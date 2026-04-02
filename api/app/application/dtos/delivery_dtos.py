"""Delivery DTOs — typed contracts for delivery query use cases.

These models define what the presentation layer passes in and what the use
cases return.  They contain no SQLAlchemy metadata and no FastAPI field info.
``lifecycle_group`` is always derived at serialisation time — it is never
stored in the database (NORM-REQ-004).

No SQLAlchemy, no FastAPI, no httpx imports.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------


class DeliveryFilterParams(BaseModel):
    """Input contract for the delivery list use case (GET /api/deliveries).

    Requirements: API-REQ-010–012, API-REQ-027–028.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    # Optional filters
    lifecycle_group: Optional[str] = None
    """Filter to a specific lifecycle group (ACTIVE | ATTENTION | TERMINAL)."""

    semantic_status: Optional[str] = None
    """Filter to a specific SemanticStatus value."""

    carrier_code: Optional[str] = None
    """Filter to a specific carrier code (case-sensitive)."""

    search: Optional[str] = Field(default=None, max_length=200)
    """Free-text search applied via ILIKE to ``description`` and
    ``tracking_number``.  The repository handles parameterised ILIKE — the
    use case passes this value through verbatim (SEC-REQ-058)."""

    # Sorting
    sort_by: str = "timestamp_expected"
    sort_dir: str = "asc"

    # Terminal inclusion
    include_terminal: bool = False
    """When ``False`` (the default), deliveries in the TERMINAL lifecycle group
    are excluded from results (API-REQ-010).  The filter is applied at the
    repository level."""


# ---------------------------------------------------------------------------
# Output DTOs
# ---------------------------------------------------------------------------


class DeliveryEventDTO(BaseModel):
    """A single carrier tracking event associated with a delivery."""

    id: UUID
    event_description: str
    event_date_raw: str
    """Verbatim from the Parcel API — never parsed (DM-BR-009)."""
    location: Optional[str]
    additional_info: Optional[str]
    sequence_number: int
    recorded_at: datetime


class StatusHistoryEntryDTO(BaseModel):
    """An immutable record of a single semantic status transition."""

    id: UUID
    previous_status_code: Optional[int]
    previous_semantic_status: Optional[str]
    new_status_code: int
    new_semantic_status: str
    detected_at: datetime


class DeliverySummaryDTO(BaseModel):
    """Output for a single item in the delivery list response."""

    id: UUID
    tracking_number: str
    carrier_code: str
    description: str
    semantic_status: str
    lifecycle_group: str
    """Derived at serialisation time from ``semantic_status``; never stored
    in the database (NORM-REQ-004)."""
    parcel_status_code: int
    date_expected_raw: Optional[str]
    date_expected_end_raw: Optional[str]
    timestamp_expected: Optional[datetime]
    timestamp_expected_end: Optional[datetime]
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class DeliveryDetailDTO(DeliverySummaryDTO):
    """Full delivery detail including events and status history.

    Extends ``DeliverySummaryDTO`` with event log and transition history.
    Not paginated — all records returned in full (API-REQ-015).
    """

    extra_information: Optional[str]
    events: list[DeliveryEventDTO]
    """Ordered by ``sequence_number ASC`` (API-REQ-014)."""
    status_history: list[StatusHistoryEntryDTO]
    """Ordered by ``detected_at ASC`` (API-REQ-014)."""


class DeliveryListDTO(BaseModel):
    """Paginated delivery list output for GET /api/deliveries."""

    items: list[DeliverySummaryDTO]
    total: int
    """Total matching records before pagination."""
    page: int
    page_size: int
    pages: int
    """Total number of pages; 0 when ``total`` is 0."""
