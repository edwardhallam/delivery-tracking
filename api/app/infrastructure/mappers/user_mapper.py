"""UserMapper — translates between UserORM and User domain entity.

``password_hash`` is mapped directly — the mapper does not inspect, log, or
transform credential data.

ARCH-INFRASTRUCTURE §4
"""
from __future__ import annotations

from app.domain.entities.user import User
from app.infrastructure.database.models.user_orm import UserORM


class UserMapper:
    """Static mapper between :class:`UserORM` and :class:`User`."""

    @staticmethod
    def to_domain(orm: UserORM) -> User:
        """Convert an ORM row to a pure domain entity."""
        return User(
            id=orm.id,
            username=orm.username,
            password_hash=orm.password_hash,
            created_at=orm.created_at,
            is_active=orm.is_active,
            token_version=orm.token_version,
            last_login_at=orm.last_login_at,
        )

    @staticmethod
    def to_orm(entity: User) -> UserORM:
        """Convert a domain entity to an ORM model for persistence.

        When ``entity.id == 0`` (sentinel for "not yet persisted"), the ``id``
        field is **not** set on the ORM instance — the database ``IDENTITY``
        column generates it.  After ``session.flush()``, ``orm.id`` will be
        populated with the database-assigned integer.
        """
        orm = UserORM(
            username=entity.username,
            password_hash=entity.password_hash,
            created_at=entity.created_at,
            is_active=entity.is_active,
            token_version=entity.token_version,
            last_login_at=entity.last_login_at,
        )
        # Only set id for existing users (id=0 signals a new, unsaved user)
        if entity.id != 0:
            orm.id = entity.id
        return orm
