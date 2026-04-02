"""StatusHistory entity — immutable audit log of delivery status transitions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.domain.value_objects.semantic_status import SemanticStatus


@dataclass(frozen=True)
class StatusHistory:
    """An immutable record of a single semantic status change on a delivery.

    One record is written when a delivery is **first seen** (``previous_*``
    fields are ``None`` — DM-BR-010).  One additional record is written for
    every subsequent status change detected by the poller (DM-BR-011).

    Records are **never modified or deleted** after creation (DM-BR-012).
    ``frozen=True`` enforces immutability at the Python dataclass level.

    Invariants:
    - ``previous_status_code`` and ``previous_semantic_status`` are ``None``
      only for the initial record when a delivery is first seen (DM-BR-010).
    - ``detected_at`` is the **poller's detection timestamp** (UTC) — it is
      NOT the carrier-side event timestamp (DM-BR-013).  Carrier timestamps
      are preserved verbatim as ``event_date_raw`` on
      :class:`~app.domain.entities.delivery_event.DeliveryEvent`.
    - Both the raw integer code and the derived semantic status are stored at
      write time and are never retroactively changed (NORM-REQ-009).
    - ``poll_log_id`` links this record to the polling cycle that detected
      the transition.  May be ``None`` for records created outside normal
      polling (e.g., during seed or manual correction).
    """

    id: UUID
    delivery_id: UUID
    previous_status_code: Optional[int]                 # None for initial entry
    previous_semantic_status: Optional[SemanticStatus]  # None for initial entry
    new_status_code: int
    new_semantic_status: SemanticStatus
    detected_at: datetime     # UTC; poller wall-clock time, NOT carrier event time
    poll_log_id: Optional[UUID] = None
