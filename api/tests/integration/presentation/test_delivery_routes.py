"""Presentation integration tests for delivery routes.

GET /api/deliveries/         — paginated list
GET /api/deliveries/{id}     — delivery detail
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import MockDeliveryRepository, make_delivery
from tests.integration.presentation.conftest import fake_user
from app.application.dtos.delivery_dtos import (
    DeliveryDetailDTO,
    DeliveryFilterParams,
    DeliveryListDTO,
    DeliverySummaryDTO,
)
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase
from app.application.use_cases.deliveries.get_delivery_detail import (
    GetDeliveryDetailUseCase,
)
from app.domain.exceptions import DeliveryNotFoundError
from app.domain.value_objects.semantic_status import SemanticStatus
from app.presentation.dependencies import (
    get_current_user,
    get_deliveries_use_case,
    get_delivery_detail_use_case,
)


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------


async def test_list_deliveries_requires_auth(client: AsyncClient) -> None:
    """GET /api/deliveries/ returns 401 without an access token."""
    response = await client.get("/api/deliveries/")
    assert response.status_code == 401


async def test_get_delivery_requires_auth(client: AsyncClient) -> None:
    """GET /api/deliveries/{id} returns 401 without an access token."""
    response = await client.get(f"/api/deliveries/{uuid4()}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/deliveries/ — list
# ---------------------------------------------------------------------------


async def test_list_deliveries_returns_paginated_response(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Authenticated list request returns the PaginatedDeliveryResponse shape."""
    repo = MockDeliveryRepository()
    d = make_delivery()
    await repo.create(d)

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = (
        lambda: GetDeliveriesUseCase(repo)
    )

    response = await client.get("/api/deliveries/")
    assert response.status_code == 200

    body = response.json()
    assert "data" in body
    assert "items" in body["data"]
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["tracking_number"] == d.tracking_number


async def test_list_deliveries_page_beyond_total_returns_empty_not_404(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Page beyond total returns empty items list — not a 404 (API-REQ-028)."""
    repo = MockDeliveryRepository()
    await repo.create(make_delivery())

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = (
        lambda: GetDeliveriesUseCase(repo)
    )

    response = await client.get("/api/deliveries/?page=999")
    assert response.status_code == 200

    body = response.json()
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 1  # total still reflects real count


async def test_list_deliveries_lifecycle_group_present(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Each item in the list includes lifecycle_group (derived, not stored)."""
    repo = MockDeliveryRepository()
    await repo.create(
        make_delivery(
            semantic_status=SemanticStatus.DELIVERED,
            parcel_status_code=0,
        )
    )

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = (
        lambda: GetDeliveriesUseCase(repo)
    )

    response = await client.get("/api/deliveries/?include_terminal=true")
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["lifecycle_group"] == "TERMINAL"


# ---------------------------------------------------------------------------
# GET /api/deliveries/{id} — detail
# ---------------------------------------------------------------------------


async def test_get_delivery_not_found_returns_404(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Unknown delivery UUID returns 404."""
    repo = MockDeliveryRepository()

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_delivery_detail_use_case] = (
        lambda: GetDeliveryDetailUseCase(repo)
    )

    response = await client.get(f"/api/deliveries/{uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "NOT_FOUND"


async def test_get_delivery_invalid_uuid_returns_422(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """A malformed UUID path parameter returns 422 (FastAPI validation)."""
    test_app.dependency_overrides[get_current_user] = lambda: fake_user()

    response = await client.get("/api/deliveries/not-a-valid-uuid")
    assert response.status_code == 422


async def test_get_delivery_returns_detail(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Known delivery UUID returns full detail including events/history arrays."""
    repo = MockDeliveryRepository()
    d = make_delivery()
    await repo.create(d)

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_delivery_detail_use_case] = (
        lambda: GetDeliveryDetailUseCase(repo)
    )

    response = await client.get(f"/api/deliveries/{d.id}")
    assert response.status_code == 200

    body = response.json()
    assert body["data"]["id"] == str(d.id)
    assert body["data"]["tracking_number"] == d.tracking_number
    assert "events" in body["data"]
    assert "status_history" in body["data"]
