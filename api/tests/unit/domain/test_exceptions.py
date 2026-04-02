"""Unit tests for domain exceptions.

Verifies that each exception carries the correct message and attributes,
and that the generic message pattern prevents username enumeration.
"""
from __future__ import annotations

import pytest

from app.domain.exceptions import (
    AccountDisabledError,
    AnomalousStatusTransitionError,
    DeliveryNotFoundError,
    DomainError,
    InvalidCredentialsError,
    InvalidStatusCodeError,
    TokenVersionMismatchError,
    UserNotFoundError,
)
from app.domain.value_objects.semantic_status import SemanticStatus


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


def test_all_exceptions_inherit_from_domain_error() -> None:
    """All domain exceptions must subclass DomainError."""
    for exc_class in (
        DeliveryNotFoundError,
        UserNotFoundError,
        InvalidCredentialsError,
        AccountDisabledError,
        TokenVersionMismatchError,
        InvalidStatusCodeError,
        AnomalousStatusTransitionError,
    ):
        assert issubclass(exc_class, DomainError)
        assert issubclass(exc_class, Exception)


# ---------------------------------------------------------------------------
# InvalidCredentialsError — timing-attack prevention (SEC-REQ-008)
# ---------------------------------------------------------------------------


def test_invalid_credentials_generic_message() -> None:
    """InvalidCredentialsError message MUST NOT distinguish user/password failure.

    Both "user not found" and "wrong password" must produce the same exception
    to prevent username enumeration (API-REQ-006, SEC-REQ-008).
    """
    exc = InvalidCredentialsError()
    msg = str(exc)
    # Must be generic — not "User not found" or "Password incorrect"
    assert "not found" not in msg.lower()
    assert "password" not in msg.lower()
    assert "username" not in msg.lower()
    assert "invalid credentials" in msg.lower()


def test_invalid_credentials_no_args() -> None:
    """InvalidCredentialsError takes no constructor arguments."""
    exc = InvalidCredentialsError()
    assert exc is not None
    with pytest.raises(TypeError):
        InvalidCredentialsError("extra_arg")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AnomalousStatusTransitionError — NORM-REQ-005–006
# ---------------------------------------------------------------------------


def test_anomalous_transition_stores_statuses() -> None:
    """AnomalousStatusTransitionError stores from_status and to_status attributes."""
    exc = AnomalousStatusTransitionError(
        tracking_number="TRACK999",
        from_status=SemanticStatus.DELIVERED,
        to_status=SemanticStatus.IN_TRANSIT,
    )
    assert exc.from_status == SemanticStatus.DELIVERED
    assert exc.to_status == SemanticStatus.IN_TRANSIT
    assert exc.tracking_number == "TRACK999"


def test_anomalous_transition_message_contains_statuses() -> None:
    """Error message includes both statuses for operator diagnostics."""
    exc = AnomalousStatusTransitionError(
        tracking_number="T123",
        from_status=SemanticStatus.FROZEN,
        to_status=SemanticStatus.OUT_FOR_DELIVERY,
    )
    msg = str(exc)
    assert "T123" in msg
    assert "FROZEN" in msg
    assert "OUT_FOR_DELIVERY" in msg


# ---------------------------------------------------------------------------
# DeliveryNotFoundError
# ---------------------------------------------------------------------------


def test_delivery_not_found_stores_identifier() -> None:
    """DeliveryNotFoundError stores the identifier for logging."""
    exc = DeliveryNotFoundError("abc-123")
    assert exc.identifier == "abc-123"
    assert "abc-123" in str(exc)


# ---------------------------------------------------------------------------
# UserNotFoundError
# ---------------------------------------------------------------------------


def test_user_not_found_stores_identifier() -> None:
    """UserNotFoundError stores the identifier."""
    exc = UserNotFoundError("alice")
    assert exc.identifier == "alice"
    assert "alice" in str(exc)


# ---------------------------------------------------------------------------
# AccountDisabledError
# ---------------------------------------------------------------------------


def test_account_disabled_error() -> None:
    """AccountDisabledError uses a fixed message."""
    exc = AccountDisabledError()
    assert "disabled" in str(exc).lower()


# ---------------------------------------------------------------------------
# TokenVersionMismatchError
# ---------------------------------------------------------------------------


def test_token_version_mismatch_error() -> None:
    """TokenVersionMismatchError indicates token invalidation."""
    exc = TokenVersionMismatchError()
    msg = str(exc).lower()
    assert "invalidated" in msg or "token" in msg


# ---------------------------------------------------------------------------
# InvalidStatusCodeError
# ---------------------------------------------------------------------------


def test_invalid_status_code_stores_code() -> None:
    """InvalidStatusCodeError stores the unrecognised code."""
    exc = InvalidStatusCodeError(42)
    assert exc.code == 42
    assert "42" in str(exc)
