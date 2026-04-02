"""Unit tests for system use cases (health and carriers).

Uses mock services — no database, no HTTP required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import pytest

from tests.conftest import MockPollLogRepository
from tests.unit.application.conftest import (
    MockCarrierCache,
    MockDBHealthChecker,
    MockSchedulerState,
)
from app.application.dtos.system_dtos import CarrierDTO, CarrierListDTO, HealthDatabaseDTO
from app.application.services.interfaces import AbstractCarrierCache
from app.application.use_cases.system.get_carriers import GetCarriersUseCase
from app.application.use_cases.system.get_health import GetHealthUseCase
from app.domain.entities.poll_log import PollOutcome


# ---------------------------------------------------------------------------
# GetHealthUseCase
# ---------------------------------------------------------------------------


async def test_health_healthy_when_all_ok(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status='healthy' when DB connected and scheduler running."""
    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="connected"),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.status == "healthy"
    assert result.database.status == "connected"
    assert result.polling.scheduler_running is True


async def test_health_unhealthy_when_db_disconnected(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status='unhealthy' when DB is disconnected (POLL-REQ-036)."""
    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="disconnected", latency_ms=None),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.status == "unhealthy"


async def test_health_unhealthy_when_scheduler_not_running(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status='unhealthy' when scheduler is not running."""
    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="connected"),
        scheduler_state=MockSchedulerState(running=False),
    )
    result = await uc.execute()
    assert result.status == "unhealthy"


async def test_health_degraded_at_3_consecutive_errors(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status='degraded' after 3 consecutive poll errors (POLL-REQ-036)."""
    mock_poll_log_repo.consecutive_errors_override = 3

    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="connected"),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.status == "degraded"
    assert result.polling.consecutive_errors == 3


async def test_health_healthy_at_2_consecutive_errors(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Status remains 'healthy' at 2 consecutive errors (threshold is 3)."""
    mock_poll_log_repo.consecutive_errors_override = 2

    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="connected"),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.status == "healthy"


async def test_health_never_raises(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """GetHealthUseCase never raises even when all sub-checks fail."""
    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(raise_on_check=RuntimeError("DB down")),
        scheduler_state=MockSchedulerState(running=False),
    )
    result = await uc.execute()  # must not raise
    assert result is not None
    assert result.status == "unhealthy"


async def test_health_db_timeout_returns_disconnected(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """A DB check that hangs beyond 3 s returns disconnected status (API-REQ-016)."""

    class SlowChecker(MockDBHealthChecker):
        async def check(self) -> HealthDatabaseDTO:
            await asyncio.sleep(10)  # will be cancelled by wait_for
            return HealthDatabaseDTO(status="connected", latency_ms=0.1)

    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=SlowChecker(),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.database.status == "disconnected"


async def test_health_includes_poll_log_state(
    mock_poll_log_repo: MockPollLogRepository,
) -> None:
    """Health DTO includes last poll outcome from poll log repo."""
    # Add a completed SUCCESS log
    log = await mock_poll_log_repo.create_in_progress(
        started_at=datetime.now(tz=timezone.utc)
    )
    await mock_poll_log_repo.complete(
        poll_id=log.id,
        outcome=PollOutcome.SUCCESS,
        completed_at=datetime.now(tz=timezone.utc),
        deliveries_fetched=5,
        new_deliveries=1,
        status_changes=2,
        new_events=3,
        error_message=None,
    )

    uc = GetHealthUseCase(
        poll_log_repo=mock_poll_log_repo,
        db_health_checker=MockDBHealthChecker(status="connected"),
        scheduler_state=MockSchedulerState(running=True),
    )
    result = await uc.execute()
    assert result.polling.last_poll_outcome == PollOutcome.SUCCESS.value


# ---------------------------------------------------------------------------
# GetCarriersUseCase
# ---------------------------------------------------------------------------


async def test_carriers_returns_cache_contents() -> None:
    """GetCarriersUseCase returns whatever the carrier cache provides."""

    class FreshCache(MockCarrierCache):
        def get_carriers(self) -> CarrierListDTO:
            return CarrierListDTO(
                carriers=[CarrierDTO(code="UPS", name="United Parcel Service")],
                cached_at=datetime.now(tz=timezone.utc),
                cache_status="fresh",
            )

    uc = GetCarriersUseCase(FreshCache())
    result = await uc.execute()

    assert len(result.carriers) == 1
    assert result.carriers[0].code == "UPS"
    assert result.cache_status == "fresh"


async def test_carriers_never_calls_http_synchronously() -> None:
    """GetCarriersUseCase.execute() is purely synchronous under the hood (API-REQ-019).

    The carrier cache's get_carriers() must not be async (it reads memory only).
    We verify this by ensuring the method is NOT a coroutine.
    """
    cache = MockCarrierCache()
    import inspect
    assert not inspect.iscoroutinefunction(cache.get_carriers)


async def test_carriers_unavailable_returns_empty_not_error() -> None:
    """If cache was never populated, an empty list is returned without raising (API-REQ-020)."""
    uc = GetCarriersUseCase(MockCarrierCache(cache_status="unavailable"))
    result = await uc.execute()

    assert result.carriers == []
    assert result.cache_status == "unavailable"
    assert result.cached_at is None
