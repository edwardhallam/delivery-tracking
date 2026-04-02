"""StatusHistoryMapper — translates between StatusHistoryORM and StatusHistory.

``previous_semantic_status`` and ``new_semantic_status`` are stored as
``VARCHAR`` in the database and coerced back to
:class:`~app.domain.value_objects.semantic_status.SemanticStatus` by this
mapper.

ARCH-INFRASTRUCTURE §4
"""
from __future__ import annotations

from typing import Optional

from app.domain.entities.status_history import StatusHistory
from app.domain.value_objects.semantic_status import SemanticStatus
from app.infrastructure.database.models.status_history_orm import StatusHistoryORM


class StatusHistoryMapper:
    """Static mapper between :class:`StatusHistoryORM` and :class:`StatusHistory`."""

    @staticmethod
    def to_domain(orm: StatusHistoryORM) -> StatusHistory:
        """Convert an ORM row to an immutable domain entity."""
        prev_semantic: Optional[SemanticStatus] = (
            SemanticStatus(orm.previous_semantic_status)
            if orm.previous_semantic_status is not None
            else None
        )
        return StatusHistory(
            id=orm.id,
            delivery_id=orm.delivery_id,
            previous_status_code=orm.previous_status_code,
            previous_semantic_status=prev_semantic,
            new_status_code=orm.new_status_code,
            new_semantic_status=SemanticStatus(orm.new_semantic_status),
            detected_at=orm.detected_at,
            poll_log_id=orm.poll_log_id,
        )

    @staticmethod
    def to_orm(entity: StatusHistory) -> StatusHistoryORM:
        """Convert a domain entity to an ORM model for persistence."""
        return StatusHistoryORM(
            id=entity.id,
            delivery_id=entity.delivery_id,
            previous_status_code=entity.previous_status_code,
            previous_semantic_status=(
                entity.previous_semantic_status.value
                if entity.previous_semantic_status is not None
                else None
            ),
            new_status_code=entity.new_status_code,
            new_semantic_status=entity.new_semantic_status.value,
            detected_at=entity.detected_at,
            poll_log_id=entity.poll_log_id,
        )
