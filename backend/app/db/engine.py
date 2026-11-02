"""Engine and session setup. SQLite is tuned here once (decisions D-3, D-4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

BUSY_TIMEOUT_MS = 5_000


def create_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    return engine


def _configure_sqlite_connection(dbapi_connection: Any, _record: Any) -> None:
    """WAL lets readers (dashboard, reports) work while the writer commits. `synchronous=NORMAL`
    is the usual safe pairing with WAL: a power cut can lose the last commits but never corrupts
    the file."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: records are copied out of rows before the session closes anyway,
    # and expired attributes would trigger lazy loads, which async sessions do not allow.
    return async_sessionmaker(engine, expire_on_commit=False)
