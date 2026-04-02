"""Repository integration tests — requires a live test database.

Run with TEST_DATABASE_URL set, or skip if no DB is available.
The integration conftest (conftest.py in this directory) creates/drops the
schema once per session.  Each test runs in a rolled-back transaction.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_delivery
from app.application.dtos.delivery_dtos import DeliveryFilterParams
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.status_history import StatusHistory
from app.domain.entities.user import User
from app.domain.value_objects.semantic_status import SemanticStatus
from app.infrastructure.database.repositories.sqlalchemy_delivery_repository import (
    SQLAlchemyDeliveryRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _seed_delivery(session: AsyncSession, **kwargs):
    repo = SQLAlchemyDeliveryRepository(session)
    d = make_delivery(**kwargs)
    return await repo.create(d)


# ---------------------------------------------------------------------------
# Delivery snapshot — single query (POLL-REQ-015)
# ---------------------------------------------------------------------------


async def test_delivery_snapshot_three_entries(session: AsyncSession) -> None:
    """Snapshot returns a dict with one entry per seeded delivery."""
    repo = SQLAlchemyDeliveryRepository(session)

    d1 = await repo.create(make_delivery(tracking_number="T1", carrier_code="UPS"))
    d2 = await repo.create(make_delivery(tracking_number="T2", carrier_code="UPS"))
    d3 = await repo.create(make_delivery(tracking_number="T3", carrier_code="DHL"))

    snapshot = await repo.get_snapshot()
    assert len(snapshot) == 3
    assert snapshot[("T1", "UPS")] == d1.id
    assert snapshot[("T2", "UPS")] == d2.id
    assert snapshot[("T3", "DHL")] == d3.id


# ---------------------------------------------------------------------------
# Event deduplication — ON CONFLICT DO NOTHING (DM-BR-007)
# ---------------------------------------------------------------------------


async def test_create_event_deduplication(session: AsyncSession) -> None:
    """Inserting the same event twice returns None on the second attempt.

    The database count must be 1 (not 2) — confirms ON CONFLICT DO NOTHING.
    """
    repo = SQLAlchemyDeliveryRepository(session)
    delivery = await repo.create(make_delivery())
    now = _now()

    event = DeliveryEvent(
        id=uuid4(),
        delivery_id=delivery.id,
        event_description="Arrived at depot",
        event_date_raw="2024-01-01T10:00:00Z",
        location="London",
        additional_info=None,
        sequence_number=0,
        recorded_at=now,
    )

    first = await repo.create_event(event)
    assert first is not None

    # Second insert — same fingerprint (delivery_id, description, date_raw)
    duplicate = DeliveryEvent(
        id=uuid4(),  # different UUID, same fingerprint
        delivery_id=delivery.id,
        event_description="Arrived at depot",
        event_date_raw="2024-01-01T10:00:00Z",
        location="London",
        additional_info=None,
        sequence_number=0,
        recorded_at=now,
    )
    second = await repo.create_event(duplicate)
    assert second is None  # silently dropped

    # Only one event in DB
    events = await repo.get_events_for_delivery(delivery.id)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Null-last sort (API-REQ-012)
# ---------------------------------------------------------------------------


async def test_list_filtered_null_last_sort(session: AsyncSession) -> None:
    """Deliveries with NULL timestamp_expected sort LAST in ASC order (API-REQ-012)."""
    from datetime import timedelta

    repo = SQLAlchemyDeliveryRepository(session)
    now = _now()

    # Three deliveries: one with None, two with datetimes
    d_none = make_delivery(tracking_number="TNONE")
    d_none.timestamp_expected = None
    await repo.create(d_none)

    d_early = make_delivery(tracking_number="TEARLY")
    d_early.timestamp_expected = now - timedelta(days=1)
    await repo.create(d_early)

    d_late = make_delivery(tracking_number="TLATE")
    d_late.timestamp_expected = now + timedelta(days=1)
    await repo.create(d_late)

    params = DeliveryFilterParams(
        sort_by="timestamp_expected",
        sort_dir="asc",
        include_terminal=True,
    )
    items, total = await repo.list_filtered(params)

    assert total == 3
    # The delivery with None should be LAST
    assert items[-1].tracking_number == "TNONE"
    assert items[0].tracking_number == "TEARLY"


# ---------------------------------------------------------------------------
# Search parameterisation — SQL injection safety (SEC-REQ-058)
# ---------------------------------------------------------------------------


async def test_list_filtered_search_harmless_injection_attempt(
    session: AsyncSession,
) -> None:
    """An injection-style search term returns an empty list harmlessly (SEC-REQ-058)."""
    repo = SQLAlchemyDeliveryRepository(session)
    await repo.create(make_delivery(description="real package"))

    # This is not a valid description but must not raise or drop the table
    params = DeliveryFilterParams(
        search="'; DROP TABLE deliveries; --",
        include_terminal=True,
    )
    items, total = await repo.list_filtered(params)
    # The injection attempt should return zero results, not crash
    assert items == []
    assert total == 0

    # Original delivery still exists
    all_params = DeliveryFilterParams(include_terminal=True)
    all_items, all_total = await repo.list_filtered(all_params)
    assert all_total == 1


# ---------------------------------------------------------------------------
# token_version atomic increment (SEC-REQ-020)
# ---------------------------------------------------------------------------


async def test_increment_token_version_atomic(session: AsyncSession) -> None:
    """increment_token_version returns the new version and updates the DB row."""
    repo = SQLAlchemyUserRepository(session)
    now = _now()

    # id=0 is the sentinel meaning "not yet persisted" — the DB IDENTITY
    # column auto-generates the real integer PK (see UserMapper.to_orm).
    user = User(
        id=0,
        username="tokentest",
        password_hash="$2b$10$fakehash",
        created_at=now,
        is_active=True,
        token_version=1,
    )
    saved = await repo.create(user)

    new_version = await repo.increment_token_version(saved.id)
    assert new_version == 2

    # Verify the DB row was actually updated
    reloaded = await repo.get_by_username("tokentest")
    assert reloaded is not None
    assert reloaded.token_version == 2
