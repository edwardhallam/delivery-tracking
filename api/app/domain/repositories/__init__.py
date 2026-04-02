"""Domain repository interfaces — persistence contracts defined in domain terms."""

from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.repositories.abstract_poll_log_repository import (
    AbstractPollLogRepository,
)
from app.domain.repositories.abstract_user_repository import (
    AbstractUserRepository,
)

__all__ = [
    "AbstractDeliveryRepository",
    "AbstractUserRepository",
    "AbstractPollLogRepository",
]
