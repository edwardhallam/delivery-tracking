"""ORM model registry — imports all models to register them with Base.metadata.

Alembic and the engine both rely on ``Base.metadata`` having knowledge of all
table definitions.  Importing this package ensures every ORM class is
registered, regardless of which module imports it first.

Usage::

    from app.infrastructure.database.models import Base
    # Base.metadata now contains all 5 table definitions
"""
from app.infrastructure.database.models.base import Base
from app.infrastructure.database.models.delivery_event_orm import DeliveryEventORM
from app.infrastructure.database.models.delivery_orm import DeliveryORM
from app.infrastructure.database.models.poll_log_orm import PollLogORM
from app.infrastructure.database.models.status_history_orm import StatusHistoryORM
from app.infrastructure.database.models.user_orm import UserORM

__all__ = [
    "Base",
    "DeliveryORM",
    "DeliveryEventORM",
    "StatusHistoryORM",
    "UserORM",
    "PollLogORM",
]
