"""LogoutUserUseCase — invalidate all outstanding tokens for a user."""
from __future__ import annotations

import logging

from app.domain.repositories.abstract_user_repository import AbstractUserRepository

logger = logging.getLogger(__name__)


class LogoutUserUseCase:
    """Atomically increment ``token_version`` to invalidate all active JWTs.

    After logout, any access or refresh token carrying the previous
    ``token_version`` is rejected at step 6 of the JWT validation chain
    (SEC-REQ-017, SEC-REQ-020).

    Architecture: ARCH-APPLICATION §4.3
    Requirements: SEC-REQ-020–021, API-REQ-009
    """

    def __init__(self, user_repo: AbstractUserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, user_id: int) -> None:
        """Increment ``token_version`` for the given user.

        The increment is performed atomically at the database level (an
        ``UPDATE … SET token_version = token_version + 1 RETURNING …``).
        This prevents race conditions where two concurrent logouts could
        issue the same version number.

        Database errors are intentionally NOT swallowed — if the increment
        fails, the caller receives the exception and the token is not
        considered invalidated.  The presentation layer should translate
        infrastructure DB errors to HTTP 500.

        Args:
            user_id: Integer primary key of the user being logged out.
        """
        await self._user_repo.increment_token_version(user_id)
        logger.info("token_version incremented for user_id=%d", user_id)
