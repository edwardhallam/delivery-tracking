"""UserORM — SQLAlchemy 2.0 table model for the ``users`` table.

The schema supports multiple rows (future multi-user expansion) but exactly
one record is expected in production (DM-BR-015).

``token_version`` is GAP-001 — required by the auth design (SEC-REQ-020) but
absent from ``02-data-model.md``.  It is incremented atomically on each
logout to invalidate all outstanding JWTs for a user.

ARCH-INFRASTRUCTURE §3.4
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class UserORM(Base):
    """ORM model for the ``users`` table.

    ``password_hash`` is excluded from ``__repr__`` to prevent accidental
    exposure in logs or debug traces (mirrors the domain entity behaviour).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # GAP-001: token_version not in 02-data-model.md; required by SEC-REQ-020
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        # Explicit unique index on username (mirrors the unique=True column arg)
        Index("uq_user_username", "username", unique=True),
    )

    def __repr__(self) -> str:
        """Safe representation that excludes ``password_hash``."""
        return (
            f"UserORM("
            f"id={self.id!r}, "
            f"username={self.username!r}, "
            f"is_active={self.is_active!r}, "
            f"token_version={self.token_version!r})"
        )
