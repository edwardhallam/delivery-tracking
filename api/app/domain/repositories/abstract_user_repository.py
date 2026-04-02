"""AbstractUserRepository — persistence contract for user credentials."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.entities.user import User


class AbstractUserRepository(ABC):
    """Persistence contract for the ``User`` entity.

    Single-user service: there will typically be exactly one ``User`` record
    in production.  All methods are ``async``.
    """

    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[User]:
        """Fetch a user by exact username match.

        **Case-sensitive** — ``MUST NOT`` apply ``lower()`` or any case
        normalisation (SEC-REQ-007).

        Returns ``None`` if no user with that exact username exists.
        """
        ...

    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Fetch a user by primary key integer ID.

        Returns ``None`` if not found.
        """
        ...

    @abstractmethod
    async def update_last_login(self, user_id: int) -> None:
        """Record the current UTC timestamp as ``last_login_at``.

        Called after every successful authentication (API-REQ-007).
        """
        ...

    @abstractmethod
    async def increment_token_version(self, user_id: int) -> int:
        """Atomically increment ``token_version`` and return the new value.

        This single operation invalidates **all** outstanding JWTs for the
        user — any token carrying the old version value will fail the
        6th step of the validation chain (SEC-REQ-017, SEC-REQ-021).

        Implementations **must** use an atomic
        ``UPDATE users SET token_version = token_version + 1 WHERE id = :id
        RETURNING token_version`` to prevent race conditions.

        Returns:
            The new ``token_version`` value after increment.
        """
        ...

    @abstractmethod
    async def get_user_count(self) -> int:
        """Return the total number of ``User`` records.

        Used by the seed script to decide whether to create the initial
        admin account (DM-MIG-004).
        """
        ...

    @abstractmethod
    async def create(self, user: User) -> User:
        """Persist a new user record and return the saved entity.

        Used exclusively by the seed script on first container start.
        """
        ...
