"""Unit tests for domain entities.

All tests are pure Python — no database, no HTTP, no framework fixtures.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.poll_log import PollLog, PollOutcome
from app.domain.entities.status_history import StatusHistory
from app.domain.entities.user import User
from app.domain.value_objects.semantic_status import SemanticStatus


# ---------------------------------------------------------------------------
# Delivery entity
# ---------------------------------------------------------------------------


def test_delivery_is_dataclass() -> None:
    """Delivery is a plain Python dataclass with no ORM metadata."""
    now = datetime.now(tz=timezone.utc)
    delivery = Delivery(
        id=uuid4(),
        tracking_number="TRACK001",
        carrier_code="UPS",
        description="Test parcel",
        extra_information=None,
        parcel_status_code=2,
        semantic_status=SemanticStatus.IN_TRANSIT,
        date_expected_raw=None,
        date_expected_end_raw=None,
        timestamp_expected=None,
        timestamp_expected_end=None,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    assert delivery.tracking_number == "TRACK001"
    assert delivery.carrier_code == "UPS"
    assert delivery.semantic_status == SemanticStatus.IN_TRANSIT
    assert delivery.last_raw_response is None  # default field


def test_delivery_last_raw_response_default_is_none() -> None:
    """last_raw_response defaults to None (optional field with default)."""
    now = datetime.now(tz=timezone.utc)
    delivery = Delivery(
        id=uuid4(),
        tracking_number="T",
        carrier_code="C",
        description="D",
        extra_information=None,
        parcel_status_code=0,
        semantic_status=SemanticStatus.DELIVERED,
        date_expected_raw=None,
        date_expected_end_raw=None,
        timestamp_expected=None,
        timestamp_expected_end=None,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    assert delivery.last_raw_response is None


def test_delivery_is_mutable() -> None:
    """Delivery entity is NOT frozen — fields can be updated (POLL-REQ-018)."""
    now = datetime.now(tz=timezone.utc)
    delivery = Delivery(
        id=uuid4(),
        tracking_number="T",
        carrier_code="C",
        description="D",
        extra_information=None,
        parcel_status_code=2,
        semantic_status=SemanticStatus.IN_TRANSIT,
        date_expected_raw=None,
        date_expected_end_raw=None,
        timestamp_expected=None,
        timestamp_expected_end=None,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    later = datetime.now(tz=timezone.utc)
    delivery.last_seen_at = later  # must not raise
    assert delivery.last_seen_at == later


def test_delivery_has_no_sqlalchemy_metadata() -> None:
    """Delivery must not have SQLAlchemy __tablename__ or __table__ (ARCH-DOMAIN §1)."""
    assert not hasattr(Delivery, "__tablename__")
    assert not hasattr(Delivery, "__table__")


# ---------------------------------------------------------------------------
# User entity
# ---------------------------------------------------------------------------


def test_user_repr_hides_password_hash() -> None:
    """User.__repr__ MUST NOT contain the password_hash value (security rule)."""
    user = User(
        id=1,
        username="admin",
        password_hash="$2b$10$SECRET_HASH_VALUE",
        created_at=datetime.now(tz=timezone.utc),
        is_active=True,
        token_version=1,
    )
    representation = repr(user)
    assert "SECRET_HASH_VALUE" not in representation
    assert "$2b$10$" not in representation


def test_user_repr_contains_safe_fields() -> None:
    """User.__repr__ contains non-sensitive identification fields."""
    user = User(
        id=42,
        username="alice",
        password_hash="$2b$10$anything",
        created_at=datetime.now(tz=timezone.utc),
        is_active=True,
        token_version=3,
    )
    r = repr(user)
    assert "alice" in r
    assert "42" in r
    assert "token_version=3" in r


def test_user_str_hides_password_hash() -> None:
    """str(user) also MUST NOT expose the password_hash (repr is used for str too)."""
    user = User(
        id=1,
        username="bob",
        password_hash="super_secret_bcrypt_hash",
        created_at=datetime.now(tz=timezone.utc),
        is_active=True,
        token_version=1,
    )
    assert "super_secret_bcrypt_hash" not in str(user)


def test_user_last_login_at_defaults_to_none() -> None:
    """last_login_at is None until explicitly set."""
    user = User(
        id=1,
        username="u",
        password_hash="h",
        created_at=datetime.now(tz=timezone.utc),
        is_active=True,
        token_version=0,
    )
    assert user.last_login_at is None


def test_user_is_mutable() -> None:
    """User is not frozen — token_version and last_login_at can be updated."""
    user = User(
        id=1,
        username="u",
        password_hash="h",
        created_at=datetime.now(tz=timezone.utc),
        is_active=True,
        token_version=1,
    )
    user.token_version = 2
    user.last_login_at = datetime.now(tz=timezone.utc)
    assert user.token_version == 2
    assert user.last_login_at is not None


# ---------------------------------------------------------------------------
# PollOutcome enum
# ---------------------------------------------------------------------------


def test_poll_outcome_values_are_string_serialisable() -> None:
    """PollOutcome uses str mixin — values work with JSON serialisation."""
    for outcome in PollOutcome:
        assert isinstance(outcome.value, str)
        assert isinstance(outcome, str)


def test_poll_outcome_in_progress_is_lowercase() -> None:
    """PollOutcome.IN_PROGRESS has value 'in_progress' to match VARCHAR column."""
    assert PollOutcome.IN_PROGRESS == "in_progress"
    assert PollOutcome.SUCCESS == "success"
    assert PollOutcome.PARTIAL == "partial"
    assert PollOutcome.ERROR == "error"


# ---------------------------------------------------------------------------
# StatusHistory entity
# ---------------------------------------------------------------------------


def test_status_history_is_frozen() -> None:
    """StatusHistory is frozen=True — records are immutable after creation."""
    now = datetime.now(tz=timezone.utc)
    entry = StatusHistory(
        id=uuid4(),
        delivery_id=uuid4(),
        previous_status_code=None,
        previous_semantic_status=None,
        new_status_code=2,
        new_semantic_status=SemanticStatus.IN_TRANSIT,
        detected_at=now,
    )
    with pytest.raises((AttributeError, TypeError)):
        entry.new_status_code = 3  # must raise on frozen dataclass


def test_status_history_initial_entry_has_null_previous() -> None:
    """The first StatusHistory for a delivery has None prev fields (DM-BR-010)."""
    now = datetime.now(tz=timezone.utc)
    entry = StatusHistory(
        id=uuid4(),
        delivery_id=uuid4(),
        previous_status_code=None,
        previous_semantic_status=None,
        new_status_code=8,
        new_semantic_status=SemanticStatus.INFO_RECEIVED,
        detected_at=now,
    )
    assert entry.previous_status_code is None
    assert entry.previous_semantic_status is None


# ---------------------------------------------------------------------------
# DeliveryEvent entity
# ---------------------------------------------------------------------------


def test_delivery_event_fields() -> None:
    """DeliveryEvent stores event_date_raw verbatim (DM-BR-009)."""
    now = datetime.now(tz=timezone.utc)
    event = DeliveryEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        event_description="Parcel arrived at depot",
        event_date_raw="Mon, 01 Jan 2024 10:00:00 +0000",
        location="London Hub",
        additional_info=None,
        sequence_number=0,
        recorded_at=now,
    )
    # event_date_raw is stored as-is, never parsed
    assert event.event_date_raw == "Mon, 01 Jan 2024 10:00:00 +0000"
    assert isinstance(event.event_date_raw, str)
