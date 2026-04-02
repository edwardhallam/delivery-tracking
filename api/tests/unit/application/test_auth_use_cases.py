"""Unit tests for authentication use cases.

Uses in-memory mock repositories — no database required.

We mock ``passlib.hash.bcrypt.verify`` throughout to avoid the bcrypt ≥4.0 /
passlib 1.7.4 compatibility issue where passlib's ``detect_wrap_bug`` tries
to hash a >72-byte string and the newer bcrypt library raises ``ValueError``.
The mock keeps tests fast and deterministic.

Critical security behaviour under test:
  - Dummy bcrypt verify fires when username not found (SEC-REQ-008)
  - Both unknown-user and wrong-password raise InvalidCredentialsError with
    the same message (API-REQ-006)
  - token_version mismatch on refresh raises TokenVersionMismatchError
  - Logout increments token_version
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import MockUserRepository, make_user
from tests.unit.application.conftest import (
    CORRECT_PASSWORD,
    CORRECT_PASSWORD_HASH,
    WRONG_PASSWORD,
)
from app.application.dtos.auth_dtos import LoginCredentialsDTO, RefreshTokenClaimsDTO
from app.application.use_cases.auth.authenticate_user import AuthenticateUserUseCase
from app.application.use_cases.auth.logout_user import LogoutUserUseCase
from app.application.use_cases.auth.refresh_token import RefreshAccessTokenUseCase
from app.domain.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    TokenVersionMismatchError,
    UserNotFoundError,
)

_VERIFY_PATH = "app.application.use_cases.auth.authenticate_user.passlib.hash.bcrypt.verify"
_DUMMY_HASH_PATH = "app.application.use_cases.auth.authenticate_user._dummy_hash"


# ---------------------------------------------------------------------------
# AuthenticateUserUseCase
# ---------------------------------------------------------------------------


async def test_login_unknown_user_calls_dummy_verify(
    mock_user_repo: MockUserRepository,
) -> None:
    """When username is not found, a dummy bcrypt verify MUST still be called.

    This prevents timing-based username enumeration: a missing username
    should consume the same CPU time as a wrong-password attempt
    (SEC-REQ-008).
    """
    use_case = AuthenticateUserUseCase(mock_user_repo)
    credentials = LoginCredentialsDTO(username="ghost", password="irrelevant")

    # Patch _dummy_hash so it returns a sentinel string without touching bcrypt
    with patch(_DUMMY_HASH_PATH, return_value="mocked_dummy_hash") as _mocked_hash:
        with patch(_VERIFY_PATH) as mock_verify:
            mock_verify.return_value = False
            with pytest.raises(InvalidCredentialsError):
                await use_case.execute(credentials)

    # verify MUST have been called exactly once even though user was None
    mock_verify.assert_called_once()


async def test_login_wrong_password_raises_invalid_credentials(
    mock_user_repo: MockUserRepository,
) -> None:
    """Wrong password raises InvalidCredentialsError (not UserNotFoundError)."""
    user = make_user(password_hash=CORRECT_PASSWORD_HASH)
    mock_user_repo.users[user.username] = user

    use_case = AuthenticateUserUseCase(mock_user_repo)

    with patch(_VERIFY_PATH, return_value=False):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(
                LoginCredentialsDTO(username=user.username, password=WRONG_PASSWORD)
            )


async def test_login_wrong_password_and_unknown_user_same_exception(
    mock_user_repo: MockUserRepository,
) -> None:
    """Unknown-user and wrong-password must raise the same exception type
    with the same message (API-REQ-006)."""
    user = make_user(password_hash=CORRECT_PASSWORD_HASH)
    mock_user_repo.users[user.username] = user

    use_case = AuthenticateUserUseCase(mock_user_repo)

    with patch(_DUMMY_HASH_PATH, return_value="mocked_dummy_hash"):
        with patch(_VERIFY_PATH, return_value=False):
            with pytest.raises(InvalidCredentialsError) as exc_wrong_pass:
                await use_case.execute(
                    LoginCredentialsDTO(username=user.username, password=WRONG_PASSWORD)
                )
            with pytest.raises(InvalidCredentialsError) as exc_no_user:
                await use_case.execute(
                    LoginCredentialsDTO(username="nonexistent", password="whatever")
                )

    # Both errors must have the same message (indistinguishable)
    assert str(exc_wrong_pass.value) == str(exc_no_user.value)


async def test_login_inactive_user_raises_account_disabled(
    mock_user_repo: MockUserRepository,
) -> None:
    """An inactive user account raises AccountDisabledError after password check."""
    user = make_user(password_hash=CORRECT_PASSWORD_HASH, is_active=False)
    mock_user_repo.users[user.username] = user

    use_case = AuthenticateUserUseCase(mock_user_repo)

    with patch(_VERIFY_PATH, return_value=True):  # password matches
        with pytest.raises(AccountDisabledError):
            await use_case.execute(
                LoginCredentialsDTO(username=user.username, password=CORRECT_PASSWORD)
            )


async def test_login_updates_last_login_on_success(
    mock_user_repo: MockUserRepository,
) -> None:
    """Successful login calls update_last_login with the user's ID (API-REQ-007)."""
    user = make_user(password_hash=CORRECT_PASSWORD_HASH)
    mock_user_repo.users[user.username] = user

    use_case = AuthenticateUserUseCase(mock_user_repo)

    with patch(_VERIFY_PATH, return_value=True):
        result = await use_case.execute(
            LoginCredentialsDTO(username=user.username, password=CORRECT_PASSWORD)
        )

    assert result.id == user.id
    assert user.id in mock_user_repo.update_last_login_called


