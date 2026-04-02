"""Middleware and exception handler integration tests.

Verifies security headers, Server header suppression, OpenAPI docs gating,
and the standard error envelope format for 500 and 422 errors.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, ASGITransport

from tests.conftest import MockDeliveryRepository, MockUserRepository, make_delivery
from tests.integration.presentation.conftest import create_test_app, fake_user
from app.presentation.dependencies import get_current_user, get_deliveries_use_case
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase


# ---------------------------------------------------------------------------
# Security headers — all responses (API-REQ-021)
# ---------------------------------------------------------------------------


async def test_all_responses_have_security_headers(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """X-Content-Type-Options, X-Frame-Options, Referrer-Policy on every response."""
    repo = MockDeliveryRepository()
    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = (
        lambda: GetDeliveriesUseCase(repo)
    )

    # Check headers on several endpoints
    endpoints = [
        ("/api/deliveries/", 200),
        ("/api/health", 200),
        ("/api/auth/login", 422),  # POST without body → 422 still has headers
    ]

    for path, _ in endpoints:
        if path == "/api/auth/login":
            response = await client.post(path, json={})
        else:
            response = await client.get(path)

        headers = response.headers
        assert headers.get("x-content-type-options") == "nosniff", (
            f"Missing X-Content-Type-Options on {path}"
        )
        assert headers.get("x-frame-options") == "DENY", (
            f"Missing X-Frame-Options on {path}"
        )
        assert headers.get("referrer-policy") is not None, (
            f"Missing Referrer-Policy on {path}"
        )


async def test_no_server_header(client: AsyncClient, test_app: FastAPI) -> None:
    """The Server header must be absent from all responses (SEC-REQ-034)."""
    repo = MockDeliveryRepository()
    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = (
        lambda: GetDeliveriesUseCase(repo)
    )

    response = await client.get("/api/deliveries/")
    assert "server" not in {k.lower() for k in response.headers.keys()}


# ---------------------------------------------------------------------------
# OpenAPI docs gating (API-REQ-023)
# ---------------------------------------------------------------------------


async def test_openapi_available_in_development() -> None:
    """Development environment: /api/docs returns 200."""
    dev_app = create_test_app(environment="development")
    async with AsyncClient(
        transport=ASGITransport(app=dev_app), base_url="http://test"
    ) as c:
        response = await c.get("/api/docs")
    assert response.status_code == 200


async def test_no_openapi_in_production() -> None:
    """Production environment: /api/docs returns 404 (API-REQ-023)."""
    prod_app = create_test_app(environment="production")
    async with AsyncClient(
        transport=ASGITransport(app=prod_app), base_url="http://test"
    ) as c:
        response = await c.get("/api/docs")
    assert response.status_code == 404


async def test_openapi_json_hidden_in_production() -> None:
    """Production environment: /api/openapi.json returns 404."""
    prod_app = create_test_app(environment="production")
    async with AsyncClient(
        transport=ASGITransport(app=prod_app), base_url="http://test"
    ) as c:
        response = await c.get("/api/openapi.json")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 500 envelope — no stack trace leakage (API-REQ-025)
# ---------------------------------------------------------------------------


async def test_500_returns_standard_envelope_not_stacktrace(
    test_app: FastAPI,
) -> None:
    """An unhandled exception returns the standard error envelope, not a traceback.

    Note: ``raise_app_exceptions=False`` is required here because Starlette's
    ``ServerErrorMiddleware`` re-raises after sending the error response (so
    ASGI servers like Uvicorn can log it).  The response IS sent before the
    re-raise; ``raise_app_exceptions=False`` tells httpx to swallow the
    re-raise and return the already-received response.
    """
    from app.application.dtos.delivery_dtos import DeliveryFilterParams
    from app.presentation.dependencies import get_scheduler_state, get_carrier_cache
    from tests.unit.application.conftest import MockCarrierCache, MockSchedulerState

    class BoomUseCase:
        async def execute(self, params: DeliveryFilterParams):
            raise RuntimeError("Unexpected DB explosion")

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    test_app.dependency_overrides[get_deliveries_use_case] = lambda: BoomUseCase()
    test_app.dependency_overrides[get_carrier_cache] = lambda: MockCarrierCache()
    test_app.dependency_overrides[get_scheduler_state] = lambda: MockSchedulerState()

    # raise_app_exceptions=False: catch the re-raise from ServerErrorMiddleware
    # (which re-raises after sending the 500 response in newer Starlette versions)
    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        response = await c.get("/api/deliveries/")

    assert response.status_code == 500

    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # Must NOT leak implementation details
    response_text = response.text
    assert "RuntimeError" not in response_text
    assert "Traceback" not in response_text
    assert "explosion" not in response_text


# ---------------------------------------------------------------------------
# 422 validation error envelope (API-REQ-005)
# ---------------------------------------------------------------------------


async def test_validation_error_returns_standard_envelope(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Pydantic validation failure returns the standard error envelope (API-REQ-005)."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "", "password": ""},  # fails min_length=1 validators
    )
    assert response.status_code == 422

    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in body["error"]
