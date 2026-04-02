"""Application exceptions — orchestration-level failures.

These represent conditions discovered while executing a use case that are not
expressible as pure domain violations.  They are distinct from domain exceptions
and are mapped to HTTP responses exclusively in the presentation layer.

No HTTP status codes, no FastAPI imports, no framework dependencies.
"""
from __future__ import annotations

from typing import Optional


class ApplicationError(Exception):
    """Base class for all application-layer exceptions."""


# ---------------------------------------------------------------------------
# Parcel API exceptions (POLL-REQ-024–026)
# ---------------------------------------------------------------------------


class ParcelAPIError(ApplicationError):
    """Base for all Parcel API call failures.

    Raised by the infrastructure ``ParcelAPIClient``; caught by
    ``PollAndSyncUseCase`` in Phase 2.
    """


class ParcelRateLimitError(ParcelAPIError):
    """HTTP 429 received from the Parcel API — rate limit exceeded (POLL-REQ-024).

    Non-retryable.  The polling use case logs a WARNING and records the poll
    cycle as ``outcome=ERROR`` without retrying.
    """


class ParcelAuthError(ParcelAPIError):
    """HTTP 401 received from the Parcel API — API key invalid (POLL-REQ-025).

    Non-retryable.  The polling use case logs CRITICAL and records the poll
    cycle as ``outcome=ERROR``.  Operator intervention is required.
    """


class ParcelServerError(ParcelAPIError):
    """HTTP 5xx or network-level error from the Parcel API (POLL-REQ-026).

    Retryable.  The infrastructure client applies exponential back-off
    (3 retries: 15 s, 60 s, 120 s) before raising this exception.  Once
    raised, the polling use case records the poll cycle as ``outcome=ERROR``.
    """

    def __init__(self, status_code: Optional[int], message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ParcelResponseError(ParcelAPIError):
    """Parcel API returned a 200 with ``success=false`` in the response body.

    Treated as a non-retryable failure.
    """

    def __init__(self, error_message: str) -> None:
        super().__init__(error_message)


# ---------------------------------------------------------------------------
# System exceptions
# ---------------------------------------------------------------------------


class DatabaseUnavailableError(ApplicationError):
    """Database is unreachable during a poll cycle (POLL-REQ-031).

    When raised, the polling use case aborts immediately — no Parcel API call
    is attempted — and records the poll cycle as ``outcome=ERROR``.
    """
