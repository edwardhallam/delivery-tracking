"""Database seed script — creates the initial admin user on first boot.

Called by entrypoint.sh via ``python -m app.seed`` after ``alembic upgrade head``.
Safe to run on every container restart — exits cleanly when the users table
already contains at least one row (idempotent, DEPLOY-REQ-027).

Exit behaviour:
  - Users table non-empty  →  no-op, exits 0.
  - Users table empty, credentials not set  →  logs CRITICAL, exits 1.
    entrypoint.sh uses ``set -e``, so the container aborts before Uvicorn starts
    (DEPLOY-REQ-028: fail-fast prevents a running service with no usable login).
  - Users table empty, credentials set  →  creates user, exits 0.
    Logs a WARNING reminding the operator to remove ADMIN_PASSWORD from .env.

Security invariants:
  - The plaintext password is NEVER written to any log (SEC-REQ-061).
  - bcrypt cost is taken from settings.BCRYPT_ROUNDS (≥ 12, SEC-REQ-001–003).
  - Minimum password length: 12 characters (SEC-REQ-005).

Requirements: DM-BR-014–016, DM-MIG-004, DEPLOY-REQ-026–028, SEC-REQ-001–005,
              SEC-REQ-004 (warn operator to remove credential), SEC-REQ-061.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import func, select

from app.config import settings
from app.infrastructure.database.engine import async_session_factory
from app.infrastructure.database.models.user_orm import UserORM

logger = logging.getLogger(__name__)

# SEC-REQ-005: passwords shorter than this are rejected at seed time.
_MIN_PASSWORD_LENGTH: int = 12


async def seed_initial_user() -> None:
    """Create the initial admin user when the users table is empty.

    This function is idempotent — it performs a row-count check before doing
    any write.  It is safe to call unconditionally on every container start.

    Raises:
        SystemExit(1): when the database is empty and required credentials
            are absent or too short.  The calling process (entrypoint.sh)
            will abort due to ``set -e``.
    """
    async with async_session_factory() as session:

        # ── Idempotency guard (DM-MIG-004) ──────────────────────────────────
        count: int = await session.scalar(select(func.count(UserORM.id)))

        if count > 0:
            logger.info(
                "Seed: users table contains %d row(s) — initial seed skipped.",
                count,
            )
            return

        logger.info("Seed: users table is empty — validating seed credentials …")

        # ── Credential retrieval ─────────────────────────────────────────────
        username: str | None = settings.ADMIN_USERNAME
        password: str | None = (
            settings.ADMIN_PASSWORD.get_secret_value()
            if settings.ADMIN_PASSWORD is not None
            else None
        )

        # Validate ADMIN_USERNAME
        if not username or not username.strip():
            logger.critical(
                "Seed: ADMIN_USERNAME is not set. "
                "Set it in .env and restart the container (DEPLOY-REQ-028)."
            )
            sys.exit(1)

        # Validate ADMIN_PASSWORD present
        if not password:
            logger.critical(
                "Seed: ADMIN_PASSWORD is not set. "
                "Set it in .env and restart the container (DEPLOY-REQ-028). "
                "Remove it again after the first successful start (SEC-REQ-004)."
            )
            sys.exit(1)

        # Validate ADMIN_PASSWORD length (SEC-REQ-005)
        if len(password) < _MIN_PASSWORD_LENGTH:
            logger.critical(
                "Seed: ADMIN_PASSWORD is too short (%d chars). "
                "Minimum required: %d characters (SEC-REQ-005).",
                len(password),
                _MIN_PASSWORD_LENGTH,
            )
            # Defensively clear the password from local scope before exiting.
            password = None  # noqa: F841
            sys.exit(1)

        # ── Password hashing (SEC-REQ-001–003) ──────────────────────────────
        pwd_context = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
            bcrypt__rounds=settings.BCRYPT_ROUNDS,
        )
        password_hash = pwd_context.hash(password)

        # Clear plaintext password from scope as soon as the hash is produced.
        # This prevents accidental exposure in tracebacks (SEC-REQ-061).
        password = None  # noqa: F841

        # ── Persist user (DM-BR-014) ─────────────────────────────────────────
        now = datetime.now(timezone.utc)
        session.add(
            UserORM(
                username=username.strip(),
                password_hash=password_hash,
                is_active=True,
                token_version=1,  # initial token generation (SEC-REQ-020)
                created_at=now,
            )
        )
        await session.commit()

        # ── Post-seed operator warning (SEC-REQ-004) ─────────────────────────
        logger.warning(
            "Seed: Initial admin user '%s' created successfully. "
            "IMPORTANT — remove ADMIN_PASSWORD from your .env file now "
            "to prevent credential exposure on subsequent restarts.",
            username,
        )


if __name__ == "__main__":
    # Configure minimal logging so the script is self-contained when invoked
    # directly (python -m app.seed) without the full Uvicorn logging stack.
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(seed_initial_user())
