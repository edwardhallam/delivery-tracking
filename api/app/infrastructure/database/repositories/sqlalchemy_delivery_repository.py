"""SQLAlchemyDeliveryRepository — async SQLAlchemy implementation.

Implements :class:`~app.domain.repositories.abstract_delivery_repository.AbstractDeliveryRepository`.
Accepts an :class:`~sqlalchemy.ext.asyncio.AsyncSession` via constructor
injection — the presentation layer provides it via ``Depends(get_async_session)``;
the polling scheduler creates a fresh session per cycle.

ARCH-INFRASTRUCTURE §5.1
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import asc, desc, func, nulls_last, or_, select, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.delivery_dtos import DeliveryFilterParams
from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.status_history import StatusHistory
from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.value_objects.lifecycle_group import LifecycleGroup, get_lifecycle_group
from app.domain.value_objects.semantic_status import SemanticStatus
from app.infrastructure.database.models.delivery_event_orm import DeliveryEventORM
from app.infrastructure.database.models.delivery_orm import DeliveryORM
from app.infrastructure.database.models.status_history_orm import StatusHistoryORM
from app.infrastructure.mappers.delivery_event_mapper import DeliveryEventMapper
from app.infrastructure.mappers.delivery_mapper import DeliveryMapper
from app.infrastructure.mappers.status_history_mapper import StatusHistoryMapper

logger = logging.getLogger(__name__)

# Allowlist of sortable columns — prevents any injection via sort_by parameter
_ALLOWED_SORT_COLUMNS: frozenset[str] = frozenset(
    {
        "timestamp_expected",
        "last_seen_at",
        "first_seen_at",
        "created_at",
        "updated_at",
        "description",
        "carrier_code",
        "semantic_status",
        "parcel_status_code",
        "tracking_number",
    }
)


class SQLAlchemyDeliveryRepository(AbstractDeliveryRepository):
    """Concrete async repository for the delivery aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_snapshot(self) -> dict[tuple[str, str], UUID]:
        """Single query; O(1) in-memory lookups during poll cycle (POLL-REQ-015)."""
        result = await self._session.execute(
            select(
                DeliveryORM.tracking_number,
                DeliveryORM.carrier_code,
                DeliveryORM.id,
            )
        )
        return {
            (row.tracking_number, row.carrier_code): row.id for row in result
        }

    async def get_by_id(self, delivery_id: UUID) -> Optional[Delivery]:
        result = await self._session.execute(
            select(DeliveryORM).where(DeliveryORM.id == delivery_id)
        )
        orm = result.scalars().first()
        return DeliveryMapper.to_domain(orm) if orm else None

    async def list_filtered(
        self,
        filter_params: DeliveryFilterParams,
    ) -> tuple[list[Delivery], int]:
        """Dynamic query builder with TERMINAL exclusion, ILIKE search,
        NULLS LAST ordering, and server-side pagination.

        ARCH-INFRASTRUCTURE §5.1 — list_filtered()
        """
        query = select(DeliveryORM)

        # ── TERMINAL exclusion (API-REQ-010) ─────────────────────────────
        if not filter_params.include_terminal:
            terminal_statuses = [
                s.value
                for s in SemanticStatus
                if get_lifecycle_group(s) == LifecycleGroup.TERMINAL
            ]
            query = query.where(
                DeliveryORM.semantic_status.not_in(terminal_statuses)
            )

        # ── lifecycle_group filter ────────────────────────────────────────
        if filter_params.lifecycle_group:
            try:
                group = LifecycleGroup(filter_params.lifecycle_group)
                statuses_in_group = [
                    s.value
                    for s in SemanticStatus
                    if get_lifecycle_group(s) == group
                ]
                query = query.where(
                    DeliveryORM.semantic_status.in_(statuses_in_group)
                )
            except ValueError:
                logger.warning(
                    "Invalid lifecycle_group filter ignored: %r",
                    filter_params.lifecycle_group,
                )

        # ── semantic_status filter ────────────────────────────────────────
        if filter_params.semantic_status:
            query = query.where(
                DeliveryORM.semantic_status == filter_params.semantic_status
            )

        # ── carrier_code filter ───────────────────────────────────────────
        if filter_params.carrier_code:
            query = query.where(
                DeliveryORM.carrier_code == filter_params.carrier_code
            )

        # ── Free-text search via parameterised ILIKE (SEC-REQ-058) ────────
        if filter_params.search:
            term = f"%{filter_params.search}%"
            query = query.where(
                or_(
                    DeliveryORM.description.ilike(term),
                    DeliveryORM.tracking_number.ilike(term),
                )
            )

        # ── Total count before pagination ─────────────────────────────────
        count_stmt = select(func.count()).select_from(query.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        # ── Validate and resolve sort column ──────────────────────────────
        sort_col_name = (
            filter_params.sort_by
            if filter_params.sort_by in _ALLOWED_SORT_COLUMNS
            else "timestamp_expected"
        )
        col = getattr(DeliveryORM, sort_col_name)
        sort_dir = filter_params.sort_dir.lower()

        # NULLS LAST for timestamp_expected (API-REQ-012)
        # Uses sqlalchemy.nulls_last() — the standalone function form is
        # safe across all SQLAlchemy 2.0 patch versions.
        if sort_col_name == "timestamp_expected":
            order_clause = (
                nulls_last(asc(col))
                if sort_dir == "asc"
                else nulls_last(desc(col))
            )
        else:
            order_clause = asc(col) if sort_dir == "asc" else desc(col)

        query = query.order_by(order_clause)

        # ── Pagination ────────────────────────────────────────────────────
        offset = (filter_params.page - 1) * filter_params.page_size
        query = query.offset(offset).limit(filter_params.page_size)

        rows = (await self._session.execute(query)).scalars().all()
        return [DeliveryMapper.to_domain(row) for row in rows], total

    async def get_events_for_delivery(self, delivery_id: UUID) -> list[DeliveryEvent]:
        """Fetch all events ordered by sequence_number ASC (API-REQ-014)."""
        result = await self._session.execute(
            select(DeliveryEventORM)
            .where(DeliveryEventORM.delivery_id == delivery_id)
            .order_by(asc(DeliveryEventORM.sequence_number))
        )
        return [
            DeliveryEventMapper.to_domain(row) for row in result.scalars().all()
        ]

    async def get_status_history_for_delivery(
        self, delivery_id: UUID
    ) -> list[StatusHistory]:
        """Fetch all status history entries ordered by detected_at ASC (API-REQ-014)."""
        result = await self._session.execute(
            select(StatusHistoryORM)
            .where(StatusHistoryORM.delivery_id == delivery_id)
            .order_by(asc(StatusHistoryORM.detected_at))
        )
        return [
            StatusHistoryMapper.to_domain(row) for row in result.scalars().all()
        ]

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def create(self, delivery: Delivery) -> Delivery:
        """Persist a new delivery record.

        Flushes immediately so subsequent FK-constrained inserts (status
        history, events) can reference the new delivery row within the
        same session transaction.
        """
        orm = DeliveryMapper.to_orm(delivery)
        self._session.add(orm)
        await self._session.flush([orm])
        return DeliveryMapper.to_domain(orm)

    async def update(self, delivery: Delivery) -> Delivery:
        """Persist mutable field changes on an existing delivery.

        Uses a Core UPDATE statement (not ORM merge) for efficiency.
        ``last_seen_at`` is always updated (POLL-REQ-018).
        Returns the input entity — all updated values originate from it.
        """
        stmt = (
            sa_update(DeliveryORM)
            .where(DeliveryORM.id == delivery.id)
            .values(
                description=delivery.description,
                extra_information=delivery.extra_information,
                parcel_status_code=delivery.parcel_status_code,
                semantic_status=delivery.semantic_status.value,
                date_expected_raw=delivery.date_expected_raw,
                date_expected_end_raw=delivery.date_expected_end_raw,
                timestamp_expected=delivery.timestamp_expected,
                timestamp_expected_end=delivery.timestamp_expected_end,
                last_seen_at=delivery.last_seen_at,
                updated_at=delivery.updated_at,
                last_raw_response=delivery.last_raw_response,
            )
        )
        await self._session.execute(stmt)
        return delivery

    async def create_event(self, event: DeliveryEvent) -> Optional[DeliveryEvent]:
        """Persist a delivery event with ON CONFLICT DO NOTHING deduplication.

        Uses PostgreSQL's ``INSERT … ON CONFLICT DO NOTHING`` on the
        ``uq_event_fingerprint`` constraint.  Returns the entity if inserted,
        or ``None`` if the fingerprint already existed (DM-BR-007).

        ``result.rowcount == 0`` indicates a no-op conflict (DM-BR-007).
        """
        stmt = (
            pg_insert(DeliveryEventORM)
            .values(
                id=event.id,
                delivery_id=event.delivery_id,
                event_description=event.event_description,
                event_date_raw=event.event_date_raw,
                location=event.location,
                additional_info=event.additional_info,
                sequence_number=event.sequence_number,
                recorded_at=event.recorded_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "delivery_id",
                    "event_description",
                    "event_date_raw",
                ]
            )
        )
        result = await self._session.execute(stmt)
        # rowcount == 1 → inserted; rowcount == 0 → conflict (already exists)
        return event if result.rowcount == 1 else None

    async def create_status_history(self, entry: StatusHistory) -> StatusHistory:
        """Append an immutable status history record."""
        orm = StatusHistoryMapper.to_orm(entry)
        self._session.add(orm)
        await self._session.flush([orm])
        return entry
