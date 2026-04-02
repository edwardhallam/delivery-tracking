"""Alembic environment configuration.

Wires the migration framework to the application's ORM model registry and
a synchronous database connection.  Uses ``psycopg2`` (blocking driver) so
Alembic can run migrations in its standard synchronous fashion.

The asynchronous ``psycopg`` driver used by the FastAPI application at runtime
is not compatible with Alembic's migration runner; the synchronous driver is
the correct choice here (ARCH-INFRASTRUCTURE §2.3).

Task 6.1
"""
from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool

# ---------------------------------------------------------------------------
# Alembic config object — provides access to values defined in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Configure logging as defined in the [loggers] section of alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import the application config and ORM model registry.
#
# Importing ``app.infrastructure.database.models`` triggers the package
# __init__.py, which in turn imports all five ORM classes:
#   DeliveryORM, DeliveryEventORM, StatusHistoryORM, UserORM, PollLogORM
#
# This ensures every table definition is registered with Base.metadata
# *before* Alembic inspects it for autogenerate or migration runs.
# ---------------------------------------------------------------------------
from app.config import settings  # noqa: E402
from app.infrastructure.database.models import Base  # noqa: E402
from app.infrastructure.database.models import (  # noqa: E402, F401
    DeliveryEventORM,
    DeliveryORM,
    PollLogORM,
    StatusHistoryORM,
    UserORM,
)

# ``target_metadata`` is what Alembic compares against the live database when
# running ``alembic check`` or ``alembic revision --autogenerate``.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runner functions
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL statements to stdout (or a file) without a live database
    connection.  Useful for reviewing migration SQL before applying it, or
    for producing SQL to hand off to a DBA.
    """
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Opens a synchronous psycopg2 connection and applies all pending
    migrations.  ``NullPool`` is intentional: Alembic is a short-lived CLI
    process, not a long-running server, so connection pooling provides no
    benefit and would leave idle connections open unnecessarily.
    """
    connectable = sa.create_engine(
        settings.sync_database_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
