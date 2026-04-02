"""Presentation integration test conftest.

Creates a minimal test FastAPI app with a stub lifespan (no DB, no scheduler,
no HTTP client connections) and provides an AsyncClient fixture.

All infrastructure dependencies are overridden via app.dependency_overrides
so tests never need a real database or Parcel API connection.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from tests.conftest import MockDeliveryRepository, MockUserRepository, make_delivery, make_user
from tests.unit.application.conftest import MockCarrierCache, MockSchedulerState
from app.application.dtos.system_dtos import CarrierListDTO
from app.application.services.interfaces import (
    AbstractCarrierCache,
    AbstractSchedulerState,
)
from app.domain.entities.user import User
from app.presentation.middleware.security_headers import SecurityHeadersMiddleware
from app.presentation.routers.auth_router import router as auth_router
from app.presentation.routers.deliveries_router import router as deliveries_router
from app.presentation.routers.system_router import router as system_router

# ---------------------------------------------------------------------------
# Test-mode app state objects
# ---------------------------------------------------------------------------

_mock_carrier_cache = MockCarrierCache()
_mock_scheduler_state = MockSchedulerState(running=True)


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    """Stub lifespan — sets mock app.state without any real I/O."""
    app.state.carrier_cache = _mock_carrier_cache
    app.state.polling_scheduler = _mock_scheduler_state
    yield


# ---------------------------------------------------------------------------
# Exception handlers (mirrors production main.py)
# ---------------------------------------------------------------------------


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(loc) for loc in err.get("loc", [])),
            "message": err["msg"],
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging
    logging.getLogger(__name__).exception("Unhandled: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred. Please try again later."}},
    )


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------


def create_test_app(*, environment: str = "development") -> FastAPI:
    """Create a minimal FastAPI app for presentation tests.

    Args:
        environment: 'development' enables /api/docs; 'production' hides it.
    """
    docs_url = "/api/docs" if environment == "development" else None
    redoc_url = "/api/redoc" if environment == "development" else None
    openapi_url = "/api/openapi.json" if environment == "development" else None

    application = FastAPI(
        title="Test App",
        version="test",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=_test_lifespan,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, _generic_handler)  # type: ignore[arg-type]
    application.include_router(auth_router, prefix="/api/auth")
    application.include_router(deliveries_router, prefix="/api/deliveries")
    application.include_router(system_router, prefix="/api")
    return application


# ---------------------------------------------------------------------------
# Reusable fake user
# ---------------------------------------------------------------------------


def fake_user(token_version: int = 1) -> User:
    return make_user(username="testuser", token_version=token_version)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app() -> FastAPI:
    """Fresh test FastAPI app per test."""
    return create_test_app()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    """AsyncClient connected to the test app.

    ``ASGITransport`` does NOT run the lifespan, so ``app.state``-reading
    dependencies (``get_carrier_cache``, ``get_scheduler_state``) are
    overridden here with in-memory mocks.  Tests that need the health or
    carriers endpoint receive consistent stub data automatically.
    Use ``test_app.dependency_overrides`` inside tests to further customise.
    """
    from app.presentation.dependencies import get_carrier_cache, get_scheduler_state

    test_app.dependency_overrides[get_carrier_cache] = lambda: _mock_carrier_cache
    test_app.dependency_overrides[get_scheduler_state] = lambda: _mock_scheduler_state

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c
    test_app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(test_app: FastAPI) -> dict[str, str]:
    """Injects a valid Bearer access token header.

    Overrides ``get_current_user`` so all endpoints skip the real JWT
    validation chain.
    """
    from app.presentation.dependencies import get_current_user

    test_app.dependency_overrides[get_current_user] = lambda: fake_user()
    return {}  # header not needed — dependency already overridden


@pytest.fixture
def mock_delivery_repo_fixture() -> MockDeliveryRepository:
    return MockDeliveryRepository()


@pytest.fixture
def mock_user_repo_fixture() -> MockUserRepository:
    return MockUserRepository()
