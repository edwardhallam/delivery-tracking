"""Mapper integration tests — round-trip domain ↔ ORM conversions.

These tests are pure Python (no DB connection needed) — mappers are
stateless translation functions.  They verify that no information is lost
when an entity crosses the infrastructure boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.conftest import make_delivery
from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.poll_log import PollLog, PollOutcome
from app.domain.entities.status_history import StatusHistory
from app.domain.entities.user import User
from app.domain.value_objects.semantic_status import SemanticStatus
from app.infrastructure.mappers.delivery_mapper import DeliveryMapper
from app.infrastructure.mappers.delivery_event_mapper import DeliveryEventMapper
from app.infrastructure.mappers.status_history_mapper import StatusHistoryMapper
from app.infrastructure.mappers.poll_log_mapper import PollLogMapper
from app.infrastructure.mappers.user_mapper import UserMapper


# ---------------------------------------------------------------------------
# DeliveryMapper
# ---------------------------------------------------------------------------


def test_delivery_mapper_round_trip() -> None:
    """to_domain(to_orm(delivery)) == delivery for all fields."""
    original = make_delivery(
        tracking_number="ROUNDTRIP123",
        carrier_code="FedEx",
        parcel_status_code=2,
        semantic_status=SemanticStatus.IN_TRANSIT,
    )

    orm = DeliveryMapper.to_orm(original)
    restored = DeliveryMapper.to_domain(orm)

    assert restored.id == original.id
    assert restored.tracking_number == original.tracking_number
    assert restored.carrier_code == original.carrier_code
    assert restored.description == original.description
    assert restored.parcel_status_code == original.parcel_status_code
    assert restored.semantic_status == original.semantic_status
    assert restored.extra_information == original.extra_information
    assert restored.date_expected_raw == original.date_expected_raw
    assert restored.timestamp_expected == original.timestamp_expected
    assert restored.first_seen_at == original.first_seen_at
    assert restored.last_raw_response == original.last_raw_response


def test_delivery_enum_roundtrip_all_statuses() -> None:
    """Every SemanticStatus survives the ORM ↔ domain round-trip."""
    for status in SemanticStatus:
        delivery = make_delivery(
            semantic_status=status,
            parcel_status_code=0,
        )
        orm = DeliveryMapper.to_orm(delivery)
        assert orm.semantic_status == status.value
        restored = DeliveryMapper.to_domain(orm)
        assert restored.semantic_status == status


def test_delivery_to_orm_stores_semantic_status_as_string() -> None:
    """ORM model stores semantic_status as a plain string value."""
    delivery = make_delivery(semantic_status=SemanticStatus.DELIVERED)
    orm = DeliveryMapper.to_orm(delivery)
    assert orm.semantic_status == "DELIVERED"
    assert isinstance(orm.semantic_status, str)


def test_delivery_to_orm_preserves_none_fields() -> None:
    """Optional fields survive round-trip as None."""
    delivery = make_delivery()  # all optional fields are None
    orm = DeliveryMapper.to_orm(delivery)
    assert orm.extra_information is None
    assert orm.date_expected_raw is None
    assert orm.timestamp_expected is None
    assert orm.last_raw_response is None

    restored = DeliveryMapper.to_domain(orm)
    assert restored.extra_information is None
    assert restored.date_expected_raw is None


# ---------------------------------------------------------------------------
# DeliveryEventMapper
# ---------------------------------------------------------------------------


def test_delivery_event_mapper_round_trip() -> None:
    """DeliveryEvent survives ORM round-trip unchanged."""
    now = datetime.now(tz=timezone.utc)
    event = DeliveryEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        event_description="Parcel arrived at sort facility",
        event_date_raw="Tue, 02 Jan 2024 08:30:00 +0000",
        location="Birmingham Hub",
        additional_info="Next scan expected in 2 hours",
        sequence_number=3,
        recorded_at=now,
    )

    orm = DeliveryEventMapper.to_orm(event)
    restored = DeliveryEventMapper.to_domain(orm)

    assert restored.id == event.id
    assert restored.delivery_id == event.delivery_id
    assert restored.event_description == event.event_description
    assert restored.event_date_raw == event.event_date_raw
    assert restored.location == event.location
    assert restored.additional_info == event.additional_info
    assert restored.sequence_number == event.sequence_number


# ---------------------------------------------------------------------------
# StatusHistoryMapper
# ---------------------------------------------------------------------------


def test_status_history_mapper_round_trip() -> None:
    """StatusHistory round-trips with both previous fields as None (initial entry)."""
    now = datetime.now(tz=timezone.utc)
    entry = StatusHistory(
        id=uuid4(),
        delivery_id=uuid4(),
        previous_status_code=None,
        previous_semantic_status=None,
        new_status_code=8,
        new_semantic_status=SemanticStatus.INFO_RECEIVED,
        detected_at=now,
        poll_log_id=None,
    )

    orm = StatusHistoryMapper.to_orm(entry)
    restored = StatusHistoryMapper.to_domain(orm)

    assert restored.id == entry.id
    assert restored.previous_status_code is None
    assert restored.previous_semantic_status is None
    assert restored.new_semantic_status == SemanticStatus.INFO_RECEIVED


def test_status_history_mapper_round_trip_with_previous() -> None:
    """StatusHistory with previous fields round-trips correctly."""
    now = datetime.now(tz=timezone.utc)
    entry = StatusHistory(
        id=uuid4(),
        delivery_id=uuid4(),
        previous_status_code=2,
        previous_semantic_status=SemanticStatus.IN_TRANSIT,
        new_status_code=0,
        new_semantic_status=SemanticStatus.DELIVERED,
        detected_at=now,
    )

    orm = StatusHistoryMapper.to_orm(entry)
    restored = StatusHistoryMapper.to_domain(orm)

    assert restored.previous_status_code == 2
    assert restored.previous_semantic_status == SemanticStatus.IN_TRANSIT
    assert restored.new_semantic_status == SemanticStatus.DELIVERED


def test_poll_outcome_roundtrip_all_values() -> None:
    """Every PollOutcome value survives PollLog round-trip."""
    now = datetime.now(tz=timezone.utc)
    for outcome in PollOutcome:
        log = PollLog(
            id=uuid4(),
            started_at=now,
            outcome=outcome,
            completed_at=now if outcome != PollOutcome.IN_PROGRESS else None,
        )
        orm = PollLogMapper.to_orm(log)
        restored = PollLogMapper.to_domain(orm)
        assert restored.outcome == outcome
