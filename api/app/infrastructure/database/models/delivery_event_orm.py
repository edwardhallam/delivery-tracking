"""DeliveryEventORM — SQLAlchemy 2.0 table model for ``delivery_events``.

Events are append-only (DM-BR-006).  The ``uq_event_fingerprint`` unique
constraint on ``(delivery_id, event_description, event_date_raw)`` enables
the ``ON CONFLICT DO NOTHING`` deduplication pattern (DM-BR-007).

ARCH-INFRASTRUCTURE §3.2
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class DeliveryEventORM(Base):
    """ORM model for the ``delivery_events`` table.

    ``event_date_raw`` is stored **verbatim** — never parsed (DM-BR-009).
    ``sequence_number`` reflects the API array index (0 = oldest event)
    and drives ascending display order (API-REQ-014).
    """

    __tablename__ = "delivery_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False
    )
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    event_date_raw: Mapped[str] = mapped_column(String(50), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    additional_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sequence_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        # Deduplication fingerprint (DM-BR-007) — used by ON CONFLICT DO NOTHING
        UniqueConstraint(
            "delivery_id",
            "event_description",
            "event_date_raw",
            name="uq_event_fingerprint",
        ),
        # Composite index for efficient ordered fetch by delivery
        Index("idx_event_delivery_seq", "delivery_id", "sequence_number"),
    )

    def __repr__(self) -> str:
        return (
            f"DeliveryEventORM(id={self.id!r}, "
            f"delivery_id={self.delivery_id!r}, "
            f"sequence_number={self.sequence_number!r})"
        )
