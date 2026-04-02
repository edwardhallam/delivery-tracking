"""DeliveryORM — SQLAlchemy 2.0 table model for the ``deliveries`` table.

This class is **not** the domain entity.  It carries SQLAlchemy column
metadata, indexes, and relationship declarations.  The
:class:`~app.infrastructure.mappers.delivery_mapper.DeliveryMapper` is the
only code that translates between ``DeliveryORM`` and
:class:`~app.domain.entities.delivery.Delivery`.

ARCH-INFRASTRUCTURE §3.1
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.models.base import Base


class DeliveryORM(Base):
    """ORM model for the ``deliveries`` table.

    Business key: ``(tracking_number, carrier_code)`` — enforced by
    ``uq_delivery_tracking`` (DM-BR-001).

    ``last_raw_response`` is stored as ``JSONB`` for efficient querying
    of the most recent API payload (DM-BR-004).

    Relationships are declared with ``lazy="raise"`` to prevent accidental
    N+1 query patterns.  Repositories load related data via explicit queries,
    never via relationship access (ARCH-INFRASTRUCTURE §3.1).
    """

    __tablename__ = "deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tracking_number: Mapped[str] = mapped_column(String(255), nullable=False)
    carrier_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    extra_information: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    parcel_status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    semantic_status: Mapped[str] = mapped_column(String(50), nullable=False)
    date_expected_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_expected_end_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    timestamp_expected: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    timestamp_expected_end: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_raw_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships — lazy="raise" guards against accidental N+1 queries.
    # Repositories query child tables directly; they never access these attrs.
    events: Mapped[list["DeliveryEventORM"]] = relationship(  # type: ignore[name-defined]
        "DeliveryEventORM",
        foreign_keys="DeliveryEventORM.delivery_id",
        lazy="raise",
    )
    status_history: Mapped[list["StatusHistoryORM"]] = relationship(  # type: ignore[name-defined]
        "StatusHistoryORM",
        foreign_keys="StatusHistoryORM.delivery_id",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("tracking_number", "carrier_code", name="uq_delivery_tracking"),
        Index("idx_delivery_semantic_status", "semantic_status"),
        # B-tree index on timestamp_expected; NULLS LAST applied at query time
        Index("idx_delivery_timestamp_expected", "timestamp_expected"),
        Index("idx_delivery_last_seen", "last_seen_at"),
        Index("idx_delivery_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return (
            f"DeliveryORM(id={self.id!r}, "
            f"tracking_number={self.tracking_number!r}, "
            f"carrier_code={self.carrier_code!r}, "
            f"semantic_status={self.semantic_status!r})"
        )
