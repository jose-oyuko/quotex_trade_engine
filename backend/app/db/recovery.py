"""Startup recovery: what was still in flight when the application last stopped."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import (
    AppSettingsRepository,
    ChainRepository,
    GroupRepository,
    TradeRepository,
)
from app.domain.records import (
    AppSettingRecord,
    ChainRecord,
    GroupRecord,
    GroupSettingsRecord,
    TradeRecord,
)

# How far back settled trades are read: enough to cover any "day" the risk limits can define.
RECENT_TRADES_WINDOW = timedelta(hours=48)


@dataclass(slots=True, frozen=True)
class RecoveryState:
    """Everything the engine needs to rebuild its in-memory state after a restart."""

    groups: list[GroupRecord]
    group_settings: list[GroupSettingsRecord]
    open_chains: list[ChainRecord]
    unsettled_trades: list[TradeRecord]
    app_settings: list[AppSettingRecord] = field(default_factory=list)
    recent_settled_trades: list[TradeRecord] = field(default_factory=list)


async def load_recovery_state(
    session_factory: async_sessionmaker[AsyncSession], *, now: datetime | None = None
) -> RecoveryState:
    """One short read transaction. The engine (Phase 4) decides what to do with the result:
    settle trades past their expiry from Quotex history, or mark them `unknown`."""
    since = (now or datetime.now(UTC)) - RECENT_TRADES_WINDOW
    async with session_factory() as session:
        groups = GroupRepository(session)
        trades = TradeRepository(session)
        return RecoveryState(
            groups=await groups.list_all(),
            group_settings=await groups.list_settings(),
            open_chains=await ChainRepository(session).list_open(),
            unsettled_trades=await trades.list_unsettled(),
            app_settings=await AppSettingsRepository(session).all(),
            recent_settled_trades=await trades.list_settled_since(since),
        )
