"""AbstractPollLogRepository — persistence contract for poll cycle audit logs."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.domain.entities.poll_log import PollLog, PollOutcome


class AbstractPollLogRepository(ABC):
    """Persistence contract for ``PollLog`` records.

    Poll logs are **append-only** audit records.  All methods are ``async``.
    """

    @abstractmethod
    async def create_in_progress(self, started_at: datetime) -> PollLog:
        """Insert a new ``PollLog`` with ``outcome=IN_PROGRESS``.

        Called at the **start** of every poll cycle, **before** the Parcel
        API request (DM-BR-018).  This guarantees every cycle is traceable
        in the audit log even if the process crashes mid-poll.

        Args:
            started_at: UTC timestamp of when the cycle began.

        Returns:
            The newly created :class:`~app.domain.entities.poll_log.PollLog`
            with ``completed_at=None``.
        """
        ...

    @abstractmethod
    async def complete(
        self,
        poll_id: UUID,
        outcome: PollOutcome,
        completed_at: datetime,
        deliveries_fetched: Optional[int],
        new_deliveries: Optional[int],
        status_changes: Optional[int],
        new_events: Optional[int],
        error_message: Optional[str],
    ) -> PollLog:
        """Finalise a ``PollLog`` record with its outcome and counters.

        Called after all per-delivery writes are complete (POLL-REQ-020).
        Executed in a **separate transaction** from the per-delivery writes
        so the log is always finalised even when individual delivery commits
        fail.

        Args:
            poll_id:           UUID of the in-progress ``PollLog`` to update.
            outcome:           Final :class:`~app.domain.entities.poll_log.PollOutcome`.
            completed_at:      UTC timestamp of cycle completion.
            deliveries_fetched: Total deliveries returned by the Parcel API.
            new_deliveries:    Deliveries not previously in the database.
            status_changes:    Deliveries whose status changed this cycle.
            new_events:        Net-new events inserted (duplicates excluded).
            error_message:     Human-readable error detail for ERROR/PARTIAL outcomes.

        Returns:
            The updated :class:`~app.domain.entities.poll_log.PollLog`.
        """
        ...

    @abstractmethod
    async def get_recent(self, limit: int = 10) -> list[PollLog]:
        """Fetch the most recent ``N`` poll logs.

        Ordered by ``started_at DESC`` (most recent first).
        """
        ...

    @abstractmethod
    async def get_last_successful(self) -> Optional[PollLog]:
        """Return the most recent ``PollLog`` with ``outcome=SUCCESS``.

        Returns ``None`` if no successful cycle has been recorded yet.
        """
        ...

    @abstractmethod
    async def count_consecutive_errors(self) -> int:
        """Count consecutive non-SUCCESS outcomes from the most recent log backward.

        Walks recent logs newest-first, counting ``ERROR`` and ``PARTIAL``
        outcomes, and stops at the first ``SUCCESS``.  An ``IN_PROGRESS``
        record (still running) does not count as an error.

        Used by :class:`~app.application.use_cases.system.get_health.GetHealthUseCase`
        to determine the ``degraded`` health threshold — three or more
        consecutive errors triggers ``degraded`` status (POLL-REQ-036).

        Returns:
            The number of consecutive non-SUCCESS outcomes.  Returns ``0``
            if the most recent completed cycle was successful.
        """
        ...
