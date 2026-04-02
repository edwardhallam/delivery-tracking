"""SQLAlchemyHealthChecker — concrete implementation of AbstractDBHealthChecker.

Performs a ``SELECT 1`` round-trip against the database and measures latency.
Used exclusively by ``GetHealthUseCase`` via FastAPI DI.

ARCH-INFRASTRUCTURE §2, API-REQ-016
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.system_dtos import HealthDatabaseDTO
from app.application.services.interfaces import AbstractDBHealthChecker

logger = logging.getLogger(__name__)


class SQLAlchemyHealthChecker(AbstractDBHealthChecker):
    """Performs a lightweight ``SELECT 1`` connectivity check.

    Accepts an ``AsyncSession`` so it fits into the standard
    ``Depends(get_async_session)`` DI chain in the presentation layer.

    The caller (``GetHealthUseCase``) wraps this in ``asyncio.wait_for``
    with a 3-second timeout (API-REQ-016).  This implementation does not
    apply its own timeout — it trusts the caller to enforce it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check(self) -> HealthDatabaseDTO:
        """Execute ``SELECT 1`` and return latency or ``disconnected`` status.

        Never raises — returns a ``disconnected`` DTO on any error so
        ``GetHealthUseCase`` can continue building the health aggregate.
        """
        try:
            start = time.monotonic()
            await self._session.execute(text("SELECT 1"))
            latency_ms = (time.monotonic() - start) * 1000.0
            return HealthDatabaseDTO(
                status="connected",
                latency_ms=round(latency_ms, 2),
            )
        except Exception as exc:
            logger.warning("Database health check failed: %s", exc)
            return HealthDatabaseDTO(status="disconnected", latency_ms=None)
