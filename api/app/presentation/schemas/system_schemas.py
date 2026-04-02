"""HTTP system schemas — health and carrier list response models.

Architecture: ARCH-PRESENTATION §4
Requirements: API-REQ-016–020
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_serializer


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as ISO 8601 UTC with Z suffix, or None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Health schemas
# ---------------------------------------------------------------------------


class DatabaseHealthSchema(BaseModel):
    """Database connectivity status."""

    status: Literal["connected", "disconnected"]
    latency_ms: Optional[float] = None
    """Round-trip latency in milliseconds; ``None`` when unreachable."""


class PollingHealthSchema(BaseModel):
    """Polling scheduler status snapshot."""

    scheduler_running: bool
    last_poll_at: Optional[datetime] = None
    last_poll_outcome: Optional[str] = None
    last_successful_poll_at: Optional[datetime] = None
    consecutive_errors: int
    next_poll_at: Optional[datetime] = None

    @field_serializer(
        "last_poll_at",
        "last_successful_poll_at",
        "next_poll_at",
    )
    def serialize_optional_dt(self, v: Optional[datetime]) -> Optional[str]:
        return _fmt(v)


class HealthSchema(BaseModel):
    """Aggregated service health."""

    status: Literal["healthy", "degraded", "unhealthy"]
    database: DatabaseHealthSchema
    polling: PollingHealthSchema
    version: str


class HealthResponse(BaseModel):
    """Top-level envelope for GET /api/health."""

    data: HealthSchema


# ---------------------------------------------------------------------------
# Carrier schemas
# ---------------------------------------------------------------------------


class CarrierSchema(BaseModel):
    """A single carrier code → name mapping."""

    code: str
    name: str


class CarrierListSchema(BaseModel):
    """Carrier list with cache metadata."""

    carriers: list[CarrierSchema]
    cached_at: Optional[datetime] = None
    cache_status: Literal["fresh", "stale", "unavailable"]

    @field_serializer("cached_at")
    def serialize_cached_at(self, v: Optional[datetime]) -> Optional[str]:
        return _fmt(v)


class CarrierListResponse(BaseModel):
    """Top-level envelope for GET /api/carriers."""

    data: CarrierListSchema
