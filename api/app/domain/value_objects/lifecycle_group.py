from __future__ import annotations

from enum import Enum

from app.domain.value_objects.semantic_status import SemanticStatus


class LifecycleGroup(str, Enum):
    """Broad operational category derived from a :class:`SemanticStatus`.

    Using ``str`` as a mixin base ensures values are JSON-serialisable.

    **Never stored in the database** — always derived at serialisation time
    from ``semantic_status`` (NORM-REQ-004).

    Groups:
        ACTIVE    — delivery is progressing normally toward the recipient.
        ATTENTION — delivery requires attention or is in an error state.
        TERMINAL  — delivery has reached a final, non-reversible state.
    """

    ACTIVE = "ACTIVE"
    ATTENTION = "ATTENTION"
    TERMINAL = "TERMINAL"


# Authoritative mapping from ARCH-DOMAIN §3.2.
# Every SemanticStatus value, including UNKNOWN, has an explicit entry.
SEMANTIC_TO_LIFECYCLE: dict[SemanticStatus, LifecycleGroup] = {
    SemanticStatus.INFO_RECEIVED: LifecycleGroup.ACTIVE,
    SemanticStatus.IN_TRANSIT: LifecycleGroup.ACTIVE,
    SemanticStatus.OUT_FOR_DELIVERY: LifecycleGroup.ACTIVE,
    SemanticStatus.AWAITING_PICKUP: LifecycleGroup.ACTIVE,
    SemanticStatus.DELIVERED: LifecycleGroup.TERMINAL,
    SemanticStatus.FROZEN: LifecycleGroup.TERMINAL,
    SemanticStatus.DELIVERY_FAILED: LifecycleGroup.ATTENTION,
    SemanticStatus.EXCEPTION: LifecycleGroup.ATTENTION,
    SemanticStatus.NOT_FOUND: LifecycleGroup.ATTENTION,
    SemanticStatus.UNKNOWN: LifecycleGroup.ATTENTION,
}


def get_lifecycle_group(status: SemanticStatus) -> LifecycleGroup:
    """Return the :class:`LifecycleGroup` for a given :class:`SemanticStatus`.

    This function **never raises** for any :class:`SemanticStatus` value
    (NORM-REQ-011).  :attr:`SemanticStatus.UNKNOWN` maps to
    :attr:`LifecycleGroup.ATTENTION`.

    Both branches (key present / key absent via the ``.get`` default) must
    be covered by tests to satisfy 100 % branch coverage (NORM-REQ-012).
    Because every SemanticStatus is in the mapping, the default branch is
    only reachable with a value not yet added to the enum — a forward-
    compatibility safety net rather than an expected code path.

    Args:
        status: A :class:`SemanticStatus` enum member.

    Returns:
        The corresponding :class:`LifecycleGroup`.
    """
    return SEMANTIC_TO_LIFECYCLE.get(status, LifecycleGroup.ATTENTION)
