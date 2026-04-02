"""Parcel API client integration tests using respx for HTTP mocking.

Tests the full request/response lifecycle of ParcelAPIClient without
hitting the real api.parcel.app.  All HTTP interactions are intercepted
by respx.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from app.application.exceptions import (
    ParcelAuthError,
    ParcelRateLimitError,
    ParcelServerError,
)
from app.infrastructure.parcel_api.client import ParcelAPIClient

# ---------------------------------------------------------------------------
# Sample API response bodies
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "success": True,
    "deliveries": [
        {
            "tracking_number": "TRACK001",
            "carrier_code": "UPS",
            "description": "Test parcel",
            "status_code": 2,
            "extra_information": None,
            "date_expected": None,
            "date_expected_end": None,
            "timestamp_expected": None,
            "timestamp_expected_end": None,
            "events": [
                {
                    "event": "In transit",
                    "date": "2024-01-01T10:00:00Z",
                    "location": "London",
                    "additional": None,
                }
            ],
        }
    ],
}

_EMPTY_RESPONSE = {"success": True, "deliveries": []}

_API_BASE = "https://api.parcel.app"
_DELIVERIES_URL = f"{_API_BASE}/external/deliveries/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(api_key: str = "test-key") -> ParcelAPIClient:
    return ParcelAPIClient(
        client=httpx.AsyncClient(),
        api_key=api_key,
        timeout=5.0,
    )


# ---------------------------------------------------------------------------
# Successful response
# ---------------------------------------------------------------------------


@respx.mock
async def test_successful_response_parsed() -> None:
    """A 200 response with success=true is parsed into ParcelDeliveryDTO objects."""
    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(200, json=_VALID_RESPONSE)
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        deliveries = await client.get_deliveries()

    assert len(deliveries) == 1
    assert deliveries[0].tracking_number == "TRACK001"
    assert deliveries[0].carrier_code == "UPS"
    assert len(deliveries[0].events) == 1
    assert deliveries[0].events[0].event_description == "In transit"


# ---------------------------------------------------------------------------
# 429 — non-retryable rate limit (POLL-REQ-024)
# ---------------------------------------------------------------------------


@respx.mock
async def test_429_raises_rate_limit_error() -> None:
    """HTTP 429 raises ParcelRateLimitError immediately (no retry)."""
    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(429, json={"error": "Rate limited"})
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        with pytest.raises(ParcelRateLimitError):
            await client.get_deliveries()


# ---------------------------------------------------------------------------
# 401 — non-retryable auth error (POLL-REQ-025)
# ---------------------------------------------------------------------------


@respx.mock
async def test_401_raises_auth_error() -> None:
    """HTTP 401 raises ParcelAuthError immediately (no retry)."""
    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(401, json={"error": "Unauthorised"})
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        with pytest.raises(ParcelAuthError):
            await client.get_deliveries()


# ---------------------------------------------------------------------------
# 503 — retries 3 times then raises (POLL-REQ-026)
# ---------------------------------------------------------------------------


@respx.mock
async def test_503_retries_exhausted_then_raises(monkeypatch) -> None:
    """HTTP 503 retries (up to 3 times) then raises ParcelServerError.

    We skip the actual sleep delays by monkeypatching asyncio.sleep with an
    AsyncMock so that ``await asyncio.sleep(...)`` works without blocking.
    """
    import asyncio
    from unittest.mock import AsyncMock

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    # Mock the route to always return 503
    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(503, json={"error": "Service unavailable"})
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        with pytest.raises(ParcelServerError) as exc_info:
            await client.get_deliveries()

    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Empty delivery list — valid response (POLL-REQ-014)
# ---------------------------------------------------------------------------


@respx.mock
async def test_empty_deliveries_list_valid() -> None:
    """An empty deliveries array is a valid response (POLL-REQ-014)."""
    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        deliveries = await client.get_deliveries()

    assert deliveries == []


# ---------------------------------------------------------------------------
# API key not in logs (POLL-REQ-033)
# ---------------------------------------------------------------------------


@respx.mock
async def test_api_key_not_in_logs(caplog) -> None:
    """The API key must never appear in any log output (POLL-REQ-033)."""
    secret_key = "SUPER_SECRET_API_KEY_12345"

    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(200, json=_VALID_RESPONSE)
    )

    client = _make_client(api_key=secret_key)
    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient() as http:
            client._client = http
            await client.get_deliveries()

    # The secret key must not appear anywhere in captured log records
    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert secret_key not in all_log_text


# ---------------------------------------------------------------------------
# Timestamp epoch conversion (DM-BR-025)
# ---------------------------------------------------------------------------


@respx.mock
async def test_timestamp_epoch_converted_to_utc_datetime() -> None:
    """Unix epoch integers are converted to UTC-aware datetime objects."""
    import datetime as dt

    epoch = 1704067200  # 2024-01-01 00:00:00 UTC
    response_body = {
        "success": True,
        "deliveries": [
            {
                "tracking_number": "EPOCH001",
                "carrier_code": "UPS",
                "description": "Epoch test",
                "status_code": 2,
                "timestamp_expected": epoch,
                "timestamp_expected_end": None,
                "events": [],
            }
        ],
    }

    respx.get(_DELIVERIES_URL).mock(
        return_value=httpx.Response(200, json=response_body)
    )

    client = _make_client()
    async with httpx.AsyncClient() as http:
        client._client = http
        deliveries = await client.get_deliveries()

    assert len(deliveries) == 1
    ts = deliveries[0].timestamp_expected
    assert ts is not None
    assert ts.tzinfo is not None  # must be UTC-aware
    assert ts == dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
