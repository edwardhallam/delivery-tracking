"""StatusHistoryORM — SQLAlchemy 2.0 table model for ``status_history``.

Status history entries are immutable once written (DM-BR-012).  Both the raw
integer code and the derived semantic status are stored at write time and are
never retroactively changed (NORM-REQ-009).

ARCH-INFRASTRUCTURE §3.3
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class StatusHistoryORM(Base):
    """ORM model for the ``status_history`` table.

    ``previous_*`` fields are ``NULL`` only on the initial entry when a
    delivery is first seen (DM-BR-010).  ``poll_log_id`` may be ``NULL``
    for records written outside normal polling (e.g. seed or manual
    correction).
    """

    __tablename__ = "status_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False
    )
    previous_status_code: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True
    )
    previous_semantic_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    new_status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    new_semantic_status: Mapped[str] = mapped_column(String(50), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    poll_log_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("poll_logs.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        # Efficient lookup of a delivery's status transitions ordered by time
        Index("idx_status_history_delivery", "delivery_id", "detected_at"),
        Index("idx_status_history_detected_at", "detected_at"),
    )

    def __repr__(self) -> str:
        return (
            f"StatusHistoryORM(id={self.id!r}, "
            f"delivery_id={self.delivery_id!r}, "
            f"new_semantic_status={self.new_semantic_status!r}, "
            f"detected_at={self.detected_at!r})"
        )
