"""SQLAlchemyUserRepository — async SQLAlchemy implementation.

Implements :class:`~app.domain.repositories.abstract_user_repository.AbstractUserRepository`.

ARCH-INFRASTRUCTURE §5.2
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user import User
from app.domain.repositories.abstract_user_repository import AbstractUserRepository
from app.infrastructure.database.models.user_orm import UserORM
from app.infrastructure.mappers.user_mapper import UserMapper

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SQLAlchemyUserRepository(AbstractUserRepository):
    """Concrete async repository for the ``User`` entity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> Optional[User]:
        """Exact, case-sensitive username lookup (SEC-REQ-007).

        ``MUST NOT`` apply ``lower()`` or any case normalisation.
        """
        result = await self._session.execute(
            select(UserORM).where(UserORM.username == username)
        )
        orm = result.scalars().first()
        return UserMapper.to_domain(orm) if orm else None

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self._session.execute(
            select(UserORM).where(UserORM.id == user_id)
        )
        orm = result.scalars().first()
        return UserMapper.to_domain(orm) if orm else None

    async def update_last_login(self, user_id: int) -> None:
        """Record the current UTC timestamp as ``last_login_at`` (API-REQ-007)."""
        stmt = (
            sa_update(UserORM)
            .where(UserORM.id == user_id)
            .values(last_login_at=_utcnow())
        )
        await self._session.execute(stmt)

    async def increment_token_version(self, user_id: int) -> int:
        """Atomically increment ``token_version`` and return the new value.

        Single ``UPDATE … RETURNING`` — atomic at the database level
        (SEC-REQ-021).  Flushes immediately so the new value is available
        before the outer session commits.
        """
        stmt = (
            sa_update(UserORM)
            .where(UserORM.id == user_id)
            .values(token_version=UserORM.token_version + 1)
            .returning(UserORM.token_version)
        )
        result = await self._session.execute(stmt)
        new_version: int = result.scalar_one()
        await self._session.flush()
        return new_version

    async def get_user_count(self) -> int:
        """Return the total number of ``User`` records (used by seed script)."""
        result = await self._session.execute(
            select(func.count(UserORM.id))
        )
        return result.scalar_one()

    async def create(self, user: User) -> User:
        """Persist a new user record.

        ``user.id == 0`` signals a new, unsaved user; the mapper omits
        setting ``id`` on the ORM model so the database generates it.
        After ``flush()``, ``orm.id`` holds the database-assigned integer.
        """
        orm = UserMapper.to_orm(user)
        self._session.add(orm)
        await self._session.flush([orm])
        return UserMapper.to_domain(orm)
