"""GetDeliveryDetailUseCase — full delivery detail with events and history."""
from __future__ import annotations

import logging
from uuid import UUID

from app.application.dtos.delivery_dtos import (
    DeliveryDetailDTO,
    DeliveryEventDTO,
    StatusHistoryEntryDTO,
)
from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.status_history import StatusHistory
from app.domain.exceptions import DeliveryNotFoundError
from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.value_objects.lifecycle_group import get_lifecycle_group

logger = logging.getLogger(__name__)


class GetDeliveryDetailUseCase:
    """Return full delivery detail including all events and status history.

    The detail response is not paginated — all events and history records are
    returned in a single response (API-REQ-015).

    Architecture: ARCH-APPLICATION §4.5
    Requirements: API-REQ-013–015, NORM-REQ-003–004
    """

    def __init__(self, delivery_repo: AbstractDeliveryRepository) -> None:
        self._delivery_repo = delivery_repo

    async def execute(self, delivery_id: UUID) -> DeliveryDetailDTO:
        """Fetch a single delivery with its full event log and status history.

        Args:
            delivery_id: Internal UUID of the delivery.

        Returns:
            :class:`~app.application.dtos.delivery_dtos.DeliveryDetailDTO`
            with all events (``sequence_number ASC``) and status history
            (``detected_at ASC``).

        Raises:
            DeliveryNotFoundError: No delivery with ``delivery_id`` exists.
        """
        delivery = await self._delivery_repo.get_by_id(delivery_id)
        if delivery is None:
            raise DeliveryNotFoundError(str(delivery_id))

        events = await self._delivery_repo.get_events_for_delivery(delivery_id)
        history = await self._delivery_repo.get_status_history_for_delivery(delivery_id)
        lifecycle_group = get_lifecycle_group(delivery.semantic_status)

        return DeliveryDetailDTO(
            id=delivery.id,
            tracking_number=delivery.tracking_number,
            carrier_code=delivery.carrier_code,
            description=delivery.description,
            extra_information=delivery.extra_information,
            semantic_status=delivery.semantic_status.value,
            lifecycle_group=lifecycle_group.value,
            parcel_status_code=delivery.parcel_status_code,
            date_expected_raw=delivery.date_expected_raw,
            date_expected_end_raw=delivery.date_expected_end_raw,
            timestamp_expected=delivery.timestamp_expected,
            timestamp_expected_end=delivery.timestamp_expected_end,
            first_seen_at=delivery.first_seen_at,
            last_seen_at=delivery.last_seen_at,
            updated_at=delivery.updated_at,
            events=[self._to_event_dto(e) for e in events],
            status_history=[self._to_history_dto(h) for h in history],
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_event_dto(event: DeliveryEvent) -> DeliveryEventDTO:
        return DeliveryEventDTO(
            id=event.id,
            event_description=event.event_description,
            event_date_raw=event.event_date_raw,
            location=event.location,
            additional_info=event.additional_info,
            sequence_number=event.sequence_number,
            recorded_at=event.recorded_at,
        )

    @staticmethod
    def _to_history_dto(entry: StatusHistory) -> StatusHistoryEntryDTO:
        return StatusHistoryEntryDTO(
            id=entry.id,
            previous_status_code=entry.previous_status_code,
            previous_semantic_status=(
                entry.previous_semantic_status.value
                if entry.previous_semantic_status is not None
                else None
            ),
            new_status_code=entry.new_status_code,
            new_semantic_status=entry.new_semantic_status.value,
            detected_at=entry.detected_at,
        )
