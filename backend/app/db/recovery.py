"""Startup recovery: what was still in flight when the application last stopped."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.records import ChainRecord, GroupRecord, GroupSettingsRecord, TradeRecord


@dataclass(slots=True, frozen=True)
class RecoveryState:
    """Everything the engine needs to rebuild its in-memory state after a restart."""

    groups: list[GroupRecord]
    group_settings: list[GroupSettingsRecord]
    open_chains: list[ChainRecord]
    unsettled_trades: list[TradeRecord]


async def load_recovery_state(session_factory: async_sessionmaker[AsyncSession]) -> RecoveryState:
    """One short read transaction. The engine (Phase 4) decides what to do with the result:
    settle trades past their expiry from Quotex history, or mark them `unknown`."""
    async with session_factory() as session:
        groups = GroupRepository(session)
        return RecoveryState(
            groups=await groups.list_all(),
            group_settings=await groups.list_settings(),
            open_chains=await ChainRepository(session).list_open(),
            unsettled_trades=await TradeRepository(session).list_unsettled(),
        )
