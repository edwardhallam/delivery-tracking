"""JWT validation chain integration tests.

Tests all 6 steps of the validation chain exhaustively (SEC-REQ-015–017).
Every step failure must produce the identical 401 response body.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt

from tests.conftest import MockUserRepository, make_user
from app.config import settings
from app.presentation.dependencies import get_current_user, get_user_repository

_SECRET = settings.JWT_SECRET_KEY.get_secret_value()
_ALGO = settings.JWT_ALGORITHM

_EXPECTED_401_CODE = "UNAUTHORIZED"


def _access_token(
    sub: str = "testuser",
    token_version: int = 1,
    type_claim: str = "access",
    exp_offset_seconds: int = 3600,
) -> str:
    """Build and sign a test access token."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "type": type_claim,
            "token_version": token_version,
            "iat": now,
            "exp": now + exp_offset_seconds,
        },
        _SECRET,
        algorithm=_ALGO,
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Step 1 — Token present
# ---------------------------------------------------------------------------


async def test_step1_missing_token_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """No Bearer token → 401 (step 1)."""
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()

    response = await client.get("/api/deliveries/")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == _EXPECTED_401_CODE


# ---------------------------------------------------------------------------
# Step 2–3 — Signature valid and not expired
# ---------------------------------------------------------------------------


async def test_step2_invalid_signature_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Token signed with wrong key → 401 (step 2)."""
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()

    # Sign with a different secret
    bad_token = jwt.encode(
        {"sub": "testuser", "type": "access", "token_version": 1,
         "iat": 0, "exp": 9999999999},
        "WRONG-SECRET-KEY-WITH-AT-LEAST-32-CHARS",
        algorithm=_ALGO,
    )
    response = await client.get("/api/deliveries/", headers=_auth_header(bad_token))
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == _EXPECTED_401_CODE


async def test_step3_expired_token_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Expired token → 401 (step 3)."""
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()

    expired_token = _access_token(exp_offset_seconds=-10)  # 10 seconds in the past

    response = await client.get("/api/deliveries/", headers=_auth_header(expired_token))
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Step 4 — type claim must be 'access'
# ---------------------------------------------------------------------------


async def test_step4_refresh_token_used_as_access_rejected(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Token with type='refresh' used as Bearer access token → 401 (step 4)."""
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()

    refresh_as_access = _access_token(type_claim="refresh")

    response = await client.get("/api/deliveries/", headers=_auth_header(refresh_as_access))
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == _EXPECTED_401_CODE


# ---------------------------------------------------------------------------
# Step 5 — User exists and is_active
# ---------------------------------------------------------------------------


async def test_step5_user_not_found_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Valid token but user not in DB → 401 (step 5)."""
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: MockUserRepository()  # empty

    token = _access_token(sub="ghost_user")

    response = await client.get("/api/deliveries/", headers=_auth_header(token))
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == _EXPECTED_401_CODE


async def test_step5_inactive_user_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Valid token for an inactive user → 401 (step 5)."""
    repo = MockUserRepository()
    repo.users["inactive"] = make_user(username="inactive", is_active=False)
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    token = _access_token(sub="inactive")

    response = await client.get("/api/deliveries/", headers=_auth_header(token))
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Step 6 — token_version matches DB
# ---------------------------------------------------------------------------


async def test_step6_token_version_mismatch_returns_401(
    client: AsyncClient, test_app: FastAPI
) -> None:
    """Token_version in JWT doesn't match DB value → 401 (step 6, SEC-REQ-017)."""
    repo = MockUserRepository()
    user = make_user(username="testuser", token_version=5)
    repo.users[user.username] = user
    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    # Token carries old version 3; DB has version 5
    stale_token = _access_token(sub="testuser", token_version=3)

    response = await client.get("/api/deliveries/", headers=_auth_header(stale_token))
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == _EXPECTED_401_CODE


# ---------------------------------------------------------------------------
# All 6 failures produce identical 401 bodies (SEC-REQ-016)
# ---------------------------------------------------------------------------


async def test_all_6_steps_return_identical_401_body(
    test_app: FastAPI,
) -> None:
    """Each of the 6 JWT validation failure modes returns the identical 401 body.

    This prevents information leakage via response-body fingerprinting
    (SEC-REQ-016).
    """
    user = make_user(username="realuser", token_version=5)
    repo = MockUserRepository()
    repo.users[user.username] = user

    test_app.dependency_overrides.pop(get_current_user, None)
    test_app.dependency_overrides[get_user_repository] = lambda: repo

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as c:
        # Step 1: no token
        r1 = await c.get("/api/deliveries/")

        # Step 2: bad signature
        bad_sig = jwt.encode(
            {"sub": "realuser", "type": "access", "token_version": 5,
             "iat": 0, "exp": 9999999999},
            "WRONG-SECRET-THAT-IS-32-CHARS-LONG!!",
            algorithm=_ALGO,
        )
        r2 = await c.get("/api/deliveries/", headers=_auth_header(bad_sig))

        # Step 3: expired
        r3 = await c.get("/api/deliveries/", headers=_auth_header(_access_token(exp_offset_seconds=-100)))

        # Step 4: wrong type
        r4 = await c.get("/api/deliveries/", headers=_auth_header(_access_token(type_claim="refresh")))

        # Step 5: user not found
        r5 = await c.get("/api/deliveries/", headers=_auth_header(_access_token(sub="unknown")))

        # Step 6: token_version mismatch
        r6 = await c.get("/api/deliveries/", headers=_auth_header(_access_token(sub="realuser", token_version=3)))

    responses = [r1, r2, r3, r4, r5, r6]
    bodies = [r.json() for r in responses]

    # All must be 401
    for i, r in enumerate(responses, 1):
        assert r.status_code == 401, f"Step {i} was not 401: got {r.status_code}"

    # All error codes must be identical
    codes = {b["detail"]["error"]["code"] for b in bodies}
    assert len(codes) == 1, f"Non-uniform error codes: {codes}"

    # All messages must be identical
    messages = {b["detail"]["error"]["message"] for b in bodies}
    assert len(messages) == 1, f"Non-uniform messages: {messages}"
