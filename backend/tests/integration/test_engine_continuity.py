"""A chain carries on through a lost connection, and on Deriv through a restart, as long as no
trade time was missed (decisions D-78, D-79). Its next step is due when its open trade expires: back
before that, the chain simply continues; back after it, the trade still gets its real result but the
step is missed and the chain ends. Fake brokers and a clock that moves only when told."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

from app.brokers.base import TradeOutcome
from app.db.recovery import RecoveryState
from app.domain.enums import (
    AccountType,
    Broker,
    ChainStatus,
    Direction,
    Strategy,
    TradeStatus,
)
from app.domain.records import ChainRecord, TradeRecord
from app.engine.manager import LOOKUP_NOTE, RESTART_REASON
from app.events.types import TradeSettled
from tests.engine_support import EngineRig, GroupSpec, make_rig
from tests.factories import make_chain, make_group, make_settings, make_trade
from tests.signal_support import ManualClock

D = Decimal
WON, LOST = TradeOutcome.WON, TradeOutcome.LOST
DV_GROUP, DV_CHAT = 2, -1002
QX_GROUP, QX_CHAT = 1, -1001
FIFTEEN_MIN = 900


def deriv_rig() -> tuple[EngineRig, ManualClock]:
    clock = ManualClock()
    rig = make_rig(clock=clock, with_deriv=True, hold_results=True)
    rig.add_group(GroupSpec(QX_GROUP, QX_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",)))
    rig.add_group(
        GroupSpec(DV_GROUP, DV_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",), broker=Broker.DERIV)
    )
    return rig, clock


def deriv_of(rig: EngineRig):  # type: ignore[no-untyped-def]
    assert rig.deriv is not None
    return rig.deriv


# --- a lost connection while the engine runs ---


async def test_back_before_the_trade_expires_the_chain_simply_continues() -> None:
    rig, clock = deriv_rig()
    await rig.start()
    fake = deriv_of(rig)
    fake.script_results(LOST, WON)
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(fake.orders) == 1)

    fake.simulate_connection_loss()
    clock.advance(120)  # two minutes away, well before the 15-minute trade expires
    fake.simulate_connection_restored()
    clock.advance(FIFTEEN_MIN - 120)
    fake.settle_all()

    await rig.until(lambda: len(fake.orders) == 2)  # the martingale step went out
    assert [o.amount for o in fake.orders] == [D("1.00"), D("2.00")]
    fake.settle_all()
    await rig.idle()
    assert rig.chains()["GBPUSD"].status is ChainStatus.COMPLETED
    await rig.stop()


async def test_back_after_the_trade_expired_the_step_is_missed_and_the_chain_ends() -> None:
    rig, clock = deriv_rig()
    await rig.start()
    fake = deriv_of(rig)
    fake.script_results(LOST)
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(fake.orders) == 1)

    fake.simulate_connection_loss()
    clock.advance(FIFTEEN_MIN + 17 * 60)  # back 17 minutes after the trade expired
    fake.simulate_connection_restored()
    fake.settle_all()
    await rig.idle()

    assert len(fake.orders) == 1  # nothing was sent late
    [trade] = rig.trades("GBPUSD")
    assert (trade.status, trade.profit) == (TradeStatus.LOST, D("-1.00"))  # its real result
    chain = rig.chains()["GBPUSD"]
    assert chain.status is ChainStatus.FAILED
    assert chain.end_reason is not None and chain.end_reason.startswith("missed: step 1 was due")
    assert "while the connection to Deriv was down" in chain.end_reason
    await rig.stop()


async def test_a_result_that_arrives_while_the_broker_is_down_misses_the_step() -> None:
    rig, _ = deriv_rig()
    await rig.start()
    fake = deriv_of(rig)
    fake.script_results(LOST)
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(fake.orders) == 1)

    fake.simulate_connection_loss()
    fake.settle_all()
    await rig.idle()

    assert len(fake.orders) == 1
    chain = rig.chains()["GBPUSD"]
    assert chain.status is ChainStatus.FAILED and (chain.end_reason or "").startswith("missed")
    await rig.stop()


async def test_a_win_needs_no_next_step_so_nothing_is_missed() -> None:
    rig, clock = deriv_rig()
    await rig.start()
    fake = deriv_of(rig)
    fake.script_results(WON)
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(fake.orders) == 1)
    fake.simulate_connection_loss()
    clock.advance(FIFTEEN_MIN + 60)
    fake.simulate_connection_restored()
    fake.settle_all()
    await rig.idle()
    assert rig.chains()["GBPUSD"].status is ChainStatus.COMPLETED
    await rig.stop()


async def test_the_same_rule_holds_for_quotex_while_the_engine_runs() -> None:
    rig, clock = deriv_rig()
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(QX_CHAT, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    rig.adapter.simulate_connection_loss()
    clock.advance(5 * 60)
    rig.adapter.simulate_connection_restored()
    rig.adapter.settle_all()
    await rig.idle()
    assert len(rig.adapter.orders) == 1
    assert (rig.chains()["EURUSD"].end_reason or "").startswith("missed")
    await rig.stop()


# --- a restart (Deriv) ---


def open_deriv_chain(
    clock: ManualClock, *, placed_ago_s: int, step: int = 0, stake: str = "1.00"
) -> tuple[ChainRecord, TradeRecord]:
    placed = clock.now() - timedelta(seconds=placed_ago_s)
    chain = make_chain(
        DV_GROUP,
        asset="GBPUSD",
        origin_direction=Direction.PUT,
        duration_s=FIFTEEN_MIN,
        strategy=Strategy.MARTINGALE,
        status=ChainStatus.OPEN,
        step=step,
        consecutive_losses=step,
        max_steps=1,
        multipliers=(D("2.0"),),
        broker=Broker.DERIV,
        created_at=placed,
        updated_at=placed,
    )
    trade = make_trade(
        chain.id,
        DV_GROUP,
        asset="GBPUSD",
        direction=Direction.PUT,
        duration_s=FIFTEEN_MIN,
        stake=D(stake),
        step=step,
        status=TradeStatus.OPEN,
        broker=Broker.DERIV,
        broker_order_id="5551",
        created_at=placed,
        opened_at=placed,
        expires_at=placed + timedelta(seconds=FIFTEEN_MIN),
    )
    return chain, trade


def recovery(
    chains: list[ChainRecord],
    trades: list[TradeRecord],
    *,
    unknown: list[TradeRecord] | None = None,
) -> RecoveryState:
    group = make_group(id=DV_GROUP, telegram_chat_id=DV_CHAT, broker=Broker.DERIV)
    settings = make_settings(
        DV_GROUP,
        strategy=Strategy.MARTINGALE,
        base_stake=D("1.00"),
        max_steps=1,
        multipliers=(D("2.0"),),
        timezone="UTC",
    )
    return RecoveryState(
        groups=[group],
        group_settings=[settings],
        open_chains=chains,
        unsettled_trades=trades,
        unknown_trades=unknown or [],
    )


def settled(rig: EngineRig, trade_id: object) -> TradeRecord | None:
    found = [
        e.trade for e in rig.collect() if isinstance(e, TradeSettled) and e.trade.id == trade_id
    ]
    return found[-1] if found else None


async def test_a_restart_before_the_open_trade_expires_carries_the_chain_on() -> None:
    rig, clock = deriv_rig()
    chain, trade = open_deriv_chain(clock, placed_ago_s=300)  # 10 minutes left
    fake = deriv_of(rig)
    fake.adopt_order(
        "5551",
        asset="GBPUSD",
        direction=Direction.PUT,
        duration_s=FIFTEEN_MIN,
        amount=D("1.00"),
        outcome=LOST,
        settled=False,
    )
    await rig.start()  # Deriv connects: ten minutes before the trade expires
    summary = rig.engine.load(recovery([chain], [trade]))
    assert (summary.chains_resumed, summary.chains_marked_unknown) == (1, 0)
    assert rig.engine.manager.active_chains(DV_GROUP)[0].id == chain.id
    assert rig.engine.guard.open_trades_of(Broker.DERIV) == 1  # its stake is counted again
    fake.script_results(WON)
    clock.advance(600)
    fake.settle("5551")
    await rig.until(lambda: len(fake.orders) == 1)  # the step after the loss went out
    assert (fake.orders[0].amount, fake.orders[0].direction) == (D("2.00"), Direction.PUT)
    fake.settle_all()
    await rig.idle()
    assert settled(rig, trade.id).status is TradeStatus.LOST  # type: ignore[union-attr]
    assert rig.chains()["GBPUSD"].status is ChainStatus.COMPLETED
    await rig.stop()


async def test_a_restart_after_the_open_trade_expired_reads_its_result_and_ends_the_chain() -> None:
    rig, clock = deriv_rig()
    chain, trade = open_deriv_chain(clock, placed_ago_s=FIFTEEN_MIN + 17 * 60)
    fake = deriv_of(rig)
    fake.adopt_order(
        "5551",
        asset="GBPUSD",
        direction=Direction.PUT,
        duration_s=FIFTEEN_MIN,
        amount=D("1.00"),
        outcome=LOST,
    )
    await rig.start()
    rig.engine.load(recovery([chain], [trade]))
    await rig.idle()

    assert fake.orders == []  # the missed step is never sent
    result = settled(rig, trade.id)
    assert result is not None
    assert (result.status, result.profit) == (TradeStatus.LOST, D("-1.00"))
    ended = rig.chains()["GBPUSD"]
    assert ended.status is ChainStatus.FAILED and (ended.end_reason or "").startswith("missed")
    assert rig.engine.guard.open_trades == 0
    await rig.stop()


async def test_trades_an_earlier_restart_left_unknown_get_their_real_result() -> None:
    rig, clock = deriv_rig()
    first_recorded = clock.now() - timedelta(hours=30)  # yesterday
    old = make_trade(
        make_chain(DV_GROUP).id,
        DV_GROUP,
        asset="R_75",
        status=TradeStatus.UNKNOWN,
        error=RESTART_REASON,
        broker=Broker.DERIV,
        broker_order_id="777",
        stake=D("35.00"),
        settled_at=first_recorded,
    )
    fake = deriv_of(rig)
    fake.adopt_order(
        "777",
        asset="R_75",
        direction=Direction.CALL,
        duration_s=60,
        amount=D("35.00"),
        outcome=WON,
    )
    await rig.start()
    summary = rig.engine.load(recovery([], [], unknown=[old]))
    assert summary.trades_looked_up == 1
    await rig.until(lambda: settled(rig, old.id) is not None)

    result = settled(rig, old.id)
    assert result is not None
    assert (result.status, result.profit) == (TradeStatus.WON, D("29.75"))
    assert result.settled_at == first_recorded  # it counts on the day it was first recorded
    assert result.error == LOOKUP_NOTE
    assert rig.engine.guard.day_pnl(AccountType.DEMO, broker=Broker.DERIV) == D(0)  # not today
    await rig.stop()


async def test_a_trade_deriv_cannot_report_stays_as_it_was() -> None:
    rig, clock = deriv_rig()
    old = make_trade(
        make_chain(DV_GROUP).id,
        DV_GROUP,
        status=TradeStatus.UNKNOWN,
        broker=Broker.DERIV,
        broker_order_id="999",  # the fake knows nothing about it
        settled_at=clock.now(),
    )
    await rig.start()
    rig.engine.load(recovery([], [], unknown=[old]))
    await rig.idle()
    for _ in range(50):
        await asyncio.sleep(0)
    assert settled(rig, old.id) is None  # nothing written: it stays `unknown`
    await rig.stop()


async def test_a_quotex_chain_still_ends_unknown_after_a_restart() -> None:
    rig, clock = deriv_rig()
    chain = make_chain(QX_GROUP, asset="EURUSD", broker=Broker.QUOTEX)
    trade = make_trade(
        chain.id,
        QX_GROUP,
        asset="EURUSD",
        broker=Broker.QUOTEX,
        broker_order_id="q-1",
        expires_at=clock.now() + timedelta(minutes=5),
    )
    state = recovery([chain], [trade])
    state.groups.append(make_group(id=QX_GROUP, telegram_chat_id=QX_CHAT))
    await rig.start()
    summary = rig.engine.load(state)
    assert (summary.chains_marked_unknown, summary.trades_marked_unknown) == (1, 1)
    assert summary.chains_resumed == 0
    await rig.stop()


async def test_a_chain_carried_on_waits_for_deriv_to_connect_first() -> None:
    rig, clock = deriv_rig()
    chain, trade = open_deriv_chain(clock, placed_ago_s=60)
    fake = deriv_of(rig)
    fake.adopt_order(
        "5551",
        asset="GBPUSD",
        direction=Direction.PUT,
        duration_s=FIFTEEN_MIN,
        amount=D("1.00"),
        outcome=LOST,
    )
    rig.engine.load(recovery([chain], [trade]))  # loaded before any broker is connected
    for _ in range(20):
        await asyncio.sleep(0)
    assert fake.orders == []  # nothing happens while Deriv is not connected
    fake.script_results(WON)
    await rig.start()  # Deriv connects: the result is read, the next step goes out
    await rig.until(lambda: len(fake.orders) == 1)
    fake.settle_all()
    await rig.idle()
    assert rig.chains()["GBPUSD"].status is ChainStatus.COMPLETED
    await rig.stop()
