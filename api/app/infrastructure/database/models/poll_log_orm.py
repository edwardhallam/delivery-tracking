"""PollLogORM — SQLAlchemy 2.0 table model for the ``poll_logs`` table.

Poll logs are append-only audit records retained indefinitely (DM-BR-020).
A ``CHECK`` constraint on ``outcome`` enforces the valid state machine values.

ARCH-INFRASTRUCTURE §3.5
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class PollLogORM(Base):
    """ORM model for the ``poll_logs`` table.

    A record is created with ``outcome = 'in_progress'`` **before** the
    Parcel API call (DM-BR-018).  ``completed_at = NULL`` indicates an
    interrupted or still-running cycle (DM-BR-019).  Counter fields are
    ``NULL`` until the cycle is finalised.
    """

    __tablename__ = "poll_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    deliveries_fetched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_deliveries: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_changes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_events: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('in_progress', 'success', 'partial', 'error')",
            name="ck_poll_log_outcome",
        ),
        Index("idx_poll_log_started_at", "started_at"),
        Index("idx_poll_log_outcome", "outcome"),
    )

    def __repr__(self) -> str:
        return (
            f"PollLogORM(id={self.id!r}, "
            f"outcome={self.outcome!r}, "
            f"started_at={self.started_at!r})"
        )
