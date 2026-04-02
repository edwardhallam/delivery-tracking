"""Integration test conftest — real async database fixtures.

Requires a running PostgreSQL database at TEST_DATABASE_URL.
Set the environment variable before running integration tests:

    TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:5432/test_delivery pytest tests/integration/

The test database is created/dropped per test session using Base.metadata.
Each test gets a fresh transaction rolled back at teardown to preserve isolation.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing the models package executes its __init__.py, which imports all
# ORM classes and registers them with Base.metadata — required for create_all.
from app.infrastructure.database.models import Base  # noqa: F401  (also registers all ORM classes)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://test:test@localhost:5432/test_delivery",
    ),
)


@pytest.fixture(scope="session")
async def test_engine() -> AsyncEngine:
    """Create the test database schema once per session; drop it afterward."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(test_engine: AsyncEngine) -> AsyncSession:
    """Provide a fresh, transaction-isolated AsyncSession per test.

    The transaction is rolled back at the end of each test — no data persists
    between tests.
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as sess:
        async with sess.begin():
            yield sess
            await sess.rollback()
