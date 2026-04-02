from __future__ import annotations

from enum import Enum


class SemanticStatus(str, Enum):
    """Canonical status values derived from Parcel API integer status codes.

    Using ``str`` as a mixin base ensures values are JSON-serialisable
    without extra configuration.

    These values ARE stored in the ``deliveries`` and ``status_history``
    tables alongside the raw integer ``parcel_status_code`` for human
    readability.  ``LifecycleGroup`` is NEVER stored — always derived at
    runtime (NORM-REQ-004).
    """

    INFO_RECEIVED = "INFO_RECEIVED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    AWAITING_PICKUP = "AWAITING_PICKUP"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    EXCEPTION = "EXCEPTION"
    NOT_FOUND = "NOT_FOUND"
    FROZEN = "FROZEN"
    UNKNOWN = "UNKNOWN"  # sentinel for any code not in 0–8


# Authoritative mapping from ARCH-DOMAIN §3.1 and NORM-REQ-001–009.
# This dict is the single source of truth — no other translation path exists.
PARCEL_CODE_TO_SEMANTIC: dict[int, SemanticStatus] = {
    0: SemanticStatus.DELIVERED,
    1: SemanticStatus.FROZEN,
    2: SemanticStatus.IN_TRANSIT,
    3: SemanticStatus.AWAITING_PICKUP,
    4: SemanticStatus.OUT_FOR_DELIVERY,
    5: SemanticStatus.NOT_FOUND,
    6: SemanticStatus.DELIVERY_FAILED,
    7: SemanticStatus.EXCEPTION,
    8: SemanticStatus.INFO_RECEIVED,
}


def normalize_status(parcel_code: int) -> SemanticStatus:
    """Map a raw Parcel API integer status code to a ``SemanticStatus``.

    This function **never raises** for any integer input (NORM-REQ-010).
    Codes outside the range 0–8 map to ``UNKNOWN``.

    Both branches (known code / unknown code) must be covered by tests
    to satisfy the 100 % branch-coverage requirement (NORM-REQ-012).

    Args:
        parcel_code: Raw integer status code from the Parcel API response.

    Returns:
        The corresponding :class:`SemanticStatus`, or
        :attr:`SemanticStatus.UNKNOWN` for unrecognised codes.
    """
    return PARCEL_CODE_TO_SEMANTIC.get(parcel_code, SemanticStatus.UNKNOWN)
