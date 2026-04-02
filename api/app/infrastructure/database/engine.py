"""Async SQLAlchemy engine, session factory, and FastAPI DI session dependency.

All infrastructure database components import from this module. The engine
and session factory are module-level singletons created at import time from
``app.config.settings``.

ARCH-INFRASTRUCTURE §2.1
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# ---------------------------------------------------------------------------
# Engine — shared across all requests and the polling scheduler
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # validate connections on checkout (important in Docker)
)

# ---------------------------------------------------------------------------
# Session factory — expire_on_commit=False prevents lazy-load errors after
# commit in async context (ARCH-INFRASTRUCTURE §2.1)
# ---------------------------------------------------------------------------

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# FastAPI DI dependency — yields one session per HTTP request
# ---------------------------------------------------------------------------


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI ``Depends()`` dependency that yields one ``AsyncSession`` per request.

    Commits on clean exit; rolls back on any exception.  Consumed exclusively
    by the presentation layer's DI providers — the polling scheduler manages
    its own session lifecycle independently.

    ARCH-INFRASTRUCTURE §2.2
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
