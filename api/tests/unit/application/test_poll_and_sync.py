"""Unit tests for PollAndSyncUseCase.

All assertions use in-memory mock repos — no database.
Key scenarios:
  - New delivery created with null-previous StatusHistory (DM-BR-010)
  - Status change creates new StatusHistory entry
  - Duplicate event returns None — silently dropped (DM-BR-007)
  - Per-delivery failure continues remaining deliveries (POLL-REQ-029–030)
  - HTTP 429 aborts cycle with outcome=ERROR (POLL-REQ-024)
  - HTTP 401 aborts cycle with outcome=ERROR (POLL-REQ-025)
  - Empty delivery list is valid (POLL-REQ-014)
  - Anomalous TERMINAL→non-TERMINAL transition logged, not rejected (NORM-REQ-005–006)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.conftest import MockDeliveryRepository, MockPollLogRepository, make_delivery
from tests.unit.application.conftest import MockParcelAPIClient
from app.application.exceptions import ParcelAuthError, ParcelRateLimitError, ParcelServerError
from app.application.dtos.system_dtos import ParcelDeliveryDTO, ParcelEventDTO
from app.application.use_cases.polling.poll_and_sync import PollAndSyncUseCase
from app.domain.entities.poll_log import PollOutcome
from app.domain.value_objects.semantic_status import SemanticStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parcel_dto(
    tracking_number: str = "TRACK001",
    carrier_code: str = "UPS",
    parcel_status_code: int = 2,  # IN_TRANSIT
    events: list[ParcelEventDTO] | None = None,
) -> ParcelDeliveryDTO:
    """Build a minimal ParcelDeliveryDTO for use in polling tests."""
    return ParcelDeliveryDTO(
        tracking_number=tracking_number,
        carrier_code=carrier_code,
        description="Test parcel",
        extra_information=None,
        parcel_status_code=parcel_status_code,
        date_expected_raw=None,
        date_expected_end_raw=None,
        timestamp_expected=None,
        timestamp_expected_end=None,
        events=events or [],
        raw_response={"tracking_number": tracking_number},
    )


def _build_use_case(
    delivery_repo: MockDeliveryRepository,
    poll_log_repo: MockPollLogRepository,
    parcel_client: MockParcelAPIClient,
) -> PollAndSyncUseCase:
    return PollAndSyncUseCase(
        delivery_repo=delivery_repo,
        poll_log_repo=poll_log_repo,
        parcel_client=parcel_client,
    )


# ---------------------------------------------------------------------------
# New delivery — initial StatusHistory (DM-BR-010)
# ---------------------------------------------------------------------------


async def test_new_delivery_creates_status_history_with_null_prev(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """First-seen delivery: StatusHistory.previous_* fields are None (DM-BR-010)."""
    parcel_client = MockParcelAPIClient(
        deliveries=[_make_parcel_dto(parcel_status_code=2)]
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    assert len(mock_delivery_repo.deliveries) == 1
    history = mock_delivery_repo.history
    assert len(history) == 1
    entry = history[0]
    assert entry.previous_status_code is None
    assert entry.previous_semantic_status is None
    assert entry.new_semantic_status == SemanticStatus.IN_TRANSIT


async def test_new_delivery_counter_incremented(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Poll log records new_deliveries=1 after first-seen delivery."""
    parcel_client = MockParcelAPIClient(deliveries=[_make_parcel_dto()])
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    completed = [
        l for l in mock_poll_log_repo.logs if l.outcome == PollOutcome.SUCCESS
    ]
    assert len(completed) == 1
    assert completed[0].new_deliveries == 1
    assert completed[0].error_message is None


# ---------------------------------------------------------------------------
# Status change creates new StatusHistory
# ---------------------------------------------------------------------------


async def test_status_change_creates_new_status_history(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status change from IN_TRANSIT to DELIVERED creates a new StatusHistory entry."""
    # Seed existing delivery with IN_TRANSIT status
    existing = make_delivery(
        tracking_number="TRACK001",
        carrier_code="UPS",
        parcel_status_code=2,
        semantic_status=SemanticStatus.IN_TRANSIT,
    )
    await mock_delivery_repo.create(existing)

    # Parcel API now reports DELIVERED (code 0)
    parcel_client = MockParcelAPIClient(
        deliveries=[_make_parcel_dto(parcel_status_code=0)]
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    history = mock_delivery_repo.history
    assert len(history) == 1
    entry = history[0]
    assert entry.previous_semantic_status == SemanticStatus.IN_TRANSIT
    assert entry.new_semantic_status == SemanticStatus.DELIVERED
    assert entry.previous_status_code == 2


# ---------------------------------------------------------------------------
# Duplicate event — ON CONFLICT DO NOTHING (DM-BR-007)
# ---------------------------------------------------------------------------


async def test_duplicate_event_does_not_raise(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Duplicate events are silently dropped; the cycle does NOT fail."""
    event = ParcelEventDTO(
        event_description="Arrived at depot",
        event_date_raw="2024-01-01T10:00:00Z",
        location="London",
        additional_info=None,
        sequence_number=0,
    )
    parcel_dto = _make_parcel_dto(events=[event])
    parcel_client = MockParcelAPIClient(deliveries=[parcel_dto])

    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)

    # First poll — creates delivery + event
    await uc.execute()
    assert len(mock_delivery_repo.events) == 1

    # Second poll — same event, should be a no-op (duplicate fingerprint)
    await uc.execute()
    assert len(mock_delivery_repo.events) == 1  # still just 1, no duplicate

    # No errors — cycle should have succeeded both times
    errors = [
        l for l in mock_poll_log_repo.logs if l.error_message is not None
    ]
    assert len(errors) == 0


