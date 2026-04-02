"""PollLog entity and PollOutcome enum — operational record of each poll cycle."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class PollOutcome(str, Enum):
    """Outcome states for a completed (or in-progress) polling cycle.

    Using ``str`` as a mixin base ensures values are JSON-serialisable and
    match the ``VARCHAR(20)`` database column exactly.

    States:
        IN_PROGRESS — cycle is still executing; ``completed_at`` is ``NULL``.
        SUCCESS     — all deliveries were processed without errors.
        PARTIAL     — at least one delivery failed; others succeeded
                      (POLL-REQ-030).
        ERROR       — the cycle failed entirely (e.g. API 429, 401, or all
                      retries exhausted).
    """

    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass
class PollLog:
    """Operational record of a single Parcel API poll cycle execution.

    A ``PollLog`` is created with ``outcome=IN_PROGRESS`` **before** the
    Parcel API call (DM-BR-018).  This guarantees every cycle is traceable
    even if the process crashes mid-poll — a ``NULL`` ``completed_at`` in
    the database indicates an incomplete or interrupted cycle (DM-BR-019).

    Records are retained indefinitely (DM-BR-020).

    Invariants:
    - ``completed_at`` is ``None`` while the cycle is running or if the
      process was interrupted before finalisation (DM-BR-019).
    - All counter fields (``deliveries_fetched``, etc.) are ``None`` until
      the cycle completes via
      :meth:`~app.domain.repositories.abstract_poll_log_repository.AbstractPollLogRepository.complete`.
    - The ``complete()`` call is always executed in a **separate transaction**
      from the per-delivery writes to ensure the log is finalised even when
      individual delivery commits fail (POLL-REQ-020).
    """

    id: UUID
    started_at: datetime            # UTC; set when cycle begins (before API call)
    outcome: PollOutcome            # IN_PROGRESS until finalised
    completed_at: Optional[datetime] = None    # UTC; None = in-progress or interrupted
    deliveries_fetched: Optional[int] = None   # total deliveries returned by Parcel API
    new_deliveries: Optional[int] = None       # deliveries not previously seen
    status_changes: Optional[int] = None       # deliveries whose status changed
    new_events: Optional[int] = None           # net-new events inserted (excl. duplicates)
    error_message: Optional[str] = None        # populated when outcome=ERROR or PARTIAL
