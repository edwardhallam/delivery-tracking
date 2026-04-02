"""Unit tests for delivery use cases.

Uses in-memory mock repositories — no database required.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from tests.conftest import MockDeliveryRepository, make_delivery
from app.application.dtos.delivery_dtos import DeliveryFilterParams
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase
from app.application.use_cases.deliveries.get_delivery_detail import (
    GetDeliveryDetailUseCase,
)
from app.domain.exceptions import DeliveryNotFoundError
from app.domain.value_objects.lifecycle_group import LifecycleGroup
from app.domain.value_objects.semantic_status import SemanticStatus


# ---------------------------------------------------------------------------
# GetDeliveriesUseCase
# ---------------------------------------------------------------------------


async def test_list_deliveries_empty_repo(mock_delivery_repo: MockDeliveryRepository) -> None:
    """Empty repository returns empty list with correct pagination metadata."""
    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams())

    assert result.items == []
    assert result.total == 0
    assert result.pages == 0
    assert result.page == 1


async def test_list_deliveries_returns_items(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """Deliveries in the repo are returned as summary DTOs."""
    d = make_delivery()
    await mock_delivery_repo.create(d)

    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams())

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].tracking_number == d.tracking_number


async def test_list_deliveries_derives_lifecycle_group(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """lifecycle_group is derived at serialisation time — not stored (NORM-REQ-004)."""
    d = make_delivery(
        semantic_status=SemanticStatus.IN_TRANSIT,
        parcel_status_code=2,
    )
    await mock_delivery_repo.create(d)

    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams())

    item = result.items[0]
    assert item.lifecycle_group == LifecycleGroup.ACTIVE.value
    assert item.semantic_status == SemanticStatus.IN_TRANSIT.value


async def test_list_deliveries_terminal_lifecycle_group(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """Delivered parcels receive LifecycleGroup.TERMINAL in the DTO."""
    d = make_delivery(
        semantic_status=SemanticStatus.DELIVERED,
        parcel_status_code=0,
    )
    await mock_delivery_repo.create(d)

    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams())

    assert result.items[0].lifecycle_group == LifecycleGroup.TERMINAL.value


async def test_list_deliveries_page_beyond_total_returns_empty(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """A page number beyond the last page returns empty items, not an error (API-REQ-028)."""
    d = make_delivery()
    await mock_delivery_repo.create(d)

    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams(page=999, page_size=20))

    assert result.items == []
    assert result.total == 1  # total count still reflects reality
    assert result.page == 999


async def test_list_deliveries_pagination_math(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """pages is calculated correctly from total and page_size."""
    for _ in range(25):
        await mock_delivery_repo.create(make_delivery(tracking_number=str(uuid4())[:8]))

    use_case = GetDeliveriesUseCase(mock_delivery_repo)
    result = await use_case.execute(DeliveryFilterParams(page=1, page_size=10))

    assert result.total == 25
    assert result.pages == 3  # ceil(25/10) == 3


# ---------------------------------------------------------------------------
# GetDeliveryDetailUseCase
# ---------------------------------------------------------------------------


async def test_get_delivery_detail_returns_dto(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """A known delivery ID returns the detail DTO."""
    d = make_delivery()
    await mock_delivery_repo.create(d)

    use_case = GetDeliveryDetailUseCase(mock_delivery_repo)
    result = await use_case.execute(d.id)

    assert result.id == d.id
    assert result.tracking_number == d.tracking_number
    assert result.events == []
    assert result.status_history == []


async def test_get_delivery_detail_missing_raises_not_found(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """Unknown delivery ID raises DeliveryNotFoundError."""
    use_case = GetDeliveryDetailUseCase(mock_delivery_repo)
    with pytest.raises(DeliveryNotFoundError):
        await use_case.execute(uuid4())


async def test_get_delivery_detail_derives_lifecycle_group(
    mock_delivery_repo: MockDeliveryRepository,
) -> None:
    """Detail DTO includes lifecycle_group derived from semantic_status (NORM-REQ-004)."""
    d = make_delivery(
        semantic_status=SemanticStatus.EXCEPTION,
        parcel_status_code=7,
    )
    await mock_delivery_repo.create(d)

    use_case = GetDeliveryDetailUseCase(mock_delivery_repo)
    result = await use_case.execute(d.id)

    assert result.lifecycle_group == LifecycleGroup.ATTENTION.value
