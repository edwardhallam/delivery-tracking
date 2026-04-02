"""DeliveryEventMapper — translates between DeliveryEventORM and DeliveryEvent.

ARCH-INFRASTRUCTURE §4
"""
from __future__ import annotations

from app.domain.entities.delivery_event import DeliveryEvent
from app.infrastructure.database.models.delivery_event_orm import DeliveryEventORM


class DeliveryEventMapper:
    """Static mapper between :class:`DeliveryEventORM` and :class:`DeliveryEvent`."""

    @staticmethod
    def to_domain(orm: DeliveryEventORM) -> DeliveryEvent:
        """Convert an ORM row to a pure domain entity."""
        return DeliveryEvent(
            id=orm.id,
            delivery_id=orm.delivery_id,
            event_description=orm.event_description,
            event_date_raw=orm.event_date_raw,
            location=orm.location,
            additional_info=orm.additional_info,
            sequence_number=orm.sequence_number,
            recorded_at=orm.recorded_at,
        )

    @staticmethod
    def to_orm(entity: DeliveryEvent) -> DeliveryEventORM:
        """Convert a domain entity to an ORM model for persistence."""
        return DeliveryEventORM(
            id=entity.id,
            delivery_id=entity.delivery_id,
            event_description=entity.event_description,
            event_date_raw=entity.event_date_raw,
            location=entity.location,
            additional_info=entity.additional_info,
            sequence_number=entity.sequence_number,
            recorded_at=entity.recorded_at,
        )
