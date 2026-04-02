"""Application layer unit test conftest.

Imports mock repos from the root conftest and provides use-case factory
helpers. No database connection is needed; all repos are in-memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest

from tests.conftest import MockDeliveryRepository, MockPollLogRepository, MockUserRepository, make_delivery, make_user
from app.application.dtos.system_dtos import (
    CarrierDTO,
    CarrierListDTO,
    HealthDatabaseDTO,
)
from app.application.services.interfaces import (
    AbstractCarrierCache,
    AbstractDBHealthChecker,
    AbstractParcelAPIClient,
    AbstractSchedulerState,
)
from app.application.dtos.system_dtos import ParcelDeliveryDTO


# ---------------------------------------------------------------------------
# Password constants for auth tests.
# NOTE: We do NOT pre-compute bcrypt hashes at import time to avoid passlib/bcrypt
# backend compatibility issues (bcrypt >=4.0 raises on >72-byte test vectors
# used by passlib's detect_wrap_bug).  Individual tests mock passlib.hash.bcrypt
# or compute hashes inline where real verification is needed.
# ---------------------------------------------------------------------------

CORRECT_PASSWORD = "correct_password"
WRONG_PASSWORD = "wrong_password"
# Sentinel value — used when a test requires a "real" hash in the user entity
# but the verify call will be mocked.  Any non-empty string works here.
CORRECT_PASSWORD_HASH: str = "__uses_mock_verify__"


# ---------------------------------------------------------------------------
# Mock external service implementations
# ---------------------------------------------------------------------------


class MockParcelAPIClient(AbstractParcelAPIClient):
    """Configurable mock for the Parcel API client."""

    def __init__(
        self,
        deliveries: Optional[list[ParcelDeliveryDTO]] = None,
        raise_on_call: Optional[Exception] = None,
    ) -> None:
        self._deliveries = deliveries or []
        self._raise = raise_on_call
        self.call_count = 0

    async def get_deliveries(self) -> list[ParcelDeliveryDTO]:
        self.call_count += 1
        if self._raise is not None:
            raise self._raise
        return self._deliveries

    async def get_carriers(self) -> list[CarrierDTO]:
        return []


class MockCarrierCache(AbstractCarrierCache):
    """Mock carrier cache — returns unavailable by default."""

    def __init__(self, *, cache_status: str = "unavailable") -> None:
        self._status = cache_status
        self.refresh_called = 0

    def get_carriers(self) -> CarrierListDTO:
        return CarrierListDTO(
            carriers=[],
            cached_at=None,
            cache_status=self._status,  # type: ignore[arg-type]
        )

    async def refresh(self) -> None:
        self.refresh_called += 1


class MockSchedulerState(AbstractSchedulerState):
    """Mock scheduler state — running by default."""

    def __init__(
        self,
        *,
        running: bool = True,
        next_poll_at: Optional[datetime] = None,
    ) -> None:
        self._running = running
        self._next_poll_at = next_poll_at

    def is_running(self) -> bool:
        return self._running

    def get_next_poll_at(self) -> Optional[datetime]:
        return self._next_poll_at


class MockDBHealthChecker(AbstractDBHealthChecker):
    """Mock DB health checker."""

    def __init__(
        self,
        *,
        status: str = "connected",
        latency_ms: Optional[float] = 1.5,
        raise_on_check: Optional[Exception] = None,
    ) -> None:
        self._status = status
        self._latency_ms = latency_ms
        self._raise = raise_on_check

    async def check(self) -> HealthDatabaseDTO:
        if self._raise is not None:
            raise self._raise
        return HealthDatabaseDTO(
            status=self._status,  # type: ignore[arg-type]
            latency_ms=self._latency_ms,
        )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_parcel_client() -> MockParcelAPIClient:
    return MockParcelAPIClient()


@pytest.fixture
def mock_carrier_cache() -> MockCarrierCache:
    return MockCarrierCache()


@pytest.fixture
def mock_scheduler_state() -> MockSchedulerState:
    return MockSchedulerState()


@pytest.fixture
def mock_db_health_checker() -> MockDBHealthChecker:
    return MockDBHealthChecker()
