"""AuthenticateUserUseCase — verify credentials and prepare token claims."""
from __future__ import annotations

import logging

import functools

import passlib.hash

from app.application.dtos.auth_dtos import LoginCredentialsDTO
from app.domain.entities.user import User
from app.domain.exceptions import AccountDisabledError, InvalidCredentialsError
from app.domain.repositories.abstract_user_repository import AbstractUserRepository

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Return a bcrypt hash of a constant string, computed once and cached.

    Lazy evaluation (rather than module-load-time computation) avoids import
    side effects and is compatible with all passlib/bcrypt backend versions.

    The hash is used in the timing-attack mitigation path (SEC-REQ-008) —
    when a username is not found we still run a full bcrypt verify against
    this hash so the response time is indistinguishable from a wrong-password
    attempt.
    """
    return passlib.hash.bcrypt.hash("__dummy__")


class AuthenticateUserUseCase:
    """Verify credentials and return the authenticated ``User`` entity.

    The presentation layer is responsible for creating JWT access and refresh
    tokens from the returned ``User``.  This use case is concerned only with
    credential verification and last-login bookkeeping.

    Architecture: ARCH-APPLICATION §4.1
    Requirements: SEC-REQ-007–008, API-REQ-006–007
    """

    def __init__(self, user_repo: AbstractUserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, credentials: LoginCredentialsDTO) -> User:
        """Verify username and password.

        Args:
            credentials: Supplied username and password.

        Returns:
            The authenticated :class:`~app.domain.entities.user.User` entity.

        Raises:
            InvalidCredentialsError: Username not found or password incorrect.
            AccountDisabledError:    User exists but ``is_active`` is ``False``.
        """
        user = await self._user_repo.get_by_username(credentials.username)

        if user is None:
            # CRITICAL: dummy verify MUST run to consume the same CPU time as a
            # real bcrypt check.  Without this, a missing username returns
            # faster than a wrong password, leaking the username's existence
            # (SEC-REQ-008).
            passlib.hash.bcrypt.verify(credentials.password, _dummy_hash())
            raise InvalidCredentialsError()

        if not passlib.hash.bcrypt.verify(credentials.password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise AccountDisabledError()

        # Record successful authentication timestamp (API-REQ-007).
        await self._user_repo.update_last_login(user.id)

        return user
