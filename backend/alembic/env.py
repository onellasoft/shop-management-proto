"""Alembic migration environment (async-aware).

This env script drives both offline and online migrations. It is configured to:

* Source the database URL at runtime from the application ``Settings``
  (``settings.database_url``) rather than ``alembic.ini`` so migrations always
  target the same database as the running app.
* Run online migrations through SQLAlchemy's **async** engine
  (``create_async_engine`` + ``connection.run_sync``), matching the app's
  async stack (asyncpg driver).
* Autogenerate against ``Base.metadata``. All ORM model modules are imported
  (via ``app.models``) before ``target_metadata`` is read so autogenerate can
  see every table. As new models are added under ``app/models`` and exported
  from ``app.models``, they are picked up automatically.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings

# Import the declarative Base and ensure all model modules are imported so
# their tables register on ``Base.metadata`` for autogenerate.
from app.db.base import Base
import app.models  # noqa: F401  (side-effecting import registers model tables)

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------
config = context.config

# Configure logging from alembic.ini if a config file is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL from application settings so migrations and
# the app never diverge.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Metadata used by ``--autogenerate`` to diff models against the database.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context on a live (sync-facing) connection and migrate."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within a sync-run callback."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for 'online' migrations using the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
