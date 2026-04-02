"""GetDeliveriesUseCase — filtered, paginated delivery list."""
from __future__ import annotations

import math
import logging
from uuid import UUID

from app.application.dtos.delivery_dtos import (
    DeliveryFilterParams,
    DeliveryListDTO,
    DeliverySummaryDTO,
)
from app.domain.entities.delivery import Delivery
from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.value_objects.lifecycle_group import get_lifecycle_group

logger = logging.getLogger(__name__)


class GetDeliveriesUseCase:
    """Return a filtered, sorted, paginated list of deliveries.

    ``lifecycle_group`` is derived on each delivery at serialisation time and
    is never stored in the database (NORM-REQ-004).

    Architecture: ARCH-APPLICATION §4.4
    Requirements: API-REQ-010–012, API-REQ-027–028, NORM-REQ-003–004
    """

    def __init__(self, delivery_repo: AbstractDeliveryRepository) -> None:
        self._delivery_repo = delivery_repo

    async def execute(self, params: DeliveryFilterParams) -> DeliveryListDTO:
        """Fetch and map a paginated list of deliveries.

        The repository handles:
        - ``include_terminal=False`` filtering (excludes TERMINAL lifecycle group)
        - Parameterised ILIKE for ``search`` (SEC-REQ-058)
        - NULLS-LAST ordering for ``timestamp_expected`` (API-REQ-012)
        - Pagination via ``page`` and ``page_size``

        A page number beyond the last page returns an empty ``items`` list,
        not an error (API-REQ-028).

        Args:
            params: Filter, sort, and pagination parameters.

        Returns:
            :class:`~app.application.dtos.delivery_dtos.DeliveryListDTO`
            with summary items and pagination metadata.
        """
        deliveries, total = await self._delivery_repo.list_filtered(params)

        items = [self._to_summary_dto(delivery) for delivery in deliveries]
        pages = math.ceil(total / params.page_size) if total > 0 else 0

        return DeliveryListDTO(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_summary_dto(delivery: Delivery) -> DeliverySummaryDTO:
        lifecycle_group = get_lifecycle_group(delivery.semantic_status)
        return DeliverySummaryDTO(
            id=delivery.id,
            tracking_number=delivery.tracking_number,
            carrier_code=delivery.carrier_code,
            description=delivery.description,
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
        )
