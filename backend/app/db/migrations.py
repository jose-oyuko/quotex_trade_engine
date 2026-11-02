"""Helpers around Alembic: where its config lives, and whether a database is up to date."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str | None = None) -> Config:
    """Alembic config. Without `url`, `alembic/env.py` takes the database from the app settings."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def schema_is_current(engine: AsyncEngine) -> bool:
    """True when the database is migrated to the newest revision."""
    async with engine.connect() as connection:
        return await connection.run_sync(_current_revision) == head_revision()
