from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import (
    AppSettingsRepository,
    BalanceSnapshotRepository,
    ChainRepository,
    GroupRepository,
    RiskEventRepository,
    SignalRepository,
    TradeRepository,
)
from app.domain.enums import (
    AccountType,
    ChainStatus,
    Direction,
    SignalStatus,
    Strategy,
    TradeStatus,
)
from app.domain.ids import new_id
from app.domain.records import GroupRecord
from tests.factories import (
    NOW,
    make_balance,
    make_chain,
    make_group,
    make_risk_event,
    make_settings,
    make_signal,
    make_trade,
)

Factory = async_sessionmaker[AsyncSession]


async def add_group(session_factory: Factory, **overrides: object) -> GroupRecord:
    async with session_factory.begin() as session:
        return await GroupRepository(session).add(make_group(**overrides))


class TestGroups:
    async def test_add_and_get(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        async with session_factory() as session:
            assert await GroupRepository(session).get(group.id) == group
            by_chat = await GroupRepository(session).get_by_chat_id(group.telegram_chat_id)
            assert by_chat == group

    async def test_get_missing_returns_none(self, session_factory: Factory) -> None:
        async with session_factory() as session:
            assert await GroupRepository(session).get(404) is None

    async def test_chat_id_is_unique(self, session_factory: Factory) -> None:
        await add_group(session_factory)
        with pytest.raises(IntegrityError):
            await add_group(session_factory, title="Duplicate")

    async def test_update_changes_title_and_enabled(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        later = NOW + timedelta(hours=1)
        async with session_factory.begin() as session:
            await GroupRepository(session).update(
                replace(group, title="Renamed", enabled=False, updated_at=later)
            )
        async with session_factory() as session:
            stored = await GroupRepository(session).get(group.id)  # type: ignore[arg-type]
        assert stored is not None
        assert (stored.title, stored.enabled, stored.updated_at) == ("Renamed", False, later)

    async def test_update_missing_group_fails(self, session_factory: Factory) -> None:
        async with session_factory.begin() as session:
            with pytest.raises(LookupError):
                await GroupRepository(session).update(make_group(id=404))

    async def test_list_can_filter_enabled(self, session_factory: Factory) -> None:
        await add_group(session_factory, telegram_chat_id=1, title="on")
        await add_group(session_factory, telegram_chat_id=2, title="off", enabled=False)
        async with session_factory() as session:
            repo = GroupRepository(session)
            assert [g.title for g in await repo.list_all()] == ["on", "off"]
            assert [g.title for g in await repo.list_all(enabled_only=True)] == ["on"]

    async def test_settings_roundtrip_keeps_exact_decimals(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        settings = make_settings(group.id, base_stake=Decimal("1.25"))
        async with session_factory.begin() as session:
            await GroupRepository(session).save_settings(settings)
        async with session_factory() as session:
            assert await GroupRepository(session).get_settings(group.id) == settings

    async def test_saving_settings_again_updates_them(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        async with session_factory.begin() as session:
            await GroupRepository(session).save_settings(make_settings(group.id))
        changed = make_settings(
            group.id, strategy=Strategy.MARTINGALE, max_steps=1, multipliers=(Decimal("2"),)
        )
        async with session_factory.begin() as session:
            await GroupRepository(session).save_settings(changed)
        async with session_factory() as session:
            repo = GroupRepository(session)
            assert await repo.get_settings(group.id) == changed
            assert len(await repo.list_settings()) == 1

    async def test_delete_removes_group_and_its_settings(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        async with session_factory.begin() as session:
            await GroupRepository(session).save_settings(make_settings(group.id))
        async with session_factory.begin() as session:
            assert await GroupRepository(session).delete(group.id) is True
        async with session_factory() as session:
            repo = GroupRepository(session)
            assert await repo.get(group.id) is None
            assert await repo.get_settings(group.id) is None
            assert await repo.delete(group.id) is False

    async def test_group_with_history_cannot_be_deleted(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        async with session_factory.begin() as session:
            await SignalRepository(session).upsert(make_signal(group.id))
        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await GroupRepository(session).delete(group.id)


class TestSignals:
    async def test_upsert_creates_then_updates(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        signal = make_signal(group.id, status=SignalStatus.NOT_PARSED, asset=None, direction=None)
        async with session_factory.begin() as session:
            await SignalRepository(session).upsert(signal)
        updated = replace(signal, status=SignalStatus.IGNORED, reason="chain active")
        async with session_factory.begin() as session:
            await SignalRepository(session).upsert(updated)
        async with session_factory() as session:
            assert await SignalRepository(session).get(signal.id) == updated

    async def test_list_filters_and_orders_newest_first(self, session_factory: Factory) -> None:
        a = await add_group(session_factory, telegram_chat_id=1)
        b = await add_group(session_factory, telegram_chat_id=2)
        assert a.id is not None and b.id is not None
        old = make_signal(a.id, received_at=NOW)
        new = make_signal(a.id, received_at=NOW + timedelta(minutes=1), status=SignalStatus.IGNORED)
        other = make_signal(b.id)
        async with session_factory.begin() as session:
            for signal in (old, new, other):
                await SignalRepository(session).upsert(signal)
        async with session_factory() as session:
            repo = SignalRepository(session)
            assert [s.id for s in await repo.list(group_id=a.id)] == [new.id, old.id]
            assert [s.id for s in await repo.list(status=SignalStatus.IGNORED)] == [new.id]

    async def test_paging_is_bounded(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        async with session_factory.begin() as session:
            for n in range(5):
                await SignalRepository(session).upsert(
                    make_signal(group.id, received_at=NOW + timedelta(seconds=n))
                )
        async with session_factory() as session:
            repo = SignalRepository(session)
            assert len(await repo.list(limit=2)) == 2
            assert len(await repo.list(limit=2, offset=4)) == 1
            assert len(await repo.list(limit=-5)) == 1  # clamped to at least one row

    async def test_naive_datetime_is_refused(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        naive = make_signal(group.id, received_at=datetime(2026, 11, 1, 12, 0))
        with pytest.raises(StatementError, match="naive"):
            async with session_factory.begin() as session:
                await SignalRepository(session).upsert(naive)

    async def test_entry_time_comes_back_in_utc(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        entry = datetime(2026, 11, 1, 12, 5, tzinfo=UTC)
        signal = make_signal(group.id, entry_time=entry)
        async with session_factory.begin() as session:
            await SignalRepository(session).upsert(signal)
        async with session_factory() as session:
            stored = await SignalRepository(session).get(signal.id)
        assert stored is not None and stored.entry_time == entry
        assert stored.entry_time.tzinfo is not None


class TestChainsAndTrades:
    async def test_chain_upsert_and_get(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
        advanced = replace(
            chain, step=1, consecutive_losses=1, updated_at=NOW + timedelta(minutes=1)
        )
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(advanced)
        async with session_factory() as session:
            assert await ChainRepository(session).get(chain.id) == advanced

    async def test_chain_keeps_its_settings_snapshot(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id, multipliers=(Decimal("2.5"), Decimal("4.25")), max_steps=2)
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
        async with session_factory() as session:
            stored = await ChainRepository(session).get(chain.id)
        assert stored is not None and stored.multipliers == (Decimal("2.5"), Decimal("4.25"))

    async def test_list_open_returns_only_pending_and_open(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chains = {
            status: make_chain(group.id, status=status, asset=f"A_{status}")
            for status in ChainStatus
        }
        async with session_factory.begin() as session:
            for chain in chains.values():
                await ChainRepository(session).upsert(chain)
        async with session_factory() as session:
            open_ids = {c.id for c in await ChainRepository(session).list_open()}
        assert open_ids == {chains[ChainStatus.PENDING].id, chains[ChainStatus.OPEN].id}

    async def test_chain_list_filters(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        demo = make_chain(group.id)
        real = make_chain(group.id, account_type=AccountType.REAL, status=ChainStatus.COMPLETED)
        async with session_factory.begin() as session:
            for chain in (demo, real):
                await ChainRepository(session).upsert(chain)
        async with session_factory() as session:
            repo = ChainRepository(session)
            assert [c.id for c in await repo.list(account_type=AccountType.REAL)] == [real.id]
            assert [c.id for c in await repo.list(status=ChainStatus.OPEN)] == [demo.id]

    async def test_trade_roundtrip_with_latency_timestamps(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        trade = make_trade(
            chain.id,
            group.id,
            stake=Decimal("2.50"),
            payout_pct=87,
            broker_order_id="abc-123",
            opened_at=NOW,
            expires_at=NOW + timedelta(seconds=60),
            t_msg_received_ns=1_000,
            t_parsed_ns=1_200,
            t_decided_ns=1_300,
            t_order_sent_ns=1_400,
            t_order_acked_ns=9_000_000_000_000,
        )
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
            await TradeRepository(session).upsert(trade)
        async with session_factory() as session:
            assert await TradeRepository(session).get(trade.id) == trade

    async def test_settling_a_trade_updates_the_same_row(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        trade = make_trade(chain.id, group.id)
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
            await TradeRepository(session).upsert(trade)
        settled = replace(
            trade,
            status=TradeStatus.WON,
            profit=Decimal("0.87"),
            settled_at=NOW + timedelta(seconds=61),
        )
        async with session_factory.begin() as session:
            await TradeRepository(session).upsert(settled)
        async with session_factory() as session:
            repo = TradeRepository(session)
            assert await repo.get(trade.id) == settled
            assert len(await repo.list()) == 1

    async def test_trades_of_a_chain_come_back_in_step_order(
        self, session_factory: Factory
    ) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        steps = [
            make_trade(chain.id, group.id, step=2, direction=Direction.CALL),
            make_trade(chain.id, group.id, step=0),
            make_trade(chain.id, group.id, step=1, direction=Direction.PUT),
        ]
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
            for trade in steps:
                await TradeRepository(session).upsert(trade)
        async with session_factory() as session:
            stored = await TradeRepository(session).list_for_chain(chain.id)
        assert [t.step for t in stored] == [0, 1, 2]

    async def test_list_unsettled_returns_only_pending_and_open(
        self, session_factory: Factory
    ) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        trades = {status: make_trade(chain.id, group.id, status=status) for status in TradeStatus}
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
            for trade in trades.values():
                await TradeRepository(session).upsert(trade)
        async with session_factory() as session:
            unsettled = {t.id for t in await TradeRepository(session).list_unsettled()}
        assert unsettled == {trades[TradeStatus.PENDING].id, trades[TradeStatus.OPEN].id}

    async def test_trade_list_filters_by_account_and_status(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        demo_win = make_trade(chain.id, group.id, status=TradeStatus.WON)
        real_loss = make_trade(
            chain.id, group.id, status=TradeStatus.LOST, account_type=AccountType.REAL
        )
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
            for trade in (demo_win, real_loss):
                await TradeRepository(session).upsert(trade)
        async with session_factory() as session:
            repo = TradeRepository(session)
            assert [t.id for t in await repo.list(account_type=AccountType.REAL)] == [real_loss.id]
            assert [t.id for t in await repo.list(status=TradeStatus.WON)] == [demo_win.id]
            both = {t.id for t in await repo.list(group_id=group.id)}
            assert both == {demo_win.id, real_loss.id}
            assert await repo.list(group_id=group.id + 1) == []

    async def test_a_stake_with_three_decimals_is_refused(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        assert group.id is not None
        chain = make_chain(group.id)
        async with session_factory.begin() as session:
            await ChainRepository(session).upsert(chain)
        with pytest.raises(StatementError, match="2 decimal places"):
            async with session_factory.begin() as session:
                await TradeRepository(session).upsert(
                    make_trade(chain.id, group.id, stake=Decimal("3.375"))
                )


class TestSystemTables:
    async def test_risk_events_roundtrip_newest_first(self, session_factory: Factory) -> None:
        group = await add_group(session_factory)
        first = make_risk_event(details={"limit": 10, "stake": 50.5, "scope": "group"})
        second = make_risk_event(
            occurred_at=NOW + timedelta(minutes=5), group_id=group.id, kind="daily_stop_loss"
        )
        async with session_factory.begin() as session:
            for event in (first, second):
                await RiskEventRepository(session).add(event)
        async with session_factory() as session:
            stored = await RiskEventRepository(session).list_recent()
        assert stored == [second, first]

    async def test_balance_latest_is_per_account_type(self, session_factory: Factory) -> None:
        demo_old = make_balance(balance=Decimal("100.00"))
        demo_new = make_balance(taken_at=NOW + timedelta(minutes=1), balance=Decimal("95.50"))
        real = make_balance(account_type=AccountType.REAL, balance=Decimal("20.00"))
        async with session_factory.begin() as session:
            for snapshot in (demo_old, demo_new, real):
                await BalanceSnapshotRepository(session).add(snapshot)
        async with session_factory() as session:
            repo = BalanceSnapshotRepository(session)
            assert await repo.latest(AccountType.DEMO) == demo_new
            assert await repo.latest(AccountType.REAL) == real
            assert [s.id for s in await repo.list_recent(AccountType.DEMO)] == [
                demo_new.id,
                demo_old.id,
            ]

    async def test_balance_latest_is_none_when_empty(self, session_factory: Factory) -> None:
        async with session_factory() as session:
            assert await BalanceSnapshotRepository(session).latest(AccountType.REAL) is None

    async def test_app_settings_set_get_update_delete(self, session_factory: Factory) -> None:
        async with session_factory.begin() as session:
            repo = AppSettingsRepository(session)
            await repo.set("account_type", "demo", now=NOW)
            await repo.set("kill_switch", False, now=NOW)
        later = NOW + timedelta(minutes=1)
        async with session_factory.begin() as session:
            await AppSettingsRepository(session).set("kill_switch", True, now=later)
        async with session_factory() as session:
            repo = AppSettingsRepository(session)
            switch = await repo.get("kill_switch")
            assert switch is not None and switch.value is True and switch.updated_at == later
            account = await repo.get("account_type")
            assert account is not None and account.value == "demo"
            assert [s.key for s in await repo.all()] == ["account_type", "kill_switch"]
        async with session_factory.begin() as session:
            assert await AppSettingsRepository(session).delete("kill_switch") is True
            assert await AppSettingsRepository(session).delete("kill_switch") is False
            assert await AppSettingsRepository(session).get("kill_switch") is None

    async def test_unknown_id_helpers(self, session_factory: Factory) -> None:
        async with session_factory() as session:
            assert await SignalRepository(session).get(new_id()) is None
            assert await ChainRepository(session).get(new_id()) is None
            assert await TradeRepository(session).get(new_id()) is None
