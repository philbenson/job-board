"""Alembic's entry point, using the async engine the service uses.

The database URL comes from the application settings, never from alembic.ini,
so the service and the migrations read one setting and convert it one way.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from job_board.models import Base
from job_board.settings import DatabaseSettings

config = context.config

if config.config_file_name is not None:
    # Keep loggers that already exist, such as the application's when the
    # migrations run inside a test process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata  # autogenerate and `alembic check` compare against the models


def database_url() -> str:
    return DatabaseSettings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Emit the migrations as SQL without connecting."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
