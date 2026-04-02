"""Unit tests for domain value objects.

CRITICAL: normalize_status() and get_lifecycle_group() must achieve 100%
branch coverage (NORM-REQ-012).  Both the known-code path AND the unknown/
default path are tested by separate parametrised test sets.
"""
from __future__ import annotations

import pytest

from app.domain.value_objects.lifecycle_group import (
    LifecycleGroup,
    SEMANTIC_TO_LIFECYCLE,
    get_lifecycle_group,
)
from app.domain.value_objects.semantic_status import (
    PARCEL_CODE_TO_SEMANTIC,
    SemanticStatus,
    normalize_status,
)


# ---------------------------------------------------------------------------
# normalize_status — NORM-REQ-001–010, NORM-REQ-012
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        (0, SemanticStatus.DELIVERED),
        (1, SemanticStatus.FROZEN),
        (2, SemanticStatus.IN_TRANSIT),
        (3, SemanticStatus.AWAITING_PICKUP),
        (4, SemanticStatus.OUT_FOR_DELIVERY),
        (5, SemanticStatus.NOT_FOUND),
        (6, SemanticStatus.DELIVERY_FAILED),
        (7, SemanticStatus.EXCEPTION),
        (8, SemanticStatus.INFO_RECEIVED),
    ],
)
def test_normalize_status_known_codes(code: int, expected: SemanticStatus) -> None:
    """All 9 known Parcel API integer codes map to the correct SemanticStatus.

    Covers the "code found in dict" branch of normalize_status() (NORM-REQ-012).
    """
    assert normalize_status(code) == expected


@pytest.mark.parametrize("code", [-1, 9, 99, 1000, -999])
def test_normalize_status_unknown_returns_unknown(code: int) -> None:
    """Any code outside 0–8 maps to UNKNOWN without raising (NORM-REQ-010).

    Covers the "code not in dict — use default" branch of normalize_status()
    (NORM-REQ-012).
    """
    result = normalize_status(code)
    assert result == SemanticStatus.UNKNOWN


def test_normalize_status_never_raises_for_any_integer() -> None:
    """normalize_status() is side-effect free and never raises (NORM-REq-010)."""
    for code in range(-10, 20):
        normalize_status(code)  # no exception should be raised


def test_parcel_code_to_semantic_covers_all_known_codes() -> None:
    """The PARCEL_CODE_TO_SEMANTIC mapping contains exactly codes 0–8."""
    expected_keys = set(range(9))
    assert set(PARCEL_CODE_TO_SEMANTIC.keys()) == expected_keys


def test_semantic_status_values_are_strings() -> None:
    """SemanticStatus uses str mixin — all values are JSON-serialisable strings."""
    for status in SemanticStatus:
        assert isinstance(status.value, str)
        assert isinstance(status, str)  # str mixin


# ---------------------------------------------------------------------------
# get_lifecycle_group — NORM-REQ-003–004, NORM-REQ-011–012
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected_group",
    [
        (SemanticStatus.INFO_RECEIVED, LifecycleGroup.ACTIVE),
        (SemanticStatus.IN_TRANSIT, LifecycleGroup.ACTIVE),
        (SemanticStatus.OUT_FOR_DELIVERY, LifecycleGroup.ACTIVE),
        (SemanticStatus.AWAITING_PICKUP, LifecycleGroup.ACTIVE),
        (SemanticStatus.DELIVERED, LifecycleGroup.TERMINAL),
        (SemanticStatus.FROZEN, LifecycleGroup.TERMINAL),
        (SemanticStatus.DELIVERY_FAILED, LifecycleGroup.ATTENTION),
        (SemanticStatus.EXCEPTION, LifecycleGroup.ATTENTION),
        (SemanticStatus.NOT_FOUND, LifecycleGroup.ATTENTION),
        (SemanticStatus.UNKNOWN, LifecycleGroup.ATTENTION),
    ],
)
def test_get_lifecycle_group_all_statuses(
    status: SemanticStatus, expected_group: LifecycleGroup
) -> None:
    """All 10 SemanticStatus values map to the correct LifecycleGroup.

    Covers the "status found in dict" branch of get_lifecycle_group()
    (NORM-REQ-012).
    """
    assert get_lifecycle_group(status) == expected_group


def test_semantic_to_lifecycle_covers_all_statuses() -> None:
    """Every SemanticStatus member has an explicit entry in SEMANTIC_TO_LIFECYCLE."""
    for status in SemanticStatus:
        assert status in SEMANTIC_TO_LIFECYCLE, (
            f"{status!r} is missing from SEMANTIC_TO_LIFECYCLE — "
            "add it to maintain explicit exhaustive coverage"
        )


def test_lifecycle_group_values_are_strings() -> None:
    """LifecycleGroup uses str mixin — all values are JSON-serialisable strings."""
    for group in LifecycleGroup:
        assert isinstance(group.value, str)
        assert isinstance(group, str)


def test_active_group_members() -> None:
    """ACTIVE group contains exactly the four in-progress statuses."""
    active = {
        s
        for s, g in SEMANTIC_TO_LIFECYCLE.items()
        if g == LifecycleGroup.ACTIVE
    }
    assert active == {
        SemanticStatus.INFO_RECEIVED,
        SemanticStatus.IN_TRANSIT,
        SemanticStatus.OUT_FOR_DELIVERY,
        SemanticStatus.AWAITING_PICKUP,
    }


def test_terminal_group_members() -> None:
    """TERMINAL group contains exactly DELIVERED and FROZEN."""
    terminal = {
        s
        for s, g in SEMANTIC_TO_LIFECYCLE.items()
        if g == LifecycleGroup.TERMINAL
    }
    assert terminal == {SemanticStatus.DELIVERED, SemanticStatus.FROZEN}


def test_attention_group_members() -> None:
    """ATTENTION group contains DELIVERY_FAILED, EXCEPTION, NOT_FOUND, UNKNOWN."""
    attention = {
        s
        for s, g in SEMANTIC_TO_LIFECYCLE.items()
        if g == LifecycleGroup.ATTENTION
    }
    assert attention == {
        SemanticStatus.DELIVERY_FAILED,
        SemanticStatus.EXCEPTION,
        SemanticStatus.NOT_FOUND,
        SemanticStatus.UNKNOWN,
    }


def test_normalize_then_lifecycle_roundtrip() -> None:
    """Composing normalize_status → get_lifecycle_group never raises."""
    for code in range(-2, 12):
        status = normalize_status(code)
        group = get_lifecycle_group(status)
        assert group in LifecycleGroup
