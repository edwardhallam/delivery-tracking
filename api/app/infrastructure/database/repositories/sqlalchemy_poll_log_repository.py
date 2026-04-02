"""SQLAlchemyPollLogRepository — async SQLAlchemy implementation.

Implements :class:`~app.domain.repositories.abstract_poll_log_repository.AbstractPollLogRepository`.

ARCH-INFRASTRUCTURE §5.3
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import desc, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.poll_log import PollLog, PollOutcome
from app.domain.repositories.abstract_poll_log_repository import (
    AbstractPollLogRepository,
)
from app.infrastructure.database.models.poll_log_orm import PollLogORM
from app.infrastructure.mappers.poll_log_mapper import PollLogMapper

logger = logging.getLogger(__name__)


class SQLAlchemyPollLogRepository(AbstractPollLogRepository):
    """Concrete async repository for ``PollLog`` audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_in_progress(self, started_at: datetime) -> PollLog:
        """Insert a new ``PollLog`` with ``outcome=IN_PROGRESS`` (DM-BR-018).

        Flushed immediately so the ``poll_id`` is available for log
        correlation in the same cycle.
        """
        orm = PollLogORM(
            id=uuid4(),
            started_at=started_at,
            outcome=PollOutcome.IN_PROGRESS.value,
        )
        self._session.add(orm)
        await self._session.flush([orm])
        return PollLogMapper.to_domain(orm)

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
        """Finalise a ``PollLog`` with its outcome and counters (POLL-REQ-020).

        Uses a Core UPDATE statement so the write is immediately visible
        within the current session without a full ORM identity-map refresh.
        Re-fetches the updated row to return the complete domain entity.
        """
        stmt = (
            sa_update(PollLogORM)
            .where(PollLogORM.id == poll_id)
            .values(
                outcome=outcome.value,
                completed_at=completed_at,
                deliveries_fetched=deliveries_fetched,
                new_deliveries=new_deliveries,
                status_changes=status_changes,
                new_events=new_events,
                error_message=error_message,
            )
        )
        await self._session.execute(stmt)
        # Re-fetch the updated row.  ``populate_existing=True`` ensures the
        # ORM identity map is updated from DB values, not served the stale
        # pre-update object that ``create_in_progress`` left in the map.
        result = await self._session.execute(
            select(PollLogORM)
            .where(PollLogORM.id == poll_id)
            .execution_options(populate_existing=True)
        )
        orm = result.scalar_one()
        return PollLogMapper.to_domain(orm)

    async def get_recent(self, limit: int = 10) -> list[PollLog]:
        """Fetch the most recent ``N`` poll logs, newest first."""
        result = await self._session.execute(
            select(PollLogORM)
            .order_by(desc(PollLogORM.started_at))
            .limit(limit)
        )
        return [PollLogMapper.to_domain(row) for row in result.scalars().all()]

    async def get_last_successful(self) -> Optional[PollLog]:
        """Return the most recent ``PollLog`` with ``outcome=SUCCESS``."""
        result = await self._session.execute(
            select(PollLogORM)
            .where(PollLogORM.outcome == PollOutcome.SUCCESS.value)
            .order_by(desc(PollLogORM.started_at))
            .limit(1)
        )
        orm = result.scalars().first()
        return PollLogMapper.to_domain(orm) if orm else None

    async def count_consecutive_errors(self) -> int:
        """Count consecutive non-SUCCESS outcomes from the most recent log backward.

        Scans up to 20 recent logs to cap the query cost.  ``IN_PROGRESS``
        rows (still running) are skipped, not counted as errors (POLL-REQ-036).
        """
        rows = await self.get_recent(limit=20)
        count = 0
        for row in rows:
            if row.outcome == PollOutcome.IN_PROGRESS:
                # Skip still-running cycles; continue scanning
                continue
            if row.outcome == PollOutcome.SUCCESS:
                break
            # ERROR or PARTIAL
            count += 1
        return count