async def test_login_returns_user_entity_on_success(
    mock_user_repo: MockUserRepository,
) -> None:
    """Successful login returns the User domain entity."""
    user = make_user(password_hash=CORRECT_PASSWORD_HASH)
    mock_user_repo.users[user.username] = user

    use_case = AuthenticateUserUseCase(mock_user_repo)

    with patch(_VERIFY_PATH, return_value=True):
        result = await use_case.execute(
            LoginCredentialsDTO(username=user.username, password=CORRECT_PASSWORD)
        )

    assert result.username == user.username
    assert result.is_active is True


# ---------------------------------------------------------------------------
# RefreshAccessTokenUseCase
# ---------------------------------------------------------------------------


async def test_refresh_token_version_mismatch_raises_error(
    mock_user_repo: MockUserRepository,
) -> None:
    """Stale token_version in claims raises TokenVersionMismatchError (SEC-REQ-017)."""
    user = make_user(token_version=5)
    mock_user_repo.users[user.username] = user

    use_case = RefreshAccessTokenUseCase(mock_user_repo)
    # Token carries version 3, DB has version 5
    claims = RefreshTokenClaimsDTO(
        sub=user.username, token_version=3, type="refresh"
    )

    with pytest.raises(TokenVersionMismatchError):
        await use_case.execute(claims)


async def test_refresh_unknown_user_raises_user_not_found(
    mock_user_repo: MockUserRepository,
) -> None:
    """Refresh with unknown sub raises UserNotFoundError."""
    use_case = RefreshAccessTokenUseCase(mock_user_repo)
    claims = RefreshTokenClaimsDTO(
        sub="ghost", token_version=1, type="refresh"
    )
    with pytest.raises(UserNotFoundError):
        await use_case.execute(claims)


async def test_refresh_inactive_user_raises_account_disabled(
    mock_user_repo: MockUserRepository,
) -> None:
    """Refresh for an inactive user raises AccountDisabledError."""
    user = make_user(is_active=False, token_version=1)
    mock_user_repo.users[user.username] = user

    use_case = RefreshAccessTokenUseCase(mock_user_repo)
    claims = RefreshTokenClaimsDTO(
        sub=user.username, token_version=1, type="refresh"
    )
    with pytest.raises(AccountDisabledError):
        await use_case.execute(claims)


async def test_refresh_valid_claims_returns_user(
    mock_user_repo: MockUserRepository,
) -> None:
    """Valid refresh claims return the User entity."""
    user = make_user(token_version=2)
    mock_user_repo.users[user.username] = user

    use_case = RefreshAccessTokenUseCase(mock_user_repo)
    claims = RefreshTokenClaimsDTO(
        sub=user.username, token_version=2, type="refresh"
    )
    result = await use_case.execute(claims)
    assert result.username == user.username


# ---------------------------------------------------------------------------
# LogoutUserUseCase
# ---------------------------------------------------------------------------


async def test_logout_calls_increment_token_version(
    mock_user_repo: MockUserRepository,
) -> None:
    """Logout increments token_version to invalidate all active JWTs (SEC-REQ-020)."""
    user = make_user(user_id=7, token_version=1)
    mock_user_repo.users[user.username] = user

    use_case = LogoutUserUseCase(mock_user_repo)
    await use_case.execute(user_id=7)

    assert 7 in mock_user_repo.increment_token_version_called
    assert user.token_version == 2  # incremented in mock


async def test_logout_returns_none(
    mock_user_repo: MockUserRepository,
) -> None:
    """LogoutUserUseCase.execute() returns None (no return value needed)."""
    user = make_user(user_id=1)
    mock_user_repo.users[user.username] = user

    use_case = LogoutUserUseCase(mock_user_repo)
    result = await use_case.execute(user_id=1)
    assert result is None
