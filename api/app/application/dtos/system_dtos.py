"""System DTOs — typed contracts for health, carrier, and polling internals.

These models define the health endpoint response shape, the carrier cache
interface, and the structured representation of a Parcel API delivery used
internally by the polling use case.

No SQLAlchemy, no FastAPI, no httpx imports.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Health DTOs
# ---------------------------------------------------------------------------


class HealthDatabaseDTO(BaseModel):
    """Database connectivity status as reported by the health checker."""

    status: Literal["connected", "disconnected"]
    latency_ms: Optional[float]
    """Round-trip time for the database ping in milliseconds; ``None`` when
    the database is unreachable."""


class HealthPollingDTO(BaseModel):
    """Polling scheduler status snapshot."""

    scheduler_running: bool
    last_poll_at: Optional[datetime]
    """``started_at`` of the most recent poll cycle; ``None`` if no cycle has
    ever run."""
    last_poll_outcome: Optional[str]
    """Outcome string from the most recent poll cycle."""
    last_successful_poll_at: Optional[datetime]
    """``started_at`` of the most recent successful cycle."""
    consecutive_errors: int
    """Number of consecutive non-SUCCESS outcomes (ERROR or PARTIAL) counted
    backwards from the most recent completed cycle (POLL-REQ-036)."""
    next_poll_at: Optional[datetime]
    """Next scheduled fire time from APScheduler; ``None`` if not running
    (API-REQ-018)."""


class HealthDTO(BaseModel):
    """Aggregated service health — returned by ``GetHealthUseCase``.

    Status determination:
    - ``'unhealthy'``:  DB disconnected OR scheduler not running.
    - ``'degraded'``:   three or more consecutive poll errors (POLL-REQ-036).
    - ``'healthy'``:    all subsystems nominal.

    HTTP status mapping (presentation layer responsibility, API-REQ-017):
    - ``'unhealthy'`` → 503
    - ``'healthy'`` / ``'degraded'`` → 200
    """

    status: Literal["healthy", "degraded", "unhealthy"]
    database: HealthDatabaseDTO
    polling: HealthPollingDTO
    version: str


# ---------------------------------------------------------------------------
# Carrier DTOs
# ---------------------------------------------------------------------------


class CarrierDTO(BaseModel):
    """A single carrier code → name mapping."""

    code: str
    name: str


class CarrierListDTO(BaseModel):
    """Carrier cache contents returned by ``GetCarriersUseCase``."""

    carriers: list[CarrierDTO]
    cached_at: Optional[datetime]
    """Timestamp of the last successful cache refresh; ``None`` if never
    fetched (API-REQ-020)."""
    cache_status: Literal["fresh", "stale", "unavailable"]
    """
    - ``'fresh'``:       TTL has not expired.
    - ``'stale'``:       TTL expired; last-known data returned without error (API-REQ-020).
    - ``'unavailable'``: Never successfully fetched.
    """


# ---------------------------------------------------------------------------
# Polling internal DTOs
# ---------------------------------------------------------------------------
# These DTOs are created by the infrastructure ParcelAPIClient and consumed
# by PollAndSyncUseCase.  They live in the application layer because the use
# case needs to understand their shape without importing httpx or any
# infrastructure module.


class ParcelEventDTO(BaseModel):
    """A single tracking event from a Parcel API delivery object."""

    event_description: str
    event_date_raw: str
    """Verbatim from the API — never parsed (DM-BR-009)."""
    location: Optional[str]
    additional_info: Optional[str]
    sequence_number: int
    """Array index in the Parcel API response (0 = oldest event)."""


class ParcelDeliveryDTO(BaseModel):
    """Structured representation of one delivery from the Parcel API response.

    Created by the infrastructure ``ParcelAPIClient``; consumed by
    ``PollAndSyncUseCase``.  The ``raw_response`` field carries the full
    response JSON for storage in ``deliveries.last_raw_response`` (DM-BR-004).
    """

    tracking_number: str
    carrier_code: str
    description: str
    extra_information: Optional[str]
    parcel_status_code: int
    date_expected_raw: Optional[str]
    date_expected_end_raw: Optional[str]
    timestamp_expected: Optional[datetime]
    timestamp_expected_end: Optional[datetime]
    events: list[ParcelEventDTO]
    raw_response: dict
    """Full Parcel API response payload stored verbatim (DM-BR-004)."""
