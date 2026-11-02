from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import models  # noqa: F401  (registers the tables)
from app.db.base import Base
from app.db.engine import create_engine, create_session_factory

# Same reasoning as app/core/logging.py: never let tests (or the app) format tracebacks slowly.
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(
            colors=False, exception_formatter=structlog.dev.plain_traceback
        )
    ]
)


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A real SQLite file (WAL needs a file, not :memory:) with the schema created from the models.
    The migration itself is tested separately in test_migrations.py."""
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)
