"""PollLogMapper — translates between PollLogORM and PollLog domain entity.

``outcome`` is stored as a ``VARCHAR(20)`` and coerced back to the
:class:`~app.domain.entities.poll_log.PollOutcome` enum by this mapper.

ARCH-INFRASTRUCTURE §4
"""
from __future__ import annotations

from app.domain.entities.poll_log import PollLog, PollOutcome
from app.infrastructure.database.models.poll_log_orm import PollLogORM


class PollLogMapper:
    """Static mapper between :class:`PollLogORM` and :class:`PollLog`."""

    @staticmethod
    def to_domain(orm: PollLogORM) -> PollLog:
        """Convert an ORM row to a pure domain entity."""
        return PollLog(
            id=orm.id,
            started_at=orm.started_at,
            outcome=PollOutcome(orm.outcome),
            completed_at=orm.completed_at,
            deliveries_fetched=orm.deliveries_fetched,
            new_deliveries=orm.new_deliveries,
            status_changes=orm.status_changes,
            new_events=orm.new_events,
            error_message=orm.error_message,
        )

    @staticmethod
    def to_orm(entity: PollLog) -> PollLogORM:
        """Convert a domain entity to an ORM model for persistence."""
        return PollLogORM(
            id=entity.id,
            started_at=entity.started_at,
            outcome=entity.outcome.value,
            completed_at=entity.completed_at,
            deliveries_fetched=entity.deliveries_fetched,
            new_deliveries=entity.new_deliveries,
            status_changes=entity.status_changes,
            new_events=entity.new_events,
            error_message=entity.error_message,
        )
