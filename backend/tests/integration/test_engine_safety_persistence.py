"""The safety state must survive a restart: a kill switch that forgets itself is no kill switch."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.recovery import load_recovery_state
from app.db.repositories import AppSettingsRepository, GroupRepository, RiskEventRepository
from app.db.writer import DBWriter
from app.domain.enums import AccountType, AssetSuffixMode, SignalStatus, Strategy
from app.engine.risk import GroupRiskLimits, RiskLimits
from app.quotex.base import TradeOutcome
from tests.engine_support import EngineRig, GroupSpec, make_rig
from tests.factories import make_group, make_settings
from tests.signal_support import ManualClock

Factory = async_sessionmaker[AsyncSession]
D = Decimal
PLAIN = GroupSpec(1, -1001, Strategy.NO_MARTINGALE, "1.00")
OTHER = GroupSpec(2, -1002, Strategy.NO_MARTINGALE, "1.00")


async def store_groups(session_factory: Factory, *specs: GroupSpec) -> None:
    async with session_factory.begin() as session:
        repo = GroupRepository(session)
        for spec in specs:
            group = await repo.add(
                make_group(telegram_chat_id=spec.chat_id, title=f"group {spec.group_id}")
            )
            assert group.id == spec.group_id
            await repo.save_settings(
                make_settings(
                    group.id,
                    strategy=spec.strategy,
                    base_stake=D(spec.base),
                    max_steps=0,
                    multipliers=(),
                    asset_suffix_mode=AssetSuffixMode.NONE,
                    timezone="UTC",
                )
            )


async def boot(session_factory: Factory, clock: ManualClock) -> tuple[EngineRig, DBWriter]:
    """A fresh engine loaded from the database, as after a restart."""
    rig = make_rig(clock=clock)
    writer = DBWriter(rig.bus, session_factory, rig.tasks)
    writer.start()
    rig.engine.load(await load_recovery_state(session_factory, now=clock.now()))
    await rig.start()
    return rig, writer


async def test_the_kill_switch_pauses_and_limits_come_back_after_a_restart(
    session_factory: Factory,
) -> None:
    await store_groups(session_factory, PLAIN, OTHER)
    clock = ManualClock()
    first, writer = await boot(session_factory, clock)
    limits = RiskLimits(max_stake=D("5.00"), daily_stop_loss=D("20"), max_concurrent_trades=3)
    first.engine.guard.set_limits(limits)
    first.engine.guard.set_group_limits(1, GroupRiskLimits(daily_stop_loss=D("4")))
    first.engine.manager.pause_group(2)
    first.engine.manager.engage_kill_switch()
    await first.stop(writer)

    async with session_factory() as session:
        keys = {s.key for s in await AppSettingsRepository(session).all()}
    assert keys == {
        "risk.limits",
        "risk.group.1",
        "controls.paused_groups",
        "controls.kill_switch",
    }

    second, writer = await boot(session_factory, clock)
    guard = second.engine.guard
    assert guard.limits == limits
    assert guard.group_limits(1) == GroupRiskLimits(daily_stop_loss=D("4"))
    assert guard.paused_groups == {2}
    assert guard.kill_switch is True

    second.signal(PLAIN.chat_id, "EURUSD CALL 1m")  # the switch is still on after the restart
    await second.until(lambda: any(r.status is SignalStatus.IGNORED for r in second.inbox()))
    assert second.adapter.orders == []

    second.engine.manager.release_kill_switch()
    await second.stop(writer)
    third, writer = await boot(session_factory, clock)
    assert third.engine.guard.kill_switch is False  # releasing it is remembered too
    assert third.engine.guard.paused_groups == {2}
    await third.stop(writer)


async def test_the_days_losses_still_count_after_a_restart(session_factory: Factory) -> None:
    await store_groups(session_factory, PLAIN)
    clock = ManualClock()
    first, writer = await boot(session_factory, clock)
    first.engine.guard.set_limits(RiskLimits(daily_stop_loss=D("2.00")))
    first.adapter.script_results(TradeOutcome.LOST, TradeOutcome.LOST)
    for asset in ("EURUSD", "GBPUSD"):
        first.signal(PLAIN.chat_id, f"{asset} CALL 1m")
        await first.idle()
    await first.stop(writer)

    clock.advance(3600)  # the application was down for an hour, the same day
    second, writer = await boot(session_factory, clock)
    assert second.engine.guard.day_pnl(AccountType.DEMO) == D("-2.00")
    second.signal(PLAIN.chat_id, "USDJPY CALL 1m")
    await second.idle()
    assert second.adapter.orders == []  # the stop-loss still holds
    await second.stop(writer)

    clock.advance(14 * 3600)  # past midnight UTC: a new day
    third, writer = await boot(session_factory, clock)
    assert third.engine.guard.day_pnl(AccountType.DEMO) == D("0")
    third.signal(PLAIN.chat_id, "AUDUSD CALL 1m")
    await third.idle()
    assert [o.asset for o in third.adapter.orders] == ["AUDUSD"]
    await third.stop(writer)


async def test_blocked_orders_are_stored_as_risk_events(session_factory: Factory) -> None:
    await store_groups(session_factory, PLAIN)
    rig, writer = await boot(session_factory, ManualClock())
    rig.engine.guard.set_limits(RiskLimits(max_stake=D("0.50")))
    rig.signal(PLAIN.chat_id, "EURUSD CALL 1m")
    await rig.idle()
    await rig.stop(writer)

    async with session_factory() as session:
        [event] = await RiskEventRepository(session).list_recent()
    assert event.kind == "max_stake" and event.group_id == 1
    assert event.message.startswith("order not sent:")
    assert event.details is not None and event.details["stake"] == "1.00"
    assert writer.stats.failed == 0
