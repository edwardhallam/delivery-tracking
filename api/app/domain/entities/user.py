"""User entity — the single service account credentials record."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """Domain entity representing the single service account.

    The table schema supports multiple rows for future multi-user expansion
    without a schema change, but exactly one record is expected in
    production (DM-BR-015).

    Invariants:
    - ``username`` is **case-sensitive** — no normalisation is applied at
      the domain layer (SEC-REQ-007).
    - ``password_hash`` is **always a bcrypt hash** — raw passwords are never
      stored (DM-BR-014).  Cost factor is configurable via ``bcrypt_rounds``
      in :class:`~app.config.Settings` (SEC-REQ-001–003).
    - ``password_hash`` is **excluded from** ``__repr__`` to prevent
      accidental exposure in log output or debug traces.
    - ``token_version`` is incremented atomically on each logout (SEC-REQ-020).
      JWTs carrying a ``token_version`` lower than the current DB value are
      rejected at the 6th step of the validation chain (SEC-REQ-017,
      API-REQ-004).  This is ``GAP-001`` — absent from ``02-data-model.md``
      but required by the auth design.
    - ``is_active = False`` is the only supported "removal" mechanism — records
      are never hard-deleted (DM-BR-016, DM-BR-017).
    """

    id: int                          # GENERATED ALWAYS AS IDENTITY (PostgreSQL)
    username: str                    # max 100 chars; case-sensitive; unique
    password_hash: str               # max 255 chars; bcrypt; NEVER logged or serialised
    created_at: datetime             # UTC; set once at creation
    is_active: bool                  # False prevents login; never delete the row
    token_version: int               # GAP-001; incremented on logout (SEC-REQ-020)
    last_login_at: Optional[datetime] = None  # UTC; updated on successful authentication

    def __repr__(self) -> str:
        """Return a safe representation that **excludes** ``password_hash``.

        This prevents the bcrypt hash from appearing in log output, error
        messages, or interactive debug sessions.
        """
        return (
            f"User("
            f"id={self.id!r}, "
            f"username={self.username!r}, "
            f"is_active={self.is_active!r}, "
            f"token_version={self.token_version!r}, "
            f"created_at={self.created_at!r}, "
            f"last_login_at={self.last_login_at!r}"
            f")"
        )
