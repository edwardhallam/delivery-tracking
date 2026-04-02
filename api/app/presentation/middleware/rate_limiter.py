"""RateLimiter — in-memory sliding-window rate limiter for login protection.

Tracks failed login attempts per source IP address using a sliding time window.
When the failure threshold is exceeded, the ``check()`` method raises HTTP 429
with a ``Retry-After`` header indicating when the oldest failure will expire.

Design notes:
  - Pure in-memory state: a ``dict[str, list[datetime]]`` mapping IP → failure
    timestamps.  This means the counter resets on process restart — acceptable
    for a single-container deployment (SEC-REQ-036).
  - Sliding window (not fixed bucket): the window is anchored to the current
    time on each ``check()`` call, so a burst of failures at T=0 does NOT
    permanently block until T=WINDOW_SECONDS; the block expires naturally.
  - ``asyncio.Lock`` guards all mutations so concurrent requests for the same
    IP cannot race on the failures list.
  - The lock is only held for the duration of the list manipulation (microseconds)
    — no I/O or heavy computation occurs inside the critical section.

Architecture: ARCH-PRESENTATION §8.2
Requirements: SEC-REQ-035–039
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (SEC-REQ-035)
# ---------------------------------------------------------------------------

WINDOW_SECONDS: int = 900
"""Sliding window size: 15 minutes (900 seconds)."""

MAX_FAILURES: int = 10
"""Maximum failed login attempts within the window before blocking (SEC-REQ-035)."""


class RateLimiter:
    """Sliding-window in-memory rate limiter for login endpoint protection.

    Thread-safe via ``asyncio.Lock``.  One instance is created at module level
    in ``dependencies.py`` and shared across all requests (SEC-REQ-036).
    """

    def __init__(
        self,
        window_seconds: int = WINDOW_SECONDS,
        max_failures: int = MAX_FAILURES,
    ) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._max_failures = max_failures
        self._failures: dict[str, list[datetime]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def check(self, ip: str) -> None:
        """Raise HTTP 429 if the IP has exceeded the failure threshold.

        Prunes stale timestamps (outside the current window) before counting,
        so the check reflects the true sliding-window failure count.

        The ``Retry-After`` header value is the integer seconds until the
        oldest in-window failure expires — i.e. when the IP will be unblocked
        if no further failures occur (SEC-REQ-039).

        Args:
            ip: Client IP address string.

        Raises:
            HTTPException(429): Failure count exceeds ``MAX_FAILURES``.
                                Always includes ``Retry-After`` header.
        """
        async with self._lock:
            self._prune(ip)
            failures = self._failures.get(ip, [])

            if len(failures) >= self._max_failures:
                oldest = failures[0]
                retry_after = math.ceil(
                    (oldest + self._window - datetime.now(tz=timezone.utc)).total_seconds()
                )
                retry_after = max(retry_after, 1)  # never 0 or negative
                logger.warning(
                    "Rate limit exceeded: ip=%s failures=%d retry_after=%ds",
                    ip,
                    len(failures),
                    retry_after,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many failed attempts. Try again later.",
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )

    async def record_failure(self, ip: str) -> None:
        """Record a failed login attempt for ``ip``.

        Prunes stale timestamps before appending to keep memory bounded.

        Args:
            ip: Client IP address string.
        """
        async with self._lock:
            self._prune(ip)
            if ip not in self._failures:
                self._failures[ip] = []
            self._failures[ip].append(datetime.now(tz=timezone.utc))
            logger.debug(
                "Rate limit failure recorded: ip=%s count=%d",
                ip,
                len(self._failures[ip]),
            )

    async def reset(self, ip: str) -> None:
        """Clear all failure records for ``ip`` on successful authentication.

        Called after a successful login so the counter does not persist for
        legitimate users who previously made typos (SEC-REQ-037).

        Args:
            ip: Client IP address string.
        """
        async with self._lock:
            removed = self._failures.pop(ip, None)
            if removed:
                logger.debug(
                    "Rate limit reset for ip=%s (cleared %d failures)",
                    ip,
                    len(removed),
                )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prune(self, ip: str) -> None:
        """Remove timestamps outside the current sliding window for ``ip``.

        Must be called while holding ``self._lock``.
        """
        if ip not in self._failures:
            return
        cutoff = datetime.now(tz=timezone.utc) - self._window
        self._failures[ip] = [ts for ts in self._failures[ip] if ts > cutoff]
        if not self._failures[ip]:
            del self._failures[ip]
