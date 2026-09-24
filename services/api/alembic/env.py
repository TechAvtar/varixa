"""Alembic environment: async engine, URL from app settings, batch mode for SQLite."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    # Keep loggers created before this point (the app's) alive when run in-process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# "alembic -x url=..." overrides; otherwise use application settings.
_x_url = context.get_x_argument(as_dictionary=True).get("url")
if _x_url:
    _url = _x_url
else:
    _settings = get_settings()
    # SQLite cannot create its file in a missing directory (fresh checkouts, CI).
    _settings.ensure_local_dirs()
    _url = _settings.database_url
config.set_main_option("sqlalchemy.url", _url)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        literal_binds=connection is None,
        compare_type=True,
        # SQLite cannot ALTER most things; batch mode recreates tables safely.
        render_as_batch=_url.startswith("sqlite"),
    )


def run_migrations_offline() -> None:
    _configure(url=_url)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync)
    await connectable.dispose()


def _run_online() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(run_migrations_online())
        return
    # Called from inside a running loop (e.g. async tests): run on a worker thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, run_migrations_online()).result()


if context.is_offline_mode():
    run_migrations_offline()
else:
    _run_online()
