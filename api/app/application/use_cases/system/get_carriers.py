"""GetCarriersUseCase — return the cached carrier list."""
from __future__ import annotations

import logging

from app.application.dtos.system_dtos import CarrierListDTO
from app.application.services.interfaces import AbstractCarrierCache

logger = logging.getLogger(__name__)


class GetCarriersUseCase:
    """Return the current carrier code → name mapping from the in-memory cache.

    This use case **never makes a synchronous outbound HTTP call** (API-REQ-019).
    The carrier cache is populated asynchronously by the infrastructure
    scheduler.  If the cache has never been populated, an empty list with
    ``cache_status='unavailable'`` is returned without raising (API-REQ-020).

    Architecture: ARCH-APPLICATION §4.8
    Requirements: API-REQ-019–020
    """

    def __init__(self, carrier_cache: AbstractCarrierCache) -> None:
        self._carrier_cache = carrier_cache

    async def execute(self) -> CarrierListDTO:
        """Return the current carrier list from the cache.

        Returns:
            :class:`~app.application.dtos.system_dtos.CarrierListDTO` — always
            returned, never raises.  ``cache_status`` indicates freshness.
        """
        return self._carrier_cache.get_carriers()