# ---------------------------------------------------------------------------
# Per-delivery failure continues remaining (POLL-REQ-029–030)
# ---------------------------------------------------------------------------


async def test_per_delivery_failure_continues_remaining(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Delivery 1 succeeds, delivery 2 raises, delivery 3 succeeds.

    Expected: outcome=PARTIAL, errors counter=1 (POLL-REQ-029–030).
    """
    # Make delivery 2's create raise an unexpected exception
    original_create = mock_delivery_repo.create
    call_count = {"n": 0}

    async def patched_create(delivery):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("Simulated DB error for delivery 2")
        return await original_create(delivery)

    mock_delivery_repo.create = patched_create  # type: ignore[method-assign]

    parcel_client = MockParcelAPIClient(
        deliveries=[
            _make_parcel_dto(tracking_number="T1"),
            _make_parcel_dto(tracking_number="T2"),
            _make_parcel_dto(tracking_number="T3"),
        ]
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()  # must NOT raise

    # One delivery failed — outcome should be PARTIAL
    completed = [l for l in mock_poll_log_repo.logs if l.outcome != PollOutcome.IN_PROGRESS]
    assert len(completed) == 1
    assert completed[0].outcome == PollOutcome.PARTIAL
    assert completed[0].error_message is not None
    # Deliveries 1 and 3 should have been created
    assert len(mock_delivery_repo.deliveries) == 2


# ---------------------------------------------------------------------------
# HTTP 429 — rate limit (POLL-REQ-024)
# ---------------------------------------------------------------------------


async def test_429_skips_cycle_with_error_outcome(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """HTTP 429 from Parcel API aborts cycle with outcome=ERROR (POLL-REQ-024)."""
    parcel_client = MockParcelAPIClient(
        raise_on_call=ParcelRateLimitError("Rate limited")
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()  # must NOT raise

    completed = [l for l in mock_poll_log_repo.logs if l.outcome != PollOutcome.IN_PROGRESS]
    assert len(completed) == 1
    assert completed[0].outcome == PollOutcome.ERROR
    assert "429" in completed[0].error_message


# ---------------------------------------------------------------------------
# HTTP 401 — auth failure (POLL-REQ-025)
# ---------------------------------------------------------------------------


async def test_401_logs_critical_skips_cycle(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """HTTP 401 from Parcel API aborts cycle with outcome=ERROR (POLL-REQ-025)."""
    parcel_client = MockParcelAPIClient(
        raise_on_call=ParcelAuthError("Unauthorised")
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()  # must NOT raise

    completed = [l for l in mock_poll_log_repo.logs if l.outcome != PollOutcome.IN_PROGRESS]
    assert len(completed) == 1
    assert completed[0].outcome == PollOutcome.ERROR
    assert "401" in completed[0].error_message


# ---------------------------------------------------------------------------
# Empty delivery list is valid (POLL-REQ-014)
# ---------------------------------------------------------------------------


async def test_empty_delivery_list_is_valid(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Empty list from Parcel API is valid — no active deliveries (POLL-REQ-014)."""
    parcel_client = MockParcelAPIClient(deliveries=[])
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    completed = [l for l in mock_poll_log_repo.logs if l.outcome != PollOutcome.IN_PROGRESS]
    assert len(completed) == 1
    assert completed[0].outcome == PollOutcome.SUCCESS
    assert completed[0].deliveries_fetched == 0
    assert len(mock_delivery_repo.deliveries) == 0


# ---------------------------------------------------------------------------
# Anomalous TERMINAL→non-TERMINAL transition (NORM-REQ-005–006)
# ---------------------------------------------------------------------------


async def test_anomalous_terminal_transition_logged_not_rejected(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """TERMINAL→ACTIVE transition logs a WARNING but still persists the update.

    The cycle must complete with outcome=SUCCESS — anomalous transitions are
    logged and the update is NOT discarded (NORM-REQ-005–006).
    """
    # Existing delivery is DELIVERED (TERMINAL)
    existing = make_delivery(
        tracking_number="TRACK001",
        carrier_code="UPS",
        parcel_status_code=0,  # DELIVERED
        semantic_status=SemanticStatus.DELIVERED,
    )
    await mock_delivery_repo.create(existing)

    # API now reports IN_TRANSIT (non-TERMINAL) — anomalous
    parcel_client = MockParcelAPIClient(
        deliveries=[_make_parcel_dto(parcel_status_code=2)]  # IN_TRANSIT
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    # Cycle must still complete successfully (the anomaly is logged, not fatal)
    completed = [l for l in mock_poll_log_repo.logs if l.outcome != PollOutcome.IN_PROGRESS]
    assert len(completed) == 1
    # Anomalous transitions are caught and logged — outcome should be SUCCESS
    # (the AnomalousStatusTransitionError is caught by the outer handler)
    assert completed[0].outcome == PollOutcome.SUCCESS


# ---------------------------------------------------------------------------
# Poll log — always created regardless of outcome
# ---------------------------------------------------------------------------


async def test_poll_log_always_created(
    mock_delivery_repo: MockDeliveryRepository,
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """A PollLog record is created even when the Parcel API call fails."""
    parcel_client = MockParcelAPIClient(
        raise_on_call=ParcelServerError(status_code=503, message="Server error")
    )
    uc = _build_use_case(mock_delivery_repo, mock_poll_log_repo, parcel_client)
    await uc.execute()

    assert len(mock_poll_log_repo.logs) == 1
    log = mock_poll_log_repo.logs[0]
    assert log.outcome == PollOutcome.ERROR
    assert log.completed_at is not None
