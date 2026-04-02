"""RefreshAccessTokenUseCase — validate refresh context and return user."""
from __future__ import annotations

import logging

from app.application.dtos.auth_dtos import RefreshTokenClaimsDTO
from app.domain.entities.user import User
from app.domain.exceptions import (
    AccountDisabledError,
    TokenVersionMismatchError,
    UserNotFoundError,
)
from app.domain.repositories.abstract_user_repository import AbstractUserRepository

logger = logging.getLogger(__name__)


class RefreshAccessTokenUseCase:
    """Validate the refresh token's user context and prepare new access-token claims.

    The presentation layer handles JWT signature verification, expiry, and
    the ``type='refresh'`` check *before* calling this use case.  This use
    case only validates the user's current state against the decoded claims.

    Architecture: ARCH-APPLICATION §4.2
    Requirements: SEC-REQ-017–018, API-REQ-008
    """

    def __init__(self, user_repo: AbstractUserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, claims: RefreshTokenClaimsDTO) -> User:
        """Validate refresh token claims against the current user record.

        Args:
            claims: Pre-decoded claims from the refresh token cookie.

        Returns:
            The current :class:`~app.domain.entities.user.User` entity.
            The presentation layer signs a new access token using
            ``user.token_version``.

        Raises:
            UserNotFoundError:          ``claims.sub`` not found in the DB.
                                        Presentation layer MUST mask as 401
                                        (SEC-REQ-016).
            AccountDisabledError:       User exists but is disabled.
            TokenVersionMismatchError:  ``claims.token_version`` is older than
                                        the current DB value, indicating the
                                        token was issued before a logout
                                        (SEC-REQ-017, API-REQ-008).
        """
        user = await self._user_repo.get_by_username(claims.sub)

        if user is None:
            raise UserNotFoundError(claims.sub)

        if not user.is_active:
            raise AccountDisabledError()

        if user.token_version != claims.token_version:
            raise TokenVersionMismatchError()

        return user
