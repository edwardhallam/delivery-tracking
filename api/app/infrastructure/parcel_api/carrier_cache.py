"""CarrierCache — in-memory carrier code → name cache.

Implements :class:`~app.application.services.interfaces.AbstractCarrierCache`.
The cache is populated by a periodic background refresh (every 24 hours) and
serves requests synchronously from memory — no outbound HTTP on read paths
(API-REQ-019).

On failure, the last known cache is retained and served as ``stale``
(API-REQ-020).  If no successful refresh has ever occurred, an empty list is
returned with ``cache_status='unavailable'``.

ARCH-INFRASTRUCTURE §7
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.application.dtos.system_dtos import CarrierDTO, CarrierListDTO
from app.application.services.interfaces import AbstractCarrierCache, AbstractParcelAPIClient

logger = logging.getLogger(__name__)

# TTL for "fresh" carrier data (24 hours in seconds)
_CARRIER_CACHE_TTL_SECONDS: int = 24 * 60 * 60


class CarrierCache(AbstractCarrierCache):
    """In-memory carrier list cache with a 24-hour TTL.

    Args:
        parcel_client:  Used by :meth:`refresh` to fetch the carrier list.
                        The same ``AbstractParcelAPIClient`` instance used
                        by the polling use case.
    """

    def __init__(self, parcel_client: AbstractParcelAPIClient) -> None:
        self._parcel_client = parcel_client
        self._carriers: list[CarrierDTO] = []
        self._cached_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # AbstractCarrierCache interface
    # ------------------------------------------------------------------

    def get_carriers(self) -> CarrierListDTO:
        """Return the cached carrier list synchronously (no I/O).

        Cache states:
        - ``'fresh'``       — TTL has not expired.
        - ``'stale'``       — TTL expired; last-known data returned without error.
        - ``'unavailable'`` — Never successfully fetched.

        This method MUST NOT trigger an outbound HTTP call (API-REQ-019).
        """
        if self._cached_at is None:
            return CarrierListDTO(
                carriers=[],
                cached_at=None,
                cache_status="unavailable",
            )

        age_seconds = (
            datetime.now(tz=timezone.utc) - self._cached_at
        ).total_seconds()
        cache_status = "fresh" if age_seconds < _CARRIER_CACHE_TTL_SECONDS else "stale"

        return CarrierListDTO(
            carriers=list(self._carriers),
            cached_at=self._cached_at,
            cache_status=cache_status,
        )

    async def refresh(self) -> None:
        """Fetch current carrier list from Parcel API and update the cache.

        On failure, the existing cache is retained — a stale carrier list is
        preferable to an error cascade (API-REQ-020).  All errors are logged
        at WARNING level and suppressed.
        """
        try:
            carriers = await self._parcel_client.get_carriers()
            self._carriers = carriers
            self._cached_at = datetime.now(tz=timezone.utc)
            logger.info(
                "Carrier cache refreshed: %d carriers loaded", len(carriers)
            )
        except Exception as exc:
            logger.warning(
                "Carrier cache refresh failed; retaining existing cache. error=%s",
                exc,
            )
            # Existing self._carriers and self._cached_at are preserved
