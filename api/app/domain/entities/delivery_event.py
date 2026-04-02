"""DeliveryEvent entity — a single carrier scan or tracking event."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class DeliveryEvent:
    """A single carrier scan or tracking event associated with a delivery.

    Events are **append-only** — never updated or deleted (DM-BR-006).

    **Deduplication fingerprint**: ``(delivery_id, event_description,
    event_date_raw)`` (DM-BR-007).  Duplicate inserts are silently dropped
    at the infrastructure layer via ``ON CONFLICT DO NOTHING``, and
    :meth:`~app.domain.repositories.abstract_delivery_repository.AbstractDeliveryRepository.create_event`
    returns ``None`` for duplicates rather than raising.

    Invariants:
    - ``event_date_raw`` is stored **exactly as received** from the Parcel API
      and is **never parsed** into a :class:`~datetime.datetime`
      (DM-BR-009, DM-BR-025).  Carrier date formats are inconsistent and
      parsing would silently lose information or raise on unusual formats.
    - ``sequence_number`` reflects the ordering provided by the Parcel API
      (index 0 = oldest event) and is used for stable display ordering
      (API-REQ-014).
    """

    id: UUID
    delivery_id: UUID
    event_description: str          # TEXT; describes the tracking checkpoint
    event_date_raw: str             # max 50 chars; verbatim from API; NEVER parsed
    location: Optional[str]         # max 255 chars; nullable
    additional_info: Optional[str]  # TEXT; nullable
    sequence_number: int            # API array index; 0 = oldest; used for ASC ordering
    recorded_at: datetime           # UTC; wall-clock time this event was persisted by the poller
