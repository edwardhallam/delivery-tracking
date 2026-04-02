"""HTTP auth schemas — Pydantic request/response models for authentication endpoints.

These are the wire-format contracts for the auth router.  They are distinct
from application DTOs and domain entities — they define exactly what goes on
the wire, including error envelope structure shared across all routers.

Architecture: ARCH-PRESENTATION §4
Requirements: API-REQ-005, API-REQ-006–009, SEC-REQ-018–024
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Login request
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Credentials submitted to POST /api/auth/login."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Token response
# ---------------------------------------------------------------------------


class AccessTokenResponse(BaseModel):
    """Payload of the access-token response returned on successful login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    """Seconds until the access token expires."""


class LoginResponse(BaseModel):
    """Envelope wrapping the access-token payload (API-REQ-005)."""

    data: AccessTokenResponse


# ---------------------------------------------------------------------------
# Error envelope — shared across ALL routers (API-REQ-005)
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """A single field-level error detail."""

    field: Optional[str] = None
    """The request field that caused the validation error, if applicable."""
    message: str


class ErrorBody(BaseModel):
    """The body of an error response."""

    code: str
    """Machine-readable error code (e.g. ``INVALID_CREDENTIALS``)."""
    message: str
    """Human-readable error summary."""
    details: Optional[Union[list[ErrorDetail], dict]] = None
    """Optional structured details — present on 422 validation errors."""


class ErrorResponse(BaseModel):
    """Standard error envelope used by every error response in the API."""

    error: ErrorBody
