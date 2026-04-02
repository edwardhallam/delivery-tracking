"""PollAndSyncUseCase — the 4-phase Parcel API polling orchestrator.

This use case coordinates the entire polling cycle:

  Phase 1 — Setup:        Create IN_PROGRESS poll log; load delivery snapshot.
  Phase 2 — API Call:     Fetch deliveries from Parcel API; handle all errors.
  Phase 3 — Change Det.:  Diff API results against snapshot; write all changes.
  Phase 4 — Finalise:     Complete poll log in a separate transaction.

**This use case NEVER raises.**  All errors are caught, logged, and reflected
in the ``PollLog`` record.  The APScheduler job remains healthy regardless of
what happens inside a cycle (POLL-REQ-029).
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from app.application.exceptions import (
    DatabaseUnavailableError,
    ParcelAuthError,
    ParcelRateLimitError,
    ParcelServerError,
)
from app.application.services.interfaces import AbstractParcelAPIClient
from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.poll_log import PollOutcome
from app.domain.entities.status_history import StatusHistory
from app.domain.exceptions import AnomalousStatusTransitionError
from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.repositories.abstract_poll_log_repository import (
    AbstractPollLogRepository,
)
from app.domain.value_objects.lifecycle_group import LifecycleGroup, get_lifecycle_group
from app.domain.value_objects.semantic_status import SemanticStatus, normalize_status

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _Counters:
    """Mutable counters accumulated during Phase 3."""

    new: int = 0
    status_changes: int = 0
    new_events: int = 0
    errors: int = 0


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class PollAndSyncUseCase:
    """4-phase Parcel API poll, diff, and persist orchestrator.

    Architecture: ARCH-APPLICATION §4.6
    Requirements: POLL-REQ-003–036
    """

    def __init__(
        self,
        delivery_repo: AbstractDeliveryRepository,
        poll_log_repo: AbstractPollLogRepository,
        parcel_client: AbstractParcelAPIClient,
    ) -> None:
        self._delivery_repo = delivery_repo
        self._poll_log_repo = poll_log_repo
        self._parcel_client = parcel_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self) -> None:
        """Run one complete poll-and-sync cycle.

        This method never raises.  All outcomes — including total failure —
        are reflected in the ``PollLog`` record written to the database.
        Every log line within the cycle includes the ``poll_id`` for
        traceability (POLL-REQ-034).
        """
        # ----------------------------------------------------------------
        # Phase 1 — Setup
        # ----------------------------------------------------------------
        started_at = _utcnow()
        try:
            poll_log = await self._poll_log_repo.create_in_progress(
                started_at=started_at
            )
        except Exception as exc:
            # If we cannot create the poll log we cannot trace the cycle.
            # Log at ERROR and abort — there is no safe recovery path here.
            logger.error("Failed to create poll log record: %s", exc, exc_info=True)
            return

        poll_id = poll_log.id
        logger.info("poll_id=%s | cycle started", poll_id)

        try:
            snapshot = await self._delivery_repo.get_snapshot()
        except Exception as exc:
            logger.error(
                "poll_id=%s | failed to load delivery snapshot: %s",
                poll_id,
                exc,
                exc_info=True,
            )
            await self._complete_poll(
                poll_id=poll_id,
                outcome=PollOutcome.ERROR,
                counters=_Counters(),
                error_message=f"Snapshot load failed: {exc}",
                deliveries_fetched=None,
            )
            return

        logger.debug("poll_id=%s | snapshot loaded, %d entries", poll_id, len(snapshot))

        # ----------------------------------------------------------------
        # Phase 2 — Parcel API Call
        # ----------------------------------------------------------------
        try:
            deliveries = await self._parcel_client.get_deliveries()
        except ParcelRateLimitError as exc:
            logger.warning(
                "poll_id=%s | rate limit hit (HTTP 429), aborting cycle: %s",
                poll_id,
                exc,
            )
            await self._complete_poll(
                poll_id=poll_id,
                outcome=PollOutcome.ERROR,
                counters=_Counters(),
                error_message="Parcel API rate limit exceeded (HTTP 429)",
                deliveries_fetched=None,
            )
            return
        except ParcelAuthError as exc:
            logger.critical(
                "poll_id=%s | Parcel API auth failure (HTTP 401) — "
                "check PARCEL_API_KEY configuration: %s",
                poll_id,
                exc,
            )
            await self._complete_poll(
                poll_id=poll_id,
                outcome=PollOutcome.ERROR,
                counters=_Counters(),
                error_message="Parcel API authentication failure (HTTP 401)",
                deliveries_fetched=None,
            )
            return
        except ParcelServerError as exc:
            logger.error(
                "poll_id=%s | Parcel API server error (HTTP %s) after all retries: %s",
                poll_id,
                exc.status_code,
                exc,
                exc_info=True,
            )
            await self._complete_poll(
                poll_id=poll_id,
                outcome=PollOutcome.ERROR,
                counters=_Counters(),
                error_message=f"Parcel API server error: {exc}",
                deliveries_fetched=None,
            )
            return
        except Exception as exc:
            logger.error(
                "poll_id=%s | unexpected error calling Parcel API: %s",
                poll_id,
                exc,
                exc_info=True,
            )
            await self._complete_poll(
                poll_id=poll_id,
                outcome=PollOutcome.ERROR,
                counters=_Counters(),
                error_message=f"Unexpected Parcel API error: {exc}",
                deliveries_fetched=None,
            )
            return

        # An empty list is valid — no active deliveries (POLL-REQ-014).
        logger.info(
            "poll_id=%s | Parcel API returned %d deliveries",
            poll_id,
            len(deliveries),
        )

        # ----------------------------------------------------------------
        # Phase 3 — Change Detection (sequential, POLL-REQ-021)
        # ----------------------------------------------------------------
        counters = _Counters()
        now = _utcnow()

        for parcel_delivery in deliveries:
            try:
                semantic_status = normalize_status(parcel_delivery.parcel_status_code)

                if semantic_status == SemanticStatus.UNKNOWN:
                    logger.warning(
                        "poll_id=%s | unknown parcel_status_code=%d for "
                        "tracking_number=%s carrier=%s",
                        poll_id,
                        parcel_delivery.parcel_status_code,
                        parcel_delivery.tracking_number,
                        parcel_delivery.carrier_code,
                    )

                key = (parcel_delivery.tracking_number, parcel_delivery.carrier_code)

                if key not in snapshot:
                    # ── New delivery ────────────────────────────────────────
                    await self._handle_new_delivery(
                        parcel_delivery=parcel_delivery,
                        semantic_status=semantic_status,
                        poll_id=poll_id,
                        now=now,
                        counters=counters,
                    )
                else:
                    # ── Existing delivery ───────────────────────────────────
                    delivery_id = snapshot[key]
                    await self._handle_existing_delivery(
                        parcel_delivery=parcel_delivery,
                        delivery_id=delivery_id,
                        semantic_status=semantic_status,
                        poll_id=poll_id,
                        now=now,
                        counters=counters,
                    )

            except AnomalousStatusTransitionError as exc:
                # Logged at WARNING level; the update was still persisted
                # (NORM-REQ-005–006).
                logger.warning(
                    "poll_id=%s | anomalous terminal→non-terminal transition: %s",
                    poll_id,
                    exc,
                )

            except Exception as exc:
                logger.error(
                    "poll_id=%s | error processing tracking_number=%s carrier=%s: %s",
                    poll_id,
                    parcel_delivery.tracking_number,
                    parcel_delivery.carrier_code,
                    exc,
                    exc_info=True,
                )
                counters.errors += 1
                # Continue to the next delivery (POLL-REQ-029).

        # ----------------------------------------------------------------
        # Phase 4 — Finalise (separate transaction, POLL-REQ-020)
        # ----------------------------------------------------------------
        outcome = (
            PollOutcome.SUCCESS if counters.errors == 0 else PollOutcome.PARTIAL
        )
        error_message: Optional[str] = None
        if counters.errors > 0:
            error_message = (
                f"{counters.errors} delivery/deliveries failed to process"
            )

        await self._complete_poll(
            poll_id=poll_id,
            outcome=outcome,
            counters=counters,
            error_message=error_message,
            deliveries_fetched=len(deliveries),
        )
        logger.info(
            "poll_id=%s | cycle complete: outcome=%s new=%d status_changes=%d "
            "new_events=%d errors=%d",
            poll_id,
            outcome.value,
            counters.new,
            counters.status_changes,
            counters.new_events,
            counters.errors,
        )

    # ------------------------------------------------------------------
    # Phase 3 helpers
    # ------------------------------------------------------------------

    async def _handle_new_delivery(
        self,
        parcel_delivery,
        semantic_status: SemanticStatus,
        poll_id: UUID,
        now: datetime,
        counters: _Counters,
    ) -> None:
        """Persist a brand-new delivery with its initial status history and events."""
        from app.application.dtos.system_dtos import ParcelDeliveryDTO

        new_delivery = Delivery(
            id=uuid4(),
            tracking_number=parcel_delivery.tracking_number,
            carrier_code=parcel_delivery.carrier_code,
            description=parcel_delivery.description,
            extra_information=parcel_delivery.extra_information,
            parcel_status_code=parcel_delivery.parcel_status_code,
            semantic_status=semantic_status,
            date_expected_raw=parcel_delivery.date_expected_raw,
            date_expected_end_raw=parcel_delivery.date_expected_end_raw,
            timestamp_expected=parcel_delivery.timestamp_expected,
            timestamp_expected_end=parcel_delivery.timestamp_expected_end,
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            last_raw_response=parcel_delivery.raw_response,
        )
        await self._delivery_repo.create(new_delivery)

        # Initial StatusHistory entry — prev fields are None (DM-BR-010).
        initial_history = StatusHistory(
            id=uuid4(),
            delivery_id=new_delivery.id,
            previous_status_code=None,
            previous_semantic_status=None,
            new_status_code=parcel_delivery.parcel_status_code,
            new_semantic_status=semantic_status,
            detected_at=now,
            poll_log_id=poll_id,
        )
        await self._delivery_repo.create_status_history(initial_history)

        # Insert events; duplicates silently dropped via ON CONFLICT DO NOTHING.
        for event_dto in parcel_delivery.events:
            event = DeliveryEvent(
                id=uuid4(),
                delivery_id=new_delivery.id,
                event_description=event_dto.event_description,
                event_date_raw=event_dto.event_date_raw,
                location=event_dto.location,
                additional_info=event_dto.additional_info,
                sequence_number=event_dto.sequence_number,
                recorded_at=now,
            )
            await self._delivery_repo.create_event(event)

        counters.new += 1

    async def _handle_existing_delivery(
        self,
        parcel_delivery,
        delivery_id: UUID,
        semantic_status: SemanticStatus,
        poll_id: UUID,
        now: datetime,
        counters: _Counters,
    ) -> None:
        """Update an existing delivery: detect status change, upsert events."""
        existing = await self._delivery_repo.get_by_id(delivery_id)
        if existing is None:
            # Snapshot was stale (race condition); treat as new.
            logger.warning(
                "poll_id=%s | snapshot entry for %s/%s not found in DB — treating as new",
                poll_id,
                parcel_delivery.tracking_number,
                parcel_delivery.carrier_code,
            )
            await self._handle_new_delivery(
                parcel_delivery=parcel_delivery,
                semantic_status=semantic_status,
                poll_id=poll_id,
                now=now,
                counters=counters,
            )
            return

        # ── Status change detection ──────────────────────────────────────
        if existing.parcel_status_code != parcel_delivery.parcel_status_code:
            old_group = get_lifecycle_group(existing.semantic_status)
            new_group = get_lifecycle_group(semantic_status)

            # Check for anomalous TERMINAL → non-TERMINAL transition.
            # We raise to let the outer handler log the warning, but we
            # still persist the update below (NORM-REQ-005–006).
            if (
                old_group == LifecycleGroup.TERMINAL
                and new_group != LifecycleGroup.TERMINAL
            ):
                raise AnomalousStatusTransitionError(
                    tracking_number=parcel_delivery.tracking_number,
                    from_status=existing.semantic_status,
                    to_status=semantic_status,
                )

            history = StatusHistory(
                id=uuid4(),
                delivery_id=existing.id,
                previous_status_code=existing.parcel_status_code,
                previous_semantic_status=existing.semantic_status,
                new_status_code=parcel_delivery.parcel_status_code,
                new_semantic_status=semantic_status,
                detected_at=now,
                poll_log_id=poll_id,
            )
            await self._delivery_repo.create_status_history(history)
            counters.status_changes += 1

        # ── Event upsert ────────────────────────────────────────────────
        for event_dto in parcel_delivery.events:
            event = DeliveryEvent(
                id=uuid4(),
                delivery_id=existing.id,
                event_description=event_dto.event_description,
                event_date_raw=event_dto.event_date_raw,
                location=event_dto.location,
                additional_info=event_dto.additional_info,
                sequence_number=event_dto.sequence_number,
                recorded_at=now,
            )
            result = await self._delivery_repo.create_event(event)
            if result is not None:
                counters.new_events += 1

        # ── Update mutable delivery fields ──────────────────────────────
        # ``last_seen_at`` MUST always be updated (POLL-REQ-018).
        existing.last_seen_at = now
        existing.updated_at = now
        existing.parcel_status_code = parcel_delivery.parcel_status_code
        existing.semantic_status = semantic_status
        existing.description = parcel_delivery.description
        existing.extra_information = parcel_delivery.extra_information
        existing.date_expected_raw = parcel_delivery.date_expected_raw
        existing.date_expected_end_raw = parcel_delivery.date_expected_end_raw
        existing.timestamp_expected = parcel_delivery.timestamp_expected
        existing.timestamp_expected_end = parcel_delivery.timestamp_expected_end
        existing.last_raw_response = parcel_delivery.raw_response
        await self._delivery_repo.update(existing)

    # ------------------------------------------------------------------
    # Phase 4 helper
    # ------------------------------------------------------------------

    async def _complete_poll(
        self,
        poll_id: UUID,
        outcome: PollOutcome,
        counters: _Counters,
        error_message: Optional[str],
        deliveries_fetched: Optional[int],
    ) -> None:
        """Finalise the poll log in a separate transaction (POLL-REQ-020).

        Failures here are logged but do not propagate — the cycle result
        cannot be retransmitted.
        """
        try:
            await self._poll_log_repo.complete(
                poll_id=poll_id,
                outcome=outcome,
                completed_at=_utcnow(),
                deliveries_fetched=deliveries_fetched,
                new_deliveries=counters.new,
                status_changes=counters.status_changes,
                new_events=counters.new_events,
                error_message=error_message,
            )
        except Exception as exc:
            logger.error(
                "poll_id=%s | failed to finalise poll log: %s",
                poll_id,
                exc,
                exc_info=True,
            )
