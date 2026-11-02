from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.repositories import TradeRepository
from tests.factories import make_trade


async def pragma(engine: AsyncEngine, name: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(f"PRAGMA {name}"))).scalar_one()


async def test_wal_mode_is_on(engine: AsyncEngine) -> None:
    assert await pragma(engine, "journal_mode") == "wal"


async def test_synchronous_is_normal(engine: AsyncEngine) -> None:
    assert await pragma(engine, "synchronous") == 1  # 1 = NORMAL


async def test_busy_timeout_is_set(engine: AsyncEngine) -> None:
    assert await pragma(engine, "busy_timeout") == 5000


async def test_foreign_keys_are_enforced(engine: AsyncEngine) -> None:
    assert await pragma(engine, "foreign_keys") == 1


async def test_a_trade_for_a_missing_chain_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await TradeRepository(session).upsert(make_trade(uuid4(), 999))
