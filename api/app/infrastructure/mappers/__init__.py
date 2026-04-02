"""Infrastructure mappers — domain-to-ORM translation layer.

Each mapper provides two static methods:
- ``to_domain(orm)``  — converts an ORM row to a pure domain entity
- ``to_orm(entity)``  — converts a domain entity to an ORM model

These are the **only** places where ORM models and domain entities coexist.
"""
from app.infrastructure.mappers.delivery_event_mapper import DeliveryEventMapper
from app.infrastructure.mappers.delivery_mapper import DeliveryMapper
from app.infrastructure.mappers.poll_log_mapper import PollLogMapper
from app.infrastructure.mappers.status_history_mapper import StatusHistoryMapper
from app.infrastructure.mappers.user_mapper import UserMapper

__all__ = [
    "DeliveryMapper",
    "DeliveryEventMapper",
    "StatusHistoryMapper",
    "UserMapper",
    "PollLogMapper",
]
