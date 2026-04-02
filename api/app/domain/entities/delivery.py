"""Delivery entity — the core tracked-parcel aggregate."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.domain.value_objects.semantic_status import SemanticStatus


@dataclass
class Delivery:
    """Core domain entity representing a single tracked parcel.

    **Business key**: ``(tracking_number, carrier_code)`` — unique per carrier
    (DM-BR-001).  Records are **never hard-deleted** (DM-BR-005).

    Invariants:
    - ``semantic_status`` is always consistent with ``parcel_status_code`` as
      mapped by :func:`~app.domain.value_objects.semantic_status.normalize_status`
      at write time (DM-BR-021).
    - ``timestamp_expected`` is the preferred field for delivery-date sorting
      (DM-BR-024).  Use it over ``date_expected_raw`` wherever possible.
    - ``date_expected_raw`` and ``date_expected_end_raw`` are stored **verbatim**
      from the Parcel API and are **never parsed** into timestamps (DM-BR-025).
    - ``last_raw_response`` holds only the **most recent** API response JSON.
      It is overwritten on every poll and is NOT a history record (DM-BR-004).
      Full event history lives in :class:`~app.domain.entities.delivery_event.DeliveryEvent`.
    - This is a pure Python dataclass — zero SQLAlchemy metadata, zero ORM
      annotations, zero FastAPI field metadata.
    """

    id: UUID
    tracking_number: str                  # max 255 chars
    carrier_code: str                     # max 50 chars
    description: str                      # max 500 chars; user label from Parcel
    extra_information: Optional[str]      # max 500 chars; nullable
    parcel_status_code: int               # raw Parcel integer 0–8 (unknown handled as UNKNOWN)
    semantic_status: SemanticStatus       # derived from parcel_status_code via normalize_status()
    date_expected_raw: Optional[str]      # max 50 chars; raw string, NEVER parsed
    date_expected_end_raw: Optional[str]  # max 50 chars; raw string, NEVER parsed
    timestamp_expected: Optional[datetime]      # UTC; derived from epoch; preferred for sorting
    timestamp_expected_end: Optional[datetime]  # UTC; derived from epoch; nullable
    first_seen_at: datetime               # UTC; set once at creation
    last_seen_at: datetime                # UTC; updated on every poll (POLL-REQ-018)
    created_at: datetime                  # UTC; DB record creation time
    updated_at: datetime                  # UTC; DB record last-updated time
    last_raw_response: Optional[dict] = field(default=None)  # most recent API JSON blob
