"""Alembic environment: async engine, URL from the application settings.

`alembic upgrade head` (or `npm run db:upgrade`) uses the same database file as the app. Tests and
tools can override the URL with `Config.set_main_option("sqlalchemy.url", ...)`.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import Settings
from app.db import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Migrations must keep working when app code changes, so they use plain SQLAlchemy types, never
# our TypeDecorators (which only add Python-side conversion on top of these storage types).
_STORAGE_TYPES = {
    "UTCDateTime": "sa.DateTime(timezone=True)",
    "Money": "sa.BigInteger()",
    "DecimalList": "sa.JSON()",
}


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    if type_ == "type":
        rendered = _STORAGE_TYPES.get(type(obj).__name__)
        if rendered is not None:
            return rendered
    return False


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of touching a database."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        render_item=render_item,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # render_as_batch: SQLite cannot ALTER most things, so later migrations are rendered as
    # "copy table, swap" batches; on PostgreSQL they stay plain ALTERs.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
