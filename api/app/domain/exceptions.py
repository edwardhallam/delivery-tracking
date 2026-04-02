"""Domain exceptions — business rule violations independent of delivery mechanism.

No HTTP status codes, no FastAPI imports, no framework dependencies.
The presentation layer is solely responsible for mapping these exceptions
to HTTP responses.
"""
from __future__ import annotations

from app.domain.value_objects.semantic_status import SemanticStatus


class DomainError(Exception):
    """Base class for all domain-layer exceptions."""


# ---------------------------------------------------------------------------
# Delivery exceptions
# ---------------------------------------------------------------------------


class DeliveryNotFoundError(DomainError):
    """No ``Delivery`` exists with the given identifier."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Delivery not found: {identifier}")


# ---------------------------------------------------------------------------
# User / auth exceptions
# ---------------------------------------------------------------------------


class UserNotFoundError(DomainError):
    """No ``User`` exists with the given username or ID.

    .. warning::
        The presentation layer MUST mask this as a generic 401 to prevent
        username enumeration (SEC-REQ-016).
    """

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"User not found: {identifier}")


class InvalidCredentialsError(DomainError):
    """Authentication credentials are invalid.

    The message is intentionally generic — it does **not** distinguish
    between "username not found" and "wrong password" (API-REQ-006,
    SEC-REQ-008).  This prevents username enumeration by both timing and
    response-body analysis.
    """

    def __init__(self) -> None:
        super().__init__("Invalid credentials")


class AccountDisabledError(DomainError):
    """The user account is disabled (``is_active == False``).

    Disabled accounts cannot authenticate.  The account is never hard-deleted
    (DM-BR-017); setting ``is_active = False`` is the only supported removal
    mechanism.
    """

    def __init__(self) -> None:
        super().__init__("Account is disabled")


class TokenVersionMismatchError(DomainError):
    """JWT ``token_version`` claim does not match ``users.token_version``.

    This indicates the token was issued before a logout event and should
    be treated as expired.  All outstanding tokens are invalidated by
    incrementing ``token_version`` at logout (SEC-REQ-017, SEC-REQ-020).
    """

    def __init__(self) -> None:
        super().__init__("Token has been invalidated")


# ---------------------------------------------------------------------------
# Status / transition exceptions
# ---------------------------------------------------------------------------


class InvalidStatusCodeError(DomainError):
    """An unrecognised Parcel API status code was explicitly asserted to be valid.

    This exception is **not** raised during normal polling — ``normalize_status()``
    handles unknown codes gracefully by returning ``UNKNOWN``.  It is reserved
    for explicit validation paths where an unknown code is a hard failure.
    """

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"Unrecognised Parcel status code: {code}")


class AnomalousStatusTransitionError(DomainError):
    """A TERMINAL-state delivery received a non-TERMINAL status update.

    A ``TERMINAL → non-TERMINAL`` transition is anomalous (a delivered or
    frozen parcel reappearing as active), and most likely indicates a data
    quality issue from the Parcel API.

    This error is **caught and logged at WARNING level** by the polling use
    case — the update is NOT discarded (NORM-REQ-005, NORM-REQ-006).  The
    transition is persisted because discarding it would cause permanent data
    divergence with the upstream API.
    """

    def __init__(
        self,
        tracking_number: str,
        from_status: SemanticStatus,
        to_status: SemanticStatus,
    ) -> None:
        self.tracking_number = tracking_number
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Anomalous terminal transition for {tracking_number}: "
            f"{from_status} → {to_status}"
        )
