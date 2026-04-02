"""Parcel API response schemas — Pydantic models for the external API payload.

These models validate and normalise the raw JSON from
``GET /external/deliveries/?filter_mode=recent``.  They are used **only**
within the infrastructure layer; the application layer never imports them.

Field name mapping (Parcel API → internal):
- ``event``          → ``event_description``
- ``additional``     → ``additional_info``
- ``status_code``    → ``parcel_status_code`` (via ``ParcelDeliveryDTO``)
- ``date_expected``  → ``date_expected_raw``   (verbatim; never parsed)

``timestamp_expected`` and ``timestamp_expected_end`` are Unix epoch integers
in the API.  The client converts them to UTC ``datetime`` objects before
returning ``ParcelDeliveryDTO`` to the application layer.

ARCH-INFRASTRUCTURE §6
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ParcelAPIEvent(BaseModel):
    """A single tracking event from the Parcel API ``events`` array."""

    event: str
    """Event description — maps to ``DeliveryEvent.event_description``."""

    date: str
    """Raw date string — stored verbatim as ``event_date_raw`` (DM-BR-009)."""

    location: Optional[str] = None

    additional: Optional[str] = None
    """Additional info — maps to ``DeliveryEvent.additional_info``."""


class ParcelAPIDelivery(BaseModel):
    """A single delivery object from the Parcel API response."""

    carrier_code: str
    description: str
    status_code: int
    tracking_number: str
    events: list[ParcelAPIEvent] = Field(default_factory=list)

    extra_information: Optional[str] = None
    date_expected: Optional[str] = None
    """Raw date string — stored verbatim as ``date_expected_raw`` (DM-BR-025)."""
    date_expected_end: Optional[str] = None
    """Raw date string — stored verbatim as ``date_expected_end_raw``."""
    timestamp_expected: Optional[int] = None
    """Unix epoch integer — converted to UTC ``datetime`` by the client."""
    timestamp_expected_end: Optional[int] = None
    """Unix epoch integer — converted to UTC ``datetime`` by the client."""


class ParcelAPIResponse(BaseModel):
    """Top-level Parcel API response envelope."""

    success: bool
    deliveries: list[ParcelAPIDelivery] = Field(default_factory=list)
    error_message: Optional[str] = None
