"""HTTP delivery schemas — query params and paginated response models.

All ``datetime`` fields are serialised as ISO 8601 UTC strings with a ``Z``
suffix (e.g. ``"2025-01-16T14:30:00Z"``) — never as Unix timestamps
(API-REQ-013).  The ``@field_serializer`` decorators on each model handle
this conversion; the rest of the codebase works with native ``datetime``
objects.

``DeliveryListQueryParams`` is designed to be used with FastAPI
``Depends()`` — all fields map directly to query string parameters.

Architecture: ARCH-PRESENTATION §4
Requirements: API-REQ-005, API-REQ-013, API-REQ-026–028
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as ISO 8601 UTC with Z suffix, or None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Query parameters (usable as FastAPI Depends())
# ---------------------------------------------------------------------------


class DeliveryListQueryParams(BaseModel):
    """Query parameters for GET /api/deliveries.

    Declared as a Pydantic model so FastAPI can validate and document all
    parameters automatically when used with ``Depends()``.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    """Maximum 100 items per page (API-REQ-027)."""

    lifecycle_group: Optional[Literal["ACTIVE", "ATTENTION", "TERMINAL"]] = None
    """Filter to a specific lifecycle group."""

    semantic_status: Optional[str] = None
    """Filter to a specific SemanticStatus value (e.g. ``IN_TRANSIT``)."""

    carrier_code: Optional[str] = Field(default=None, max_length=50)
    """Filter to a specific carrier code (case-sensitive)."""

    search: Optional[str] = Field(default=None, max_length=200)
    """Free-text search applied to ``description`` and ``tracking_number``
    via parameterised ILIKE (SEC-REQ-057)."""

    sort_by: Literal[
        "timestamp_expected",
        "timestamp_expected_end",
        "first_seen_at",
        "last_seen_at",
        "updated_at",
        "carrier_code",
        "tracking_number",
    ] = "timestamp_expected"

    sort_dir: Literal["asc", "desc"] = "asc"

    include_terminal: bool = False
    """When ``False`` (default), TERMINAL deliveries are excluded (API-REQ-010)."""


# ---------------------------------------------------------------------------
# Nested response schemas
# ---------------------------------------------------------------------------


class DeliveryEventSchema(BaseModel):
    """A single carrier tracking event in a delivery's timeline."""

    id: UUID
    event_description: str
    event_date_raw: str
    """Verbatim from the Parcel API — never parsed (DM-BR-009)."""
    location: Optional[str] = None
    additional_info: Optional[str] = None
    sequence_number: int
    recorded_at: datetime

    @field_serializer("recorded_at")
    def serialize_recorded_at(self, v: datetime) -> str:
        return _fmt(v) or ""


class StatusHistoryEntrySchema(BaseModel):
    """An immutable semantic-status transition record."""

    id: UUID
    previous_status_code: Optional[int] = None
    previous_semantic_status: Optional[str] = None
    new_status_code: int
    new_semantic_status: str
    detected_at: datetime

    @field_serializer("detected_at")
    def serialize_detected_at(self, v: datetime) -> str:
        return _fmt(v) or ""


# ---------------------------------------------------------------------------
# Summary and detail schemas
# ---------------------------------------------------------------------------


class DeliverySummarySchema(BaseModel):
    """Single item in the paginated delivery list response."""

    id: UUID
    tracking_number: str
    carrier_code: str
    description: str
    semantic_status: str
    lifecycle_group: str
    """Derived at serialisation time — never stored in DB (NORM-REQ-004)."""
    parcel_status_code: int
    date_expected_raw: Optional[str] = None
    date_expected_end_raw: Optional[str] = None
    timestamp_expected: Optional[datetime] = None
    timestamp_expected_end: Optional[datetime] = None
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime

    @field_serializer(
        "timestamp_expected",
        "timestamp_expected_end",
    )
    def serialize_optional_dt(self, v: Optional[datetime]) -> Optional[str]:
        return _fmt(v)

    @field_serializer("first_seen_at", "last_seen_at", "updated_at")
    def serialize_dt(self, v: datetime) -> str:
        return _fmt(v) or ""


class DeliveryDetailSchema(DeliverySummarySchema):
    """Full delivery detail including events and status history.

    All events are ordered by ``sequence_number ASC``; all status history
    entries by ``detected_at ASC`` (API-REQ-014).  Not paginated (API-REQ-015).
    """

    extra_information: Optional[str] = None
    events: list[DeliveryEventSchema]
    status_history: list[StatusHistoryEntrySchema]


# ---------------------------------------------------------------------------
# Paginated list response
# ---------------------------------------------------------------------------


class PaginatedDeliveryData(BaseModel):
    """Pagination envelope for the delivery list."""

    items: list[DeliverySummarySchema]
    total: int
    """Total matching records before pagination."""
    page: int
    page_size: int
    pages: int
    """Total page count; 0 when ``total`` is 0."""


class PaginatedDeliveryResponse(BaseModel):
    """Top-level envelope for GET /api/deliveries."""

    data: PaginatedDeliveryData


# ---------------------------------------------------------------------------
# Detail response
# ---------------------------------------------------------------------------


class DeliveryDetailResponse(BaseModel):
    """Top-level envelope for GET /api/deliveries/{delivery_id}."""

    data: DeliveryDetailSchema
