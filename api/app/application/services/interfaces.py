"""Abstract interfaces for external services consumed by application use cases.

These ABCs allow the application layer to depend on stable contracts without
importing httpx, apscheduler, or any infrastructure module.  Concrete
implementations live exclusively in the infrastructure layer and are wired
via FastAPI ``Depends()`` in the presentation layer.

No httpx, no apscheduler, no SQLAlchemy, no FastAPI imports.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.application.dtos.system_dtos import (
    CarrierDTO,
    CarrierListDTO,
    HealthDatabaseDTO,
    ParcelDeliveryDTO,
)


class AbstractParcelAPIClient(ABC):
    """Interface for calling the external Parcel App API.

    Concrete implementation: ``app.infrastructure.parcel_api.client.ParcelAPIClient``
    (wraps httpx, never imported by this layer).

    Retry logic and HTTP error translation belong to the concrete client.
    By the time any exception reaches the use case, retries are exhausted.
    """

    @abstractmethod
    async def get_deliveries(self) -> list[ParcelDeliveryDTO]:
        """Call ``GET /external/deliveries/?filter_mode=recent``.

        Returns a parsed delivery list on success.  An empty list is a valid
        response — it means no active deliveries (POLL-REQ-014).

        Raises:
            ParcelRateLimitError:  HTTP 429 received (POLL-REQ-024).
            ParcelAuthError:       HTTP 401 received (POLL-REQ-025).
            ParcelServerError:     HTTP 5xx or network error after all retries
                                   are exhausted (POLL-REQ-026).
            ParcelResponseError:   Successful HTTP status but ``success=false``
                                   in the response body.
        """
        ...

    @abstractmethod
    async def get_carriers(self) -> list[CarrierDTO]:
        """Call the carrier list endpoint on the Parcel API.

        Used by the carrier cache refresh task (API-REQ-019).

        Returns:
            List of :class:`~app.application.dtos.system_dtos.CarrierDTO`
            objects.  May be empty if the API returns no carriers.
        """
        ...


class AbstractCarrierCache(ABC):
    """Interface for the in-memory carrier code → name cache.

    The cache is populated asynchronously by the infrastructure scheduler.
    The ``get_carriers()`` method is **synchronous** because it reads from
    memory only — it never blocks on I/O.

    This design satisfies API-REQ-019: the ``GET /api/carriers`` endpoint
    never triggers a synchronous outbound HTTP call.
    """

    @abstractmethod
    def get_carriers(self) -> CarrierListDTO:
        """Return the current cached carrier list.

        The call MUST NOT trigger an outbound HTTP request (API-REQ-019).

        Behaviour by cache state:
        - ``fresh``:        TTL has not expired; data is authoritative.
        - ``stale``:        TTL expired; last-known data returned without error
                            (API-REQ-020).
        - ``unavailable``:  Never successfully populated; returns an empty
                            list without raising (API-REQ-020).

        Returns:
            :class:`~app.application.dtos.system_dtos.CarrierListDTO` with
            the appropriate ``cache_status``.
        """
        ...

    @abstractmethod
    async def refresh(self) -> None:
        """Fetch the current carrier list from the Parcel API and update the cache.

        Called by the infrastructure scheduler on a periodic basis.  Failures
        are logged by the concrete implementation and do not propagate — a
        stale cache is preferable to an error cascade.
        """
        ...


class AbstractSchedulerState(ABC):
    """Interface to query the APScheduler instance for health reporting.

    The application layer uses this to populate
    :class:`~app.application.dtos.system_dtos.HealthPollingDTO` without
    importing apscheduler (API-REQ-018).

    Both methods are **synchronous** — they read in-memory scheduler state.
    """

    @abstractmethod
    def is_running(self) -> bool:
        """Return ``True`` if the scheduler is running and has active jobs."""
        ...

    @abstractmethod
    def get_next_poll_at(self) -> Optional[datetime]:
        """Return the UTC datetime of the next scheduled poll.

        Returns ``None`` if the scheduler is not running or no job is
        scheduled (API-REQ-018).
        """
        ...


class AbstractDBHealthChecker(ABC):
    """Interface for performing a live database connectivity check.

    Used exclusively by ``GetHealthUseCase`` to produce the
    :class:`~app.application.dtos.system_dtos.HealthDatabaseDTO` with a
    round-trip latency measurement.

    A 3-second timeout is applied by the use case caller via
    ``asyncio.wait_for`` (API-REQ-016).
    """

    @abstractmethod
    async def check(self) -> HealthDatabaseDTO:
        """Perform a lightweight database ping and return the result.

        Must complete within 3 seconds (the caller enforces the timeout).
        Implementations should run a ``SELECT 1`` or equivalent and measure
        the round-trip latency.

        Returns:
            :class:`~app.application.dtos.system_dtos.HealthDatabaseDTO`
            with ``status='connected'`` and a latency measurement, or
            ``status='disconnected'`` if unreachable.

        Note:
            Implementations should NOT raise — they return a ``disconnected``
            DTO instead so the use case can continue building the health
            aggregate.
        """
        ...
