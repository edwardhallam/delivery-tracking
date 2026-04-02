"""ParcelAPIClient — concrete implementation of AbstractParcelAPIClient.

Wraps ``httpx.AsyncClient`` to call the Parcel App API.  Implements the full
retry strategy with exponential back-off (POLL-REQ-026) and translates HTTP
responses to typed ``ParcelDeliveryDTO`` objects for the application layer.

Security: the API key is **never** logged, printed, or exposed in exceptions
(POLL-REQ-009, POLL-REQ-033).

ARCH-INFRASTRUCTURE §6
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import ValidationError

from app.application.dtos.system_dtos import CarrierDTO, ParcelDeliveryDTO, ParcelEventDTO
from app.application.exceptions import (
    ParcelAuthError,
    ParcelRateLimitError,
    ParcelResponseError,
    ParcelServerError,
)
from app.application.services.interfaces import AbstractParcelAPIClient
from app.infrastructure.parcel_api.schemas import (
    ParcelAPIDelivery,
    ParcelAPIResponse,
)

logger = logging.getLogger(__name__)

# Retry delays in seconds for retryable errors (POLL-REQ-026)
_RETRY_DELAYS: tuple[int, ...] = (15, 60, 120)

_PARCEL_BASE_URL = "https://api.parcel.app"
_DELIVERIES_PATH = "/external/deliveries/"
_CARRIERS_PATH = "/external/supported_carriers.json"


class ParcelAPIClient(AbstractParcelAPIClient):
    """Async HTTP client for the Parcel App API.

    The ``httpx.AsyncClient`` is **shared** across poll cycles (not created
    per poll) to enable HTTP/1.1 keep-alive connection reuse (POLL-REQ-012).

    The API key is stored in a private attribute and passed only as a request
    header — it never appears in log messages at any level (POLL-REQ-033).

    Args:
        client:   Shared ``httpx.AsyncClient`` instance (managed by caller).
        api_key:  Parcel API key from ``PARCEL_API_KEY`` env var.
        timeout:  Combined connect + read timeout in seconds (POLL-REQ-011).
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    # ------------------------------------------------------------------
    # AbstractParcelAPIClient interface
    # ------------------------------------------------------------------

    async def get_deliveries(self) -> list[ParcelDeliveryDTO]:
        """Call ``GET /external/deliveries/?filter_mode=recent`` with retries.

        Retry schedule for 5xx / network errors (POLL-REQ-026):
        - Attempt 0 (initial): immediate
        - Attempt 1 (1st retry): wait 15 s
        - Attempt 2 (2nd retry): wait 60 s
        - Attempt 3 (3rd retry): wait 120 s
        - After 3rd failure: raise :class:`ParcelServerError`

        Non-retryable errors (429, 401, 4xx non-auth, ``success=false``)
        propagate immediately without sleeping.

        Raises:
            ParcelRateLimitError:  HTTP 429.
            ParcelAuthError:       HTTP 401.
            ParcelServerError:     HTTP 5xx or network error after all retries.
            ParcelResponseError:   ``success=false`` in response body.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                logger.debug(
                    "Parcel API call attempt=%d url=%s%s filter_mode=recent",
                    attempt,
                    _PARCEL_BASE_URL,
                    _DELIVERIES_PATH,
                )
                response = await self._client.get(
                    f"{_PARCEL_BASE_URL}{_DELIVERIES_PATH}",
                    params={"filter_mode": "recent"},
                    headers={"api-key": self._api_key},
                    timeout=self._timeout,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Parcel API network error attempt=%d error_type=%s "
                        "retry_delay_seconds=%d",
                        attempt + 1,
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ParcelServerError(
                    status_code=None,
                    message=f"Network error after {len(_RETRY_DELAYS)} retries: {exc}",
                ) from exc

            # ── HTTP status handling ──────────────────────────────────────
            logger.debug(
                "Parcel API response attempt=%d status_code=%d",
                attempt,
                response.status_code,
            )

            if response.status_code == 429:
                raise ParcelRateLimitError(
                    "Parcel API rate limited (HTTP 429)"
                )  # non-retryable

            if response.status_code == 401:
                raise ParcelAuthError(
                    "Parcel API authentication failed (HTTP 401)"
                )  # non-retryable

            if 400 <= response.status_code < 500:
                # Other client errors are non-retryable (POLL-REQ-013)
                raise ParcelServerError(
                    status_code=response.status_code,
                    message=f"Parcel API client error (HTTP {response.status_code})",
                )

            if response.status_code >= 500:
                # Server error — retryable (POLL-REQ-026)
                last_exc = ParcelServerError(
                    status_code=response.status_code,
                    message=f"Parcel API server error (HTTP {response.status_code})",
                )
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Parcel API server error attempt=%d status_code=%d "
                        "retry_delay_seconds=%d",
                        attempt + 1,
                        response.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_exc  # type: ignore[misc]

            # ── Parse response body ───────────────────────────────────────
            try:
                body = response.json()
            except Exception as exc:
                # Invalid JSON — treat as retryable server error (POLL-REQ-013)
                last_exc = exc
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Parcel API invalid JSON attempt=%d retry_delay_seconds=%d",
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ParcelServerError(
                    status_code=response.status_code,
                    message=f"Parcel API returned invalid JSON after retries: {exc}",
                ) from exc

            # ── success flag check ────────────────────────────────────────
            if not body.get("success", False):
                error_msg = body.get("error_message", "Unknown error from Parcel API")
                raise ParcelResponseError(error_msg)

            # ── Parse and return delivery list ────────────────────────────
            raw_deliveries = body.get("deliveries", [])
            logger.debug(
                "Parcel API success deliveries_count=%d", len(raw_deliveries)
            )
            return self._parse_deliveries(raw_deliveries)

        # Should be unreachable — loop always raises or returns
        raise ParcelServerError(
            status_code=None,
            message="All Parcel API retry attempts exhausted",
        )

    async def get_carriers(self) -> list[CarrierDTO]:
        """Fetch the carrier code → name mapping from the Parcel API.

        Used by :class:`~app.infrastructure.parcel_api.carrier_cache.CarrierCache`
        for its periodic refresh.  A single GET with no retry logic — the
        carrier cache tolerates staleness gracefully (API-REQ-020).
        """
        try:
            response = await self._client.get(
                f"{_PARCEL_BASE_URL}{_CARRIERS_PATH}",
                headers={"api-key": self._api_key},
                timeout=10.0,
            )
            response.raise_for_status()
            data: dict = response.json()
            return [CarrierDTO(code=k, name=v) for k, v in data.items()]
        except Exception as exc:
            logger.warning("get_carriers failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_deliveries(
        self, raw_deliveries: list[dict]
    ) -> list[ParcelDeliveryDTO]:
        """Convert raw Parcel API delivery dicts to ``ParcelDeliveryDTO`` objects.

        - Validates structure via ``ParcelAPIDelivery`` Pydantic schema.
        - Converts ``timestamp_expected`` / ``timestamp_expected_end`` from
          Unix epoch integers to UTC-aware ``datetime`` objects.
        - Maps ``event.event`` → ``event_description`` and
          ``event.additional`` → ``additional_info``.
        - ``date_expected`` and ``date_expected_end`` are preserved verbatim
          as raw strings (DM-BR-025).
        - Malformed individual delivery records are skipped with a WARNING;
          they do not abort the parse (defensive, fail-open per delivery).
        """
        result: list[ParcelDeliveryDTO] = []

        for idx, raw in enumerate(raw_deliveries):
            try:
                api_delivery = ParcelAPIDelivery.model_validate(raw)
            except ValidationError as exc:
                logger.warning(
                    "Skipping malformed delivery at index=%d error=%s",
                    idx,
                    exc,
                )
                continue

            # Convert Unix epoch → UTC datetime (None-safe)
            ts_expected = (
                datetime.fromtimestamp(
                    api_delivery.timestamp_expected, tz=timezone.utc
                )
                if api_delivery.timestamp_expected is not None
                else None
            )
            ts_expected_end = (
                datetime.fromtimestamp(
                    api_delivery.timestamp_expected_end, tz=timezone.utc
                )
                if api_delivery.timestamp_expected_end is not None
                else None
            )

            # Map API events → ParcelEventDTO (sequence_number = array index)
            events = [
                ParcelEventDTO(
                    event_description=e.event,
                    event_date_raw=e.date,
                    location=e.location,
                    additional_info=e.additional,
                    sequence_number=i,
                )
                for i, e in enumerate(api_delivery.events)
            ]

            result.append(
                ParcelDeliveryDTO(
                    tracking_number=api_delivery.tracking_number,
                    carrier_code=api_delivery.carrier_code,
                    description=api_delivery.description,
                    extra_information=api_delivery.extra_information,
                    parcel_status_code=api_delivery.status_code,
                    date_expected_raw=api_delivery.date_expected,
                    date_expected_end_raw=api_delivery.date_expected_end,
                    timestamp_expected=ts_expected,
                    timestamp_expected_end=ts_expected_end,
                    events=events,
                    raw_response=raw,
                )
            )

        return result
