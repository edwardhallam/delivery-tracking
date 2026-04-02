"""JWT token creation and validation for the presentation layer.

This module owns the full JWT lifecycle:
  - ``create_access_token``        — sign a short-lived access token
  - ``create_refresh_token``       — sign a long-lived refresh token
  - ``oauth2_scheme``              — Bearer-token extractor (auto_error=False)
  - ``UNAUTHORIZED``               — canonical 401 HTTPException (identical body
                                     for all auth failures — SEC-REQ-016)
  - ``validate_access_token``      — decode + validate an access JWT;
                                     returns raw claims dict
  - ``get_refresh_token_claims``   — FastAPI dependency; reads and validates the
                                     refresh cookie; returns RefreshTokenClaimsDTO

``get_current_user`` is declared in ``dependencies.py`` so it can be wired
with the user-repository Depends() in the same file without creating a
circular import.

JWT library: python-jose[cryptography] (HS256 signing).

Architecture: ARCH-PRESENTATION §5
Requirements: SEC-REQ-009–017, API-REQ-001–004, SEC-REQ-025–027
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

from app.application.dtos.auth_dtos import RefreshTokenClaimsDTO
from app.config import settings
from app.domain.entities.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OAuth2 scheme
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login",
    auto_error=False,
    # auto_error=False: we return our own error envelope on missing token
    # instead of FastAPI's default 401 plain text (API-REQ-005).
)

# ---------------------------------------------------------------------------
# Canonical 401 — identical body for ALL auth failures (SEC-REQ-016)
# ---------------------------------------------------------------------------

from fastapi import HTTPException, status as _status  # noqa: E402

UNAUTHORIZED: HTTPException = HTTPException(
    status_code=_status.HTTP_401_UNAUTHORIZED,
    detail={"error": {"code": "UNAUTHORIZED", "message": "Authentication required"}},
    headers={"WWW-Authenticate": "Bearer"},
)
"""Single 401 exception instance raised by all auth failure paths.

Every validation step raises this same object so the response body is
bit-for-bit identical regardless of the actual failure reason.  This
prevents timing-independent information leakage via response-body analysis
(SEC-REQ-016).
"""


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(user: User) -> tuple[str, int]:
    """Sign a new HS256 access token for ``user``.

    Returns:
        ``(signed_jwt, expires_in_seconds)``

    Claims:
        sub            — username
        type           — ``"access"`` (discriminator — SEC-REQ-012)
        token_version  — must match DB value at validation time (SEC-REQ-017)
        iat            — issued-at (Unix epoch seconds)
        exp            — expiry (Unix epoch seconds)
    """
    now = datetime.now(tz=timezone.utc)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    exp = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims: dict = {
        "sub": user.username,
        "type": "access",
        "token_version": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(
        claims,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expires_in


def create_refresh_token(user: User) -> str:
    """Sign a new HS256 refresh token for ``user``.

    Returns:
        Signed JWT string — stored in an httpOnly cookie by the auth router.

    Claims:
        sub, type="refresh", token_version, iat, exp
    """
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    claims: dict = {
        "sub": user.username,
        "type": "refresh",
        "token_version": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(
        claims,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


# ---------------------------------------------------------------------------
# Access-token claim extraction (steps 1–4 of the 6-step chain)
# ---------------------------------------------------------------------------


def validate_access_token_claims(token: Optional[str]) -> dict:
    """Decode and structurally validate an access JWT.

    Performs steps 1–4 of the 6-step validation chain (SEC-REQ-015):
      1. Token present                  → raises ``UNAUTHORIZED`` if None
      2. JWT signature valid            → raises ``UNAUTHORIZED`` on JWTError
      3. Token not expired              → raises ``UNAUTHORIZED`` on ExpiredSignatureError
      4. ``type`` claim == ``"access"`` → raises ``UNAUTHORIZED`` if mismatch

    Steps 5–6 (user exists, is_active, token_version) require a database
    lookup and are performed by ``get_current_user`` in ``dependencies.py``.

    All failures raise the **same** ``UNAUTHORIZED`` exception and log the
    reason at INFO level for server-side diagnostics (SEC-REQ-016, SEC-REQ-059).

    Args:
        token: Raw Bearer token string, or ``None`` if the header was absent.

    Returns:
        Decoded claims ``dict`` (guaranteed to have ``sub`` and
        ``token_version`` keys).

    Raises:
        HTTPException(401): Any of the four structural checks fail.
    """
    # Step 1 — token present
    if token is None:
        logger.info("JWT validation: no Bearer token in request")
        raise UNAUTHORIZED

    # Steps 2–3 — signature and expiry
    try:
        payload: dict = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except ExpiredSignatureError:
        logger.info("JWT validation: token expired")
        raise UNAUTHORIZED
    except JWTError as exc:
        logger.info("JWT validation: invalid signature (%s)", type(exc).__name__)
        raise UNAUTHORIZED

    # Step 4 — type discriminator (prevents refresh token being used as access)
    if payload.get("type") != "access":
        logger.info(
            "JWT validation: wrong token type '%s' (expected 'access')",
            payload.get("type"),
        )
        raise UNAUTHORIZED

    if not payload.get("sub") or payload.get("token_version") is None:
        logger.info("JWT validation: missing 'sub' or 'token_version' claims")
        raise UNAUTHORIZED

    return payload


# ---------------------------------------------------------------------------
# Refresh token cookie dependency
# ---------------------------------------------------------------------------


def get_refresh_token_claims(request: Request) -> RefreshTokenClaimsDTO:
    """FastAPI dependency — validate the refresh cookie and return its claims.

    Validates JWT signature, expiry, and the ``type="refresh"`` discriminator.
    Does NOT validate ``token_version`` against the database — that belongs to
    ``RefreshAccessTokenUseCase`` (application layer).

    Args:
        request: Injected by FastAPI — provides access to cookies.

    Returns:
        :class:`~app.application.dtos.auth_dtos.RefreshTokenClaimsDTO`.

    Raises:
        HTTPException(401): Cookie absent, invalid signature, expired, or
                            wrong token type.  Always ``UNAUTHORIZED``.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        logger.info("Refresh validation: no refresh_token cookie")
        raise UNAUTHORIZED

    try:
        payload: dict = jwt.decode(
            refresh_token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except ExpiredSignatureError:
        logger.info("Refresh validation: refresh token expired")
        raise UNAUTHORIZED
    except JWTError as exc:
        logger.info("Refresh validation: invalid token (%s)", type(exc).__name__)
        raise UNAUTHORIZED

    if payload.get("type") != "refresh":
        logger.info(
            "Refresh validation: wrong type '%s' (expected 'refresh')",
            payload.get("type"),
        )
        raise UNAUTHORIZED

    username: Optional[str] = payload.get("sub")
    token_version: Optional[int] = payload.get("token_version")

    if not username or token_version is None:
        logger.info("Refresh validation: missing claims")
        raise UNAUTHORIZED

    return RefreshTokenClaimsDTO(
        sub=username,
        token_version=token_version,
        type="refresh",
    )
