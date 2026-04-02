"""DeliveryMapper — translates between DeliveryORM and Delivery domain entity.

This is the **only** code that crosses the ORM/domain boundary for deliveries.
The domain entity is a pure Python dataclass; the ORM model carries SQLAlchemy
column metadata.  Keeping them separate ensures the domain layer remains
100% free of SQLAlchemy instrumentation and independently testable.

ARCH-INFRASTRUCTURE §4
"""
from __future__ import annotations

from app.domain.entities.delivery import Delivery
from app.domain.value_objects.semantic_status import SemanticStatus
from app.infrastructure.database.models.delivery_orm import DeliveryORM


class DeliveryMapper:
    """Static mapper between :class:`DeliveryORM` and :class:`Delivery`."""

    @staticmethod
    def to_domain(orm: DeliveryORM) -> Delivery:
        """Convert an ORM row to a pure domain entity.

        ``semantic_status`` is coerced from its ``VARCHAR`` database value
        back to the :class:`~app.domain.value_objects.semantic_status.SemanticStatus`
        enum.  Any stored value that is no longer in the enum will raise
        ``ValueError`` — this indicates a data migration is required.
        """
        return Delivery(
            id=orm.id,
            tracking_number=orm.tracking_number,
            carrier_code=orm.carrier_code,
            description=orm.description,
            extra_information=orm.extra_information,
            parcel_status_code=orm.parcel_status_code,
            semantic_status=SemanticStatus(orm.semantic_status),
            date_expected_raw=orm.date_expected_raw,
            date_expected_end_raw=orm.date_expected_end_raw,
            timestamp_expected=orm.timestamp_expected,
            timestamp_expected_end=orm.timestamp_expected_end,
            first_seen_at=orm.first_seen_at,
            last_seen_at=orm.last_seen_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            last_raw_response=orm.last_raw_response,
        )

    @staticmethod
    def to_orm(entity: Delivery) -> DeliveryORM:
        """Convert a domain entity to an ORM model for persistence.

        ``semantic_status`` is stored as its string ``value`` (the
        ``VARCHAR`` column stores e.g. ``'IN_TRANSIT'``, not the enum
        object itself).
        """
        return DeliveryORM(
            id=entity.id,
            tracking_number=entity.tracking_number,
            carrier_code=entity.carrier_code,
            description=entity.description,
            extra_information=entity.extra_information,
            parcel_status_code=entity.parcel_status_code,
            semantic_status=entity.semantic_status.value,
            date_expected_raw=entity.date_expected_raw,
            date_expected_end_raw=entity.date_expected_end_raw,
            timestamp_expected=entity.timestamp_expected,
            timestamp_expected_end=entity.timestamp_expected_end,
            first_seen_at=entity.first_seen_at,
            last_seen_at=entity.last_seen_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            last_raw_response=entity.last_raw_response,
        )
