"""Auth router — login, refresh, and logout endpoints.

Endpoints:
  POST /api/auth/login    — verify credentials, issue tokens, set cookie
  POST /api/auth/refresh  — issue new access token using refresh cookie
  POST /api/auth/logout   — invalidate tokens, clear cookie

Architecture: ARCH-PRESENTATION §7.1
Requirements: API-REQ-006–009, SEC-REQ-018–024, SEC-REQ-035–040
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.application.dtos.auth_dtos import LoginCredentialsDTO, RefreshTokenClaimsDTO
from app.application.use_cases.auth.authenticate_user import AuthenticateUserUseCase
from app.application.use_cases.auth.logout_user import LogoutUserUseCase
from app.application.use_cases.auth.refresh_token import RefreshAccessTokenUseCase
from app.config import settings
from app.domain.exceptions import AccountDisabledError, InvalidCredentialsError
from app.presentation.auth import (
    create_access_token,
    create_refresh_token,
    get_refresh_token_claims,
)
from app.presentation.dependencies import (
    get_authenticate_use_case,
    get_current_user,
    get_logout_use_case,
    get_rate_limiter,
    get_refresh_use_case,
)
from app.presentation.middleware.rate_limiter import RateLimiter
from app.presentation.schemas.auth_schemas import (
    AccessTokenResponse,
    ErrorBody,
    ErrorResponse,
    LoginRequest,
    LoginResponse,
)
from app.domain.entities.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Utility: client IP extraction
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request, trust_proxy: bool) -> str:
    """Extract the real client IP from the request.

    When ``trust_proxy=True`` (i.e. ``TRUST_PROXY_HEADERS=true``), reads
    ``X-Real-IP`` first, then the first value of ``X-Forwarded-For``.
    Falls back to the direct connection address when headers are absent or
    ``trust_proxy=False`` (SEC-REQ-040).

    Args:
        request:     FastAPI Request object.
        trust_proxy: Whether to honour proxy forwarding headers.

    Returns:
        IP address string — never ``None``.
    """
    if trust_proxy:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
    # Direct connection address
    client = request.client
    return client.host if client else "unknown"


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive tokens",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        403: {"model": ErrorResponse, "description": "Account disabled"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def login(
    body: LoginRequest,
    request: Request,
    use_case: AuthenticateUserUseCase = Depends(get_authenticate_use_case),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> JSONResponse:
    """Authenticate with username + password.

    On success:
      - Returns a JSON body with the short-lived access token.
      - Sets a ``refresh_token`` httpOnly cookie (path=/api/auth).

    Security:
      - Rate limiter is checked BEFORE the credential lookup (SEC-REQ-038).
      - Failed logins increment the rate-limit counter (SEC-REQ-035–037).
      - Successful logins reset the counter (SEC-REQ-037).
      - Unknown-username and wrong-password both return HTTP 401 with the
        **same** body to prevent username enumeration (API-REQ-006, SEC-REQ-008).
    """
    source_ip = _get_client_ip(request, trust_proxy=settings.TRUST_PROXY_HEADERS)

    # 1. Rate-limit check BEFORE use-case call (SEC-REQ-038)
    await rate_limiter.check(source_ip)

    # 2. Authenticate
    try:
        user = await use_case.execute(
            LoginCredentialsDTO(username=body.username, password=body.password)
        )
    except InvalidCredentialsError:
        await rate_limiter.record_failure(source_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorResponse(
                error=ErrorBody(code="INVALID_CREDENTIALS", message="Invalid credentials")
            ).model_dump(),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AccountDisabledError:
        # 403 for disabled account — but still mask identity via identical message
        # to the invalid-credentials response (SEC-REQ-016 guidance)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorResponse(
                error=ErrorBody(code="ACCOUNT_DISABLED", message="Account is disabled")
            ).model_dump(),
        )

    # 3. Success — reset rate limiter (SEC-REQ-037)
    await rate_limiter.reset(source_ip)

    # 4. Create tokens
    access_token, expires_in = create_access_token(user)
    refresh_token_str = create_refresh_token(user)

    # 5. Build response
    response_body = LoginResponse(
        data=AccessTokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        )
    )
    response = JSONResponse(
        content=response_body.model_dump(),
        status_code=status.HTTP_200_OK,
    )

    # 6. Set httpOnly refresh token cookie (SEC-REQ-022–024)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        samesite="strict",
        path="/api/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        secure=settings.COOKIE_SECURE,
    )

    logger.info(
        "Login successful: username=%s ip=%s",
        user.username,
        source_ip,
    )
    return response


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh the access token using the refresh cookie",
    responses={
        401: {"model": ErrorResponse, "description": "Refresh token invalid or expired"},
    },
)
async def refresh(
    claims: RefreshTokenClaimsDTO = Depends(get_refresh_token_claims),
    use_case: RefreshAccessTokenUseCase = Depends(get_refresh_use_case),
) -> LoginResponse:
    """Issue a new access token from a valid refresh cookie.

    The refresh token is read from the httpOnly ``refresh_token`` cookie —
    never from the request body (SEC-REQ-022).  The refresh token is NOT
    rotated on refresh (SEC-REQ-019).

    The use case validates ``token_version`` against the database to ensure
    the refresh token has not been invalidated by a logout (API-REQ-008).
    """
    # Use case validates user existence, is_active, and token_version
    try:
        user = await use_case.execute(claims)
    except Exception:
        # Masks UserNotFoundError, AccountDisabledError, TokenVersionMismatchError
        # all as 401 (SEC-REQ-016)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorResponse(
                error=ErrorBody(code="UNAUTHORIZED", message="Authentication required")
            ).model_dump(),
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(user)
    return LoginResponse(
        data=AccessTokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        )
    )


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate all tokens and clear the refresh cookie",
    responses={
        204: {"description": "Logged out — cookie cleared"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def logout(
    current_user: User = Depends(get_current_user),
    use_case: LogoutUserUseCase = Depends(get_logout_use_case),
) -> Response:
    """Logout the current user.

    Increments ``token_version`` in the database so all outstanding access
    and refresh tokens are immediately invalidated (SEC-REQ-020).  Deletes
    the ``refresh_token`` cookie.

    Requires a valid access token — ensures only the authenticated user can
    log themselves out (SEC-REQ-021).
    """
    await use_case.execute(current_user.id)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
        samesite="strict",
    )

    logger.info("Logout: username=%s", current_user.username)
    return response
