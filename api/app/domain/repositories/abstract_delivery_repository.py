"""AbstractDeliveryRepository — persistence contract for the delivery aggregate."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from app.domain.entities.delivery import Delivery
from app.domain.entities.delivery_event import DeliveryEvent
from app.domain.entities.status_history import StatusHistory

if TYPE_CHECKING:
    # DeliveryFilterParams lives in the Application layer (Phase 3).
    # Importing under TYPE_CHECKING means this symbol is available to static
    # analysis tools (mypy, pyright) without creating a runtime circular
    # dependency between the Domain and Application layers.
    # With `from __future__ import annotations`, all annotations are treated
    # as strings at runtime so no import is needed then.
    from app.application.dtos.delivery_dtos import DeliveryFilterParams


class AbstractDeliveryRepository(ABC):
    """Persistence contract for the delivery aggregate.

    All methods are ``async``.  Concrete implementations live exclusively in
    the Infrastructure layer and must never be imported by Domain or
    Application code directly — the presentation layer wires them via DI.

    The Domain layer **owns** this interface; the Infrastructure layer
    **satisfies** it.
    """

    @abstractmethod
    async def get_snapshot(self) -> dict[tuple[str, str], UUID]:
        """Return a lightweight snapshot of all persisted deliveries.

        Returns a ``dict`` keyed by ``(tracking_number, carrier_code)``
        mapping to the delivery's internal ``UUID``.

        This **single query** enables O(1) existence checks during the
        change-detection phase of polling, avoiding per-delivery ``SELECT``
        queries (POLL-REQ-015 — no N+1).
        """
        ...

    @abstractmethod
    async def get_by_id(self, delivery_id: UUID) -> Optional[Delivery]:
        """Fetch a single delivery by its internal UUID.

        Returns ``None`` if no delivery with that UUID exists.
        """
        ...

    @abstractmethod
    async def list_filtered(
        self,
        filter_params: DeliveryFilterParams,
    ) -> tuple[list[Delivery], int]:
        """Fetch a filtered, paginated list of deliveries.

        Returns a ``(items, total_count)`` tuple where ``total_count`` is
        the count of records matching the filter **before** pagination.

        Implementations must:
        - Apply ``NULLS LAST`` ordering when sorting by
          ``timestamp_expected`` (API-REQ-012).
        - Use parameterised ``ILIKE`` for the ``search`` term — never string
          interpolation (SEC-REQ-058).
        - Exclude ``TERMINAL`` lifecycle-group deliveries by default when
          ``filter_params.include_terminal`` is ``False``.
        - Return an empty ``items`` list (not an error) when
          ``filter_params.page`` exceeds the total page count (API-REQ-028).
        """
        ...

    @abstractmethod
    async def create(self, delivery: Delivery) -> Delivery:
        """Persist a new delivery record and return the saved entity."""
        ...

    @abstractmethod
    async def update(self, delivery: Delivery) -> Delivery:
        """Persist changes to an existing delivery and return the updated entity.

        Implementations **must** always update ``last_seen_at`` and
        ``updated_at`` to reflect the current polling time (POLL-REQ-018).
        """
        ...

    @abstractmethod
    async def create_event(self, event: DeliveryEvent) -> Optional[DeliveryEvent]:
        """Persist a new delivery event, silently ignoring duplicates.

        Uses ``INSERT … ON CONFLICT DO NOTHING`` on the
        ``(delivery_id, event_description, event_date_raw)`` deduplication
        fingerprint (DM-BR-007).

        Returns:
            The persisted :class:`~app.domain.entities.delivery_event.DeliveryEvent`,
            or ``None`` if the fingerprint already existed.
        """
        ...

    @abstractmethod
    async def get_events_for_delivery(self, delivery_id: UUID) -> list[DeliveryEvent]:
        """Fetch all events for a delivery, ordered by ``sequence_number ASC``.

        An empty list is a valid return value — deliveries may exist before
        any events are synced (API-REQ-014).
        """
        ...

    @abstractmethod
    async def create_status_history(self, entry: StatusHistory) -> StatusHistory:
        """Append an immutable status history record and return it.

        Status history is **append-only** — entries are never updated or
        deleted (DM-BR-012).
        """
        ...

    @abstractmethod
    async def get_status_history_for_delivery(
        self, delivery_id: UUID
    ) -> list[StatusHistory]:
        """Fetch all status history entries for a delivery.

        Ordered by ``detected_at ASC`` (oldest-first) (API-REQ-014).
        """
        ...
