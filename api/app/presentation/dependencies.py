"""Dependency injection providers — the architectural seam of the service.

This is the ONLY file that explicitly links application use-case interfaces
to their concrete infrastructure implementations.  Every layer above
(routers) receives injected objects; every layer below (infrastructure) has
no knowledge of FastAPI.

All use of ``Depends()`` lives either here or in ``auth.py``.  No other
file outside ``presentation/`` ever imports FastAPI.

Architecture: ARCH-PRESENTATION §6
Requirements: SEC-REQ-025–027
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.interfaces import (
    AbstractCarrierCache,
    AbstractSchedulerState,
)
from app.domain.repositories.abstract_user_repository import AbstractUserRepository
from app.application.use_cases.auth.authenticate_user import AuthenticateUserUseCase
from app.application.use_cases.auth.logout_user import LogoutUserUseCase
from app.application.use_cases.auth.refresh_token import RefreshAccessTokenUseCase
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase
from app.application.use_cases.deliveries.get_delivery_detail import (
    GetDeliveryDetailUseCase,
)
from app.application.use_cases.system.get_carriers import GetCarriersUseCase
from app.application.use_cases.system.get_health import GetHealthUseCase
from app.domain.entities.user import User
from app.domain.repositories.abstract_delivery_repository import (
    AbstractDeliveryRepository,
)
from app.domain.repositories.abstract_poll_log_repository import (
    AbstractPollLogRepository,
)
from app.infrastructure.database.engine import async_session_factory
from app.infrastructure.database.health_checker import SQLAlchemyHealthChecker
from app.infrastructure.database.repositories.sqlalchemy_delivery_repository import (
    SQLAlchemyDeliveryRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_poll_log_repository import (
    SQLAlchemyPollLogRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)
from app.presentation.auth import UNAUTHORIZED, oauth2_scheme, validate_access_token_claims
from app.presentation.middleware.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database session provider
# ---------------------------------------------------------------------------


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yield one ``AsyncSession`` per HTTP request.

    Commits on clean exit; rolls back on any exception.  Each HTTP request
    gets its own session; the polling scheduler manages its own sessions
    independently.

    Note: this re-declares the same session lifecycle as
    ``app.infrastructure.database.engine.get_async_session`` but lives in
    the presentation layer so that ``app.dependency_overrides`` can replace
    it cleanly in tests without touching infrastructure modules.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Repository providers
# ---------------------------------------------------------------------------


async def get_delivery_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractDeliveryRepository:
    """Provide a ``SQLAlchemyDeliveryRepository`` bound to the request session."""
    return SQLAlchemyDeliveryRepository(session)


async def get_user_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractUserRepository:
    """Provide a ``SQLAlchemyUserRepository`` bound to the request session."""
    return SQLAlchemyUserRepository(session)


async def get_poll_log_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractPollLogRepository:
    """Provide a ``SQLAlchemyPollLogRepository`` bound to the request session."""
    return SQLAlchemyPollLogRepository(session)


# ---------------------------------------------------------------------------
# External-service / scheduler providers (read from app.state)
# ---------------------------------------------------------------------------


def get_carrier_cache(request: Request) -> AbstractCarrierCache:
    """Return the ``CarrierCache`` singleton stored on ``app.state``.

    The carrier cache is populated during lifespan startup and stored on
    ``app.state.carrier_cache``.  It is synchronous (in-memory) so no
    async is needed (API-REQ-019).
    """
    return request.app.state.carrier_cache


def get_scheduler_state(request: Request) -> AbstractSchedulerState:
    """Return the ``PollingScheduler`` stored on ``app.state``.

    ``PollingScheduler`` implements ``AbstractSchedulerState`` so the health
    use case can query it without importing APScheduler.
    """
    return request.app.state.polling_scheduler


# ---------------------------------------------------------------------------
# Current-user dependency (6-step JWT validation chain)
# ---------------------------------------------------------------------------


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> User:
    """FastAPI dependency — validate a Bearer access token and return the User.

    Implements all 6 steps of the JWT validation chain (SEC-REQ-015):
      1–4. Structural checks via ``validate_access_token_claims`` (auth.py)
      5.   User exists AND ``is_active == True``
      6.   ``token_version`` claim matches ``users.token_version`` in DB

    ALL failures raise the **same** ``UNAUTHORIZED`` exception (SEC-REQ-016).
    The failure reason is logged at INFO level server-side (SEC-REQ-059) but
    is NEVER included in the response body.

    User identity comes exclusively from the validated token — never from
    the request body (SEC-REQ-027).

    Returns:
        The authenticated :class:`~app.domain.entities.user.User` entity.

    Raises:
        HTTPException(401): Any validation step fails.
    """
    # Steps 1–4: structural JWT validation (raises UNAUTHORIZED on failure)
    payload = validate_access_token_claims(token)

    username: str = payload["sub"]
    token_version: int = payload["token_version"]

    # Step 5: user exists and is active
    user = await user_repo.get_by_username(username)
    if user is None or not user.is_active:
        logger.info(
            "JWT validation: user '%s' not found or inactive", username
        )
        raise UNAUTHORIZED

    # Step 6: token_version matches DB (detects post-logout tokens — SEC-REQ-017)
    if user.token_version != token_version:
        logger.info(
            "JWT validation: token_version mismatch for '%s' "
            "(token=%d db=%d)",
            username,
            token_version,
            user.token_version,
        )
        raise UNAUTHORIZED

    return user


# ---------------------------------------------------------------------------
# Rate limiter provider
# ---------------------------------------------------------------------------

_rate_limiter = RateLimiter()
"""Module-level singleton — one shared in-memory rate limiter for the whole
process (SEC-REQ-036).  Created once at import time; never per-request."""


def get_rate_limiter() -> RateLimiter:
    """Return the module-level ``RateLimiter`` singleton."""
    return _rate_limiter


# ---------------------------------------------------------------------------
# Use-case providers
# ---------------------------------------------------------------------------


async def get_authenticate_use_case(
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> AuthenticateUserUseCase:
    """Provide ``AuthenticateUserUseCase`` with the request-scoped user repo."""
    return AuthenticateUserUseCase(user_repo)


async def get_refresh_use_case(
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> RefreshAccessTokenUseCase:
    """Provide ``RefreshAccessTokenUseCase`` with the request-scoped user repo."""
    return RefreshAccessTokenUseCase(user_repo)


async def get_logout_use_case(
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> LogoutUserUseCase:
    """Provide ``LogoutUserUseCase`` with the request-scoped user repo."""
    return LogoutUserUseCase(user_repo)


async def get_deliveries_use_case(
    delivery_repo: AbstractDeliveryRepository = Depends(get_delivery_repository),
) -> GetDeliveriesUseCase:
    """Provide ``GetDeliveriesUseCase`` with the request-scoped delivery repo."""
    return GetDeliveriesUseCase(delivery_repo)


async def get_delivery_detail_use_case(
    delivery_repo: AbstractDeliveryRepository = Depends(get_delivery_repository),
) -> GetDeliveryDetailUseCase:
    """Provide ``GetDeliveryDetailUseCase`` with the request-scoped delivery repo."""
    return GetDeliveryDetailUseCase(delivery_repo)


async def get_health_use_case(
    session: AsyncSession = Depends(get_async_session),
    poll_log_repo: AbstractPollLogRepository = Depends(get_poll_log_repository),
    scheduler_state: AbstractSchedulerState = Depends(get_scheduler_state),
) -> GetHealthUseCase:
    """Provide ``GetHealthUseCase`` with DB checker, poll-log repo, and scheduler.

    The ``SQLAlchemyHealthChecker`` receives its own session reference — it
    uses the same request-scoped session as the poll-log repo so both share
    the same transaction.
    """
    db_health_checker = SQLAlchemyHealthChecker(session)
    return GetHealthUseCase(
        poll_log_repo=poll_log_repo,
        db_health_checker=db_health_checker,
        scheduler_state=scheduler_state,
    )


async def get_carriers_use_case(
    carrier_cache: AbstractCarrierCache = Depends(get_carrier_cache),
) -> GetCarriersUseCase:
    """Provide ``GetCarriersUseCase`` with the in-memory carrier cache."""
    return GetCarriersUseCase(carrier_cache)
