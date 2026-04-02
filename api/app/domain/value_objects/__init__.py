"""Domain value objects — immutable typed wrappers capturing domain invariants."""

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

__all__ = [
    # SemanticStatus
    "SemanticStatus",
    "PARCEL_CODE_TO_SEMANTIC",
    "normalize_status",
    # LifecycleGroup
    "LifecycleGroup",
    "SEMANTIC_TO_LIFECYCLE",
    "get_lifecycle_group",
]
