"""GetHealthUseCase — aggregate service health into a structured DTO."""
from __future__ import annotations

import asyncio
import logging

from app.application.dtos.system_dtos import (
    HealthDatabaseDTO,
    HealthDTO,
    HealthPollingDTO,
)
from app.application.services.interfaces import (
    AbstractDBHealthChecker,
    AbstractSchedulerState,
)
from app.domain.repositories.abstract_poll_log_repository import (
    AbstractPollLogRepository,
)

logger = logging.getLogger(__name__)

_DB_CHECK_TIMEOUT_SECONDS = 3.0
"""Hard timeout for the database connectivity check (API-REQ-016)."""

_DEGRADED_ERROR_THRESHOLD = 3
"""Number of consecutive non-SUCCESS poll outcomes that trigger 'degraded'
health status (POLL-REQ-036)."""


class GetHealthUseCase:
    """Produce a ``HealthDTO`` aggregating DB, scheduler, and polling state.

    This use case **never raises**.  Any failure in a sub-check produces a
    conservative (degraded/unhealthy) value in the corresponding DTO field so
    the caller always receives a valid response.

    The HTTP status code (200 vs 503) is determined by the **presentation
    layer** based on ``HealthDTO.status`` — not here (API-REQ-017).

    Architecture: ARCH-APPLICATION §4.7
    Requirements: API-REQ-016–018, POLL-REQ-035–036
    """

    def __init__(
        self,
        poll_log_repo: AbstractPollLogRepository,
        db_health_checker: AbstractDBHealthChecker,
        scheduler_state: AbstractSchedulerState,
    ) -> None:
        self._poll_log_repo = poll_log_repo
        self._db_health_checker = db_health_checker
        self._scheduler_state = scheduler_state

    async def execute(self) -> HealthDTO:
        """Gather all health signals and return a consolidated ``HealthDTO``.

        Returns:
            :class:`~app.application.dtos.system_dtos.HealthDTO` — always
            returned, never raises.
        """
        # ── Database check with hard timeout (API-REQ-016) ────────────────
        db_status = await self._check_database()

        # ── Polling state ──────────────────────────────────────────────────
        last_poll_log = None
        last_success = None
        consecutive_errors = 0

        try:
            recent = await self._poll_log_repo.get_recent(1)
            last_poll_log = recent[0] if recent else None
        except Exception as exc:
            logger.warning("Failed to fetch recent poll log: %s", exc)

        try:
            last_success = await self._poll_log_repo.get_last_successful()
        except Exception as exc:
            logger.warning("Failed to fetch last successful poll log: %s", exc)

        try:
            consecutive_errors = await self._poll_log_repo.count_consecutive_errors()
        except Exception as exc:
            logger.warning("Failed to count consecutive poll errors: %s", exc)

        # ── Scheduler state ────────────────────────────────────────────────
        scheduler_running = False
        next_poll_at = None
        try:
            scheduler_running = self._scheduler_state.is_running()
            next_poll_at = self._scheduler_state.get_next_poll_at()
        except Exception as exc:
            logger.warning("Failed to query scheduler state: %s", exc)

        # ── Determine overall health ───────────────────────────────────────
        if db_status.status == "disconnected" or not scheduler_running:
            overall = "unhealthy"
        elif consecutive_errors >= _DEGRADED_ERROR_THRESHOLD:
            overall = "degraded"
        else:
            overall = "healthy"

        polling_dto = HealthPollingDTO(
            scheduler_running=scheduler_running,
            last_poll_at=(
                last_poll_log.started_at if last_poll_log is not None else None
            ),
            last_poll_outcome=(
                last_poll_log.outcome.value if last_poll_log is not None else None
            ),
            last_successful_poll_at=(
                last_success.started_at if last_success is not None else None
            ),
            consecutive_errors=consecutive_errors,
            next_poll_at=next_poll_at,
        )

        from importlib.metadata import version as _pkg_version

        try:
            _version = _pkg_version("delivery-tracking")
        except Exception:
            _version = "unknown"

        return HealthDTO(
            status=overall,
            database=db_status,
            polling=polling_dto,
            version=_version,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check_database(self) -> HealthDatabaseDTO:
        """Run the DB check with a 3-second timeout (API-REQ-016).

        Returns a ``disconnected`` DTO on any failure — does NOT raise.
        """
        try:
            return await asyncio.wait_for(
                self._db_health_checker.check(),
                timeout=_DB_CHECK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Database health check timed out after %.1fs", _DB_CHECK_TIMEOUT_SECONDS)
            return HealthDatabaseDTO(status="disconnected", latency_ms=None)
        except Exception as exc:
            logger.warning("Database health check failed: %s", exc)
            return HealthDatabaseDTO(status="disconnected", latency_ms=None)
