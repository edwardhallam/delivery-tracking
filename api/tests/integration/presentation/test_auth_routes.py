"""Presentation integration tests for auth routes.

Use cases are mocked via dependency_overrides — presentation tests validate
HTTP behaviour (status codes, cookies, headers, rate limiting), NOT business
logic (which is tested by unit tests in tests/unit/application/).

POST /api/auth/login  → credentials → access token + httpOnly cookie
POST /api/auth/refresh → refresh cookie → new access token
POST /api/auth/logout  → invalidate tokens + clear cookie
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import MockUserRepository, make_user
from tests.integration.presentation.conftest import fake_user
from app.application.use_cases.auth.authenticate_user import AuthenticateUserUseCase
from app.application.use_cases.auth.logout_user import LogoutUserUseCase
from app.application.use_cases.auth.refresh_token import RefreshAccessTokenUseCase
from app.domain.exceptions import AccountDisabledError, InvalidCredentialsError
from app.presentation.dependencies import (
    get_authenticate_use_case,
    get_current_user,
    get_logout_use_case,
    get_rate_limiter,
    get_refresh_use_case,
    get_user_repository,
)
from app.presentation.middleware.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


async def test_login_success_sets_httponly_cookie(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Successful login sets a refresh_token cookie that is httpOnly + samesite=strict."""
    logged_in_user = make_user(username="testuser", token_version=1)

    mock_auth = AsyncMock(spec=AuthenticateUserUseCase)
    mock_auth.execute.return_value = logged_in_user
    test_app.dependency_overrides[get_authenticate_use_case] = lambda: mock_auth
    # Pre-create RateLimiter in the async context to avoid thread-loop issues
    test_limiter = RateLimiter()
    test_app.dependency_overrides[get_rate_limiter] = lambda: test_limiter

    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "correct_password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "access_token" in body["data"]

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token" in set_cookie_header
    assert "httponly" in set_cookie_header.lower()
    assert "samesite=strict" in set_cookie_header.lower()
    assert "path=/api/auth" in set_cookie_header.lower()


async def test_login_wrong_password_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Wrong password returns 401 with the generic INVALID_CREDENTIALS code."""
    mock_auth = AsyncMock(spec=AuthenticateUserUseCase)
    mock_auth.execute.side_effect = InvalidCredentialsError()
    test_app.dependency_overrides[get_authenticate_use_case] = lambda: mock_auth
    test_limiter = RateLimiter()
    test_app.dependency_overrides[get_rate_limiter] = lambda: test_limiter

    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "WRONG"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_user_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Unknown username returns 401 — same response as wrong password (API-REQ-006)."""
    mock_auth = AsyncMock(spec=AuthenticateUserUseCase)
    mock_auth.execute.side_effect = InvalidCredentialsError()
    test_app.dependency_overrides[get_authenticate_use_case] = lambda: mock_auth
    test_limiter = RateLimiter()
    test_app.dependency_overrides[get_rate_limiter] = lambda: test_limiter

    response = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "anything"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_wrong_password_and_unknown_user_identical_response(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Wrong-password and unknown-user return bit-for-bit identical bodies (API-REQ-006)."""
    mock_auth = AsyncMock(spec=AuthenticateUserUseCase)
    mock_auth.execute.side_effect = InvalidCredentialsError()
    test_app.dependency_overrides[get_authenticate_use_case] = lambda: mock_auth
    test_limiter = RateLimiter()
    test_app.dependency_overrides[get_rate_limiter] = lambda: test_limiter

    wrong_pass = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "WRONG"},
    )
    no_user = await client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "anything"},
    )

    assert wrong_pass.status_code == no_user.status_code == 401
    assert (
        wrong_pass.json()["detail"]["error"]["code"]
        == no_user.json()["detail"]["error"]["code"]
    )
    assert (
        wrong_pass.json()["detail"]["error"]["message"]
        == no_user.json()["detail"]["error"]["message"]
    )


async def test_login_rate_limit_after_10_failures(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """After 10 failed login attempts, the 11th returns HTTP 429 (SEC-REQ-038–039)."""
    mock_auth = AsyncMock(spec=AuthenticateUserUseCase)
    mock_auth.execute.side_effect = InvalidCredentialsError()
    test_app.dependency_overrides[get_authenticate_use_case] = lambda: mock_auth
    # A fresh rate limiter with small window — pre-created in async context
    fresh_limiter = RateLimiter(window_seconds=60, max_failures=10)
    test_app.dependency_overrides[get_rate_limiter] = lambda: fresh_limiter

    # 10 failures
    for _ in range(10):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "wrong"},
        )
        assert resp.status_code == 401

    # 11th attempt — should be rate limited
    blocked = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------


async def test_refresh_validates_token_version_mismatch(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Refresh with a stale token_version returns 401 (SEC-REQ-017)."""
    from jose import jwt
    from app.config import settings

    repo = MockUserRepository()
    user = make_user(username="testuser", token_version=5)
    repo.users[user.username] = user
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    # Create a refresh token with stale version 3
    claims = {
        "sub": "testuser",
        "type": "refresh",
        "token_version": 3,  # stale — DB has 5
        "iat": 0,
        "exp": 9999999999,
    }
    stale_token = jwt.encode(
        claims,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )

    response = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": stale_token},
    )
    assert response.status_code == 401


async def test_refresh_token_as_access_token_rejected(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Using a refresh token in the Authorization Bearer header returns 401."""
    from jose import jwt
    from app.config import settings

    claims = {
        "sub": "testuser",
        "type": "refresh",  # WRONG type for access
        "token_version": 1,
        "iat": 0,
        "exp": 9999999999,
    }
    refresh_as_access = jwt.encode(
        claims,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )

    # Remove the get_current_user override so the real validation chain runs
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()

    response = await client.get(
        "/api/deliveries/",
        headers={"Authorization": f"Bearer {refresh_as_access}"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


async def test_logout_clears_cookie(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Logout returns 204 and clears the refresh_token cookie."""
    user = make_user(username="testuser", token_version=1, user_id=1)
    repo = MockUserRepository()
    repo.users[user.username] = user

    test_app.dependency_overrides[get_current_user] = lambda: user
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    response = await client.post("/api/auth/logout")
    assert response.status_code == 204

    set_cookie = response.headers.get("set-cookie", "")
    assert "refresh_token" in set_cookie
    assert "max-age=0" in set_cookie.lower() or "expires" in set_cookie.lower()


async def test_logout_increments_token_version(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Logout calls increment_token_version on the user repository (SEC-REQ-020)."""
    user = make_user(username="testuser", user_id=1, token_version=1)
    repo = MockUserRepository()
    repo.users[user.username] = user

    test_app.dependency_overrides[get_current_user] = lambda: user
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    await client.post("/api/auth/logout")
    assert 1 in repo.increment_token_version_called
