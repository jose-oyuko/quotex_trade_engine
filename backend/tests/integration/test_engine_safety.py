"""Phase 5 through a running engine: limits that end chains, the kill switch, the controls."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.domain.enums import AccountType, ChainStatus, SignalStatus, Strategy, TradeStatus
from app.domain.ids import new_id
from app.engine.errors import AccountSwitchRefusedError, UnknownChainError
from app.engine.risk import GroupRiskLimits, RiskLimits
from app.events.types import RiskTripped
from app.quotex.base import TradeOutcome
from app.quotex.errors import RealAccountNotAllowedError
from tests.engine_support import EngineRig, GroupSpec, make_rig
from tests.signal_support import ManualClock

D = Decimal
LOST, WON = TradeOutcome.LOST, TradeOutcome.WON
G1, G2, G3 = -1001, -1002, -1003

FLIP = GroupSpec(1, G1, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0", "3.0"))
MARTINGALE = GroupSpec(2, G2, Strategy.MARTINGALE, "2.00", ("2", "2"))
PLAIN = GroupSpec(3, G3, Strategy.NO_MARTINGALE, "1.00")


def risk_kinds(rig: EngineRig) -> list[str]:
    return [e.risk_event.kind for e in rig.risk_events()]


def last_chain(rig: EngineRig, asset: str):  # type: ignore[no-untyped-def]
    return rig.chains()[asset]


# --- the kill switch ---


async def test_the_kill_switch_stops_a_follow_up_that_was_waiting_for_a_loss() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.engine.manager.engage_kill_switch()
    rig.settle_last("EURUSD")  # the loss arrives: the follow-up would go out now
    await rig.idle()

    assert len(rig.adapter.orders) == 1  # nothing was sent after the switch
    chain = last_chain(rig, "EURUSD")
    assert chain.status is ChainStatus.STOPPED
    assert chain.end_reason is not None and "kill_switch" in chain.end_reason
    assert rig.statuses("EURUSD") == [TradeStatus.LOST, TradeStatus.FAILED]
    assert risk_kinds(rig) == ["kill_switch"]
    await rig.stop()


async def test_no_order_goes_out_after_the_kill_switch_even_with_many_follow_ups_queued() -> None:
    rig = make_rig(hold_results=True)
    for spec in (FLIP, MARTINGALE):
        rig.add_group(spec)
    await rig.start()
    rig.adapter.script_results(LOST, LOST, LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    rig.signal(G2, "GBPUSD PUT 1m")
    rig.signal(G2, "AUDUSD CALL 1m")  # a second chain in the martingale group
    await rig.until(lambda: len(rig.adapter.orders) == 3)

    rig.engine.manager.engage_kill_switch()
    rig.adapter.settle_all()  # three losses at once: three follow-ups want to go out
    await rig.idle()

    assert len(rig.adapter.orders) == 3
    assert {c.status for c in rig.chains().values()} == {ChainStatus.STOPPED}
    assert risk_kinds(rig) == ["kill_switch"] * 3
    assert rig.engine.manager.active_chains() == []
    await rig.stop()


async def test_new_signals_are_ignored_while_the_kill_switch_is_engaged_and_say_so() -> None:
    rig = make_rig()
    rig.add_group(PLAIN)
    await rig.start()
    rig.engine.manager.engage_kill_switch()
    rig.signal(G3, "EURUSD CALL 1m")
    await rig.until(lambda: any(r.status is SignalStatus.IGNORED for r in rig.inbox()))
    assert rig.adapter.orders == []
    reason = next(r.reason for r in rig.inbox() if r.status is SignalStatus.IGNORED)
    assert reason is not None and "kill switch" in reason

    rig.engine.manager.release_kill_switch()
    rig.signal(G3, "GBPUSD CALL 1m")
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["GBPUSD"]
    await rig.stop()


async def test_the_kill_switch_can_stop_the_running_chains_at_once() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.engine.manager.engage_kill_switch(stop_chains=True)
    assert rig.engine.manager.active_chains() == []  # gone immediately, not at the next order
    assert last_chain(rig, "EURUSD").status is ChainStatus.STOPPED

    rig.settle_last("EURUSD")
    await rig.idle()
    assert rig.statuses("EURUSD") == [TradeStatus.LOST]  # the open trade is still recorded
    assert len(rig.adapter.orders) == 1
    await rig.stop()


# --- the owner's other controls ---


async def test_pausing_a_group_ignores_new_signals_but_lets_running_chains_finish() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(MARTINGALE)
    await rig.start()
    rig.adapter.script_results(LOST, WON)
    rig.signal(G2, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.engine.manager.pause_group(2)
    rig.signal(G2, "GBPUSD CALL 1m")
    await rig.until(lambda: any(r.status is SignalStatus.IGNORED for r in rig.inbox()))
    assert [r.reason for r in rig.inbox() if r.status is SignalStatus.IGNORED] == [
        "group is paused"
    ]

    rig.settle_last("EURUSD")  # the running chain still gets its follow-up
    await rig.until(lambda: len(rig.orders("EURUSD")) == 2)
    rig.settle_last("EURUSD")
    await rig.idle()
    assert rig.chains()["EURUSD"].status is ChainStatus.COMPLETED
    assert rig.orders("GBPUSD") == []

    rig.engine.manager.resume_group(2)
    rig.signal(G2, "NZDUSD CALL 1m")
    await rig.until(lambda: len(rig.orders("NZDUSD")) == 1)
    rig.adapter.settle_all()
    await rig.idle()
    await rig.stop()


async def test_stop_after_current_ends_the_chain_when_the_open_trade_loses() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    [chain] = rig.engine.manager.active_chains()
    rig.engine.manager.stop_after_current(chain.id)
    assert chain.active  # nothing happens until the trade settles
    rig.settle_last("EURUSD")
    await rig.idle()

    record = last_chain(rig, "EURUSD")
    assert (record.status, record.step, record.consecutive_losses) == (ChainStatus.STOPPED, 0, 1)
    assert record.end_reason == "stopped after trade 0 as requested"
    assert len(rig.adapter.orders) == 1
    assert rig.statuses("EURUSD") == [TradeStatus.LOST]
    await rig.stop()


async def test_stop_after_current_does_not_change_a_win() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    [chain] = rig.engine.manager.active_chains()
    rig.engine.manager.stop_after_current(chain.id)
    rig.settle_last("EURUSD")
    await rig.idle()
    assert last_chain(rig, "EURUSD").status is ChainStatus.COMPLETED
    await rig.stop()


async def test_ending_a_chain_frees_the_group_now_and_the_open_trade_is_still_recorded() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST, WON)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    [chain] = rig.engine.manager.active_chains()

    rig.engine.manager.end_chain(chain.id)
    assert last_chain(rig, "EURUSD").status is ChainStatus.STOPPED
    rig.signal(G1, "GBPUSD PUT 1m")  # the flip group accepts a signal again straight away
    await rig.until(lambda: len(rig.orders("GBPUSD")) == 1)

    rig.settle_last("EURUSD")  # the first chain's trade loses: no follow-up must follow
    await rig.until(lambda: rig.statuses("EURUSD") == [TradeStatus.LOST])
    for _ in range(20):  # give a wrongly-placed follow-up every chance to appear
        await asyncio.sleep(0)
    assert len(rig.orders("EURUSD")) == 1
    rig.settle_last("GBPUSD")
    await rig.idle()
    await rig.stop()


async def test_controls_on_a_chain_that_is_not_running_are_a_clear_error() -> None:
    rig = make_rig()
    rig.add_group(PLAIN)
    await rig.start()
    with pytest.raises(UnknownChainError):
        rig.engine.manager.stop_after_current(new_id())
    with pytest.raises(UnknownChainError):
        rig.engine.manager.end_chain(new_id())
    await rig.stop()


# --- limits through a running chain ---


async def test_a_follow_up_above_the_max_stake_is_blocked_and_the_chain_ends_failed() -> None:
    rig = make_rig(hold_results=True, limits=RiskLimits(max_stake=D("2.50")))
    rig.add_group(FLIP)  # stakes 1.00, 2.00, 3.00
    await rig.start()
    rig.adapter.script_results(LOST, LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    rig.settle_last("EURUSD")
    await rig.until(lambda: len(rig.adapter.orders) == 2)  # 2.00 is under the limit
    rig.settle_last("EURUSD")
    await rig.idle()  # 3.00 is over it

    assert [o.amount for o in rig.adapter.orders] == [D("1.00"), D("2.00")]
    chain = last_chain(rig, "EURUSD")
    assert chain.status is ChainStatus.FAILED
    assert chain.end_reason is not None and "max_stake" in chain.end_reason
    assert rig.statuses("EURUSD") == [TradeStatus.LOST, TradeStatus.LOST, TradeStatus.FAILED]
    [event] = rig.risk_events()
    assert event.risk_event.kind == "max_stake" and event.risk_event.group_id == 1
    assert "3.00" in event.risk_event.message
    await rig.stop()


async def test_the_max_concurrent_trades_blocks_the_next_chain_until_one_settles() -> None:
    rig = make_rig(hold_results=True, limits=RiskLimits(max_concurrent_trades=2))
    for spec in (FLIP, MARTINGALE, PLAIN):
        rig.add_group(spec)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    rig.signal(G2, "GBPUSD CALL 1m")
    rig.signal(G3, "USDJPY CALL 1m")  # the third at once
    await rig.until(lambda: len(rig.adapter.orders) == 2)
    await rig.until(lambda: "max_concurrent_trades" in risk_kinds(rig))
    assert rig.orders("USDJPY") == []
    assert last_chain(rig, "USDJPY").status is ChainStatus.FAILED

    rig.settle_last("EURUSD")
    await rig.until(lambda: rig.engine.guard.open_trades == 1)
    rig.signal(G3, "AUDUSD CALL 1m")
    await rig.until(lambda: len(rig.orders("AUDUSD")) == 1)
    rig.adapter.settle_all()
    await rig.idle()
    await rig.stop()


async def test_the_exposure_cap_counts_open_stakes() -> None:
    rig = make_rig(hold_results=True, limits=RiskLimits(max_exposure=D("2.50")))
    rig.add_group(FLIP)
    rig.add_group(PLAIN)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")  # 1.00 open
    rig.signal(G3, "USDJPY CALL 1m")  # + 1.00 = 2.00, fine
    rig.signal(G3, "GBPUSD CALL 1m")  # + 1.00 = 3.00 > 2.50
    await rig.until(lambda: "max_exposure" in risk_kinds(rig))
    assert len(rig.adapter.orders) == 2
    assert rig.engine.guard.open_exposure == D("2.00")
    rig.adapter.settle_all()
    await rig.idle()
    assert rig.engine.guard.open_exposure == D("0")
    await rig.stop()


async def test_a_payout_below_the_groups_minimum_skips_the_signal() -> None:
    rig = make_rig()  # every asset pays 80 %
    rig.add_group(GroupSpec(3, G3, Strategy.NO_MARTINGALE, "1.00", (), min_payout_pct=81))
    await rig.start()
    rig.signal(G3, "EURUSD CALL 1m")
    await rig.idle()
    assert rig.adapter.orders == []
    assert risk_kinds(rig) == ["min_payout"]
    assert last_chain(rig, "EURUSD").status is ChainStatus.FAILED

    rig.add_group(GroupSpec(3, G3, Strategy.NO_MARTINGALE, "1.00", (), min_payout_pct=80))
    rig.signal(G3, "GBPUSD CALL 1m")
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["GBPUSD"]  # at the minimum is fine
    await rig.stop()


async def test_a_chain_cannot_be_longer_than_the_global_limit() -> None:
    rig = make_rig(limits=RiskLimits(max_chain_trades=2))
    rig.add_group(FLIP)  # would allow 3 trades
    await rig.start()
    rig.adapter.script_results(LOST, LOST, LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()
    assert len(rig.adapter.orders) == 2
    assert risk_kinds(rig) == ["max_chain_length"]
    await rig.stop()


async def test_the_daily_stop_loss_ends_trading_for_the_day_and_resets_after_midnight() -> None:
    clock = ManualClock()  # 2026-11-01 10:00 UTC; the day resets at 00:00 UTC
    rig = make_rig(clock=clock, limits=RiskLimits(daily_stop_loss=D("2.00")))
    rig.add_group(PLAIN)
    await rig.start()
    rig.adapter.script_results(LOST, LOST, LOST)
    for asset in ("EURUSD", "GBPUSD"):
        rig.signal(G3, f"{asset} CALL 1m")
        await rig.idle()
    assert len(rig.adapter.orders) == 2 and rig.engine.guard.day_pnl(AccountType.DEMO) == D("-2.00")

    rig.signal(G3, "USDJPY CALL 1m")  # the stop-loss has been reached
    await rig.idle()
    assert len(rig.adapter.orders) == 2
    assert risk_kinds(rig) == ["daily_stop_loss"]

    clock.advance(14 * 3600)  # 00:00 UTC the next day
    rig.signal(G3, "AUDUSD CALL 1m")
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["EURUSD", "GBPUSD", "AUDUSD"]
    await rig.stop()


async def test_a_group_stop_loss_leaves_the_other_groups_trading() -> None:
    rig = make_rig()
    rig.add_group(PLAIN)
    rig.add_group(MARTINGALE)
    rig.engine.guard.set_group_limits(3, GroupRiskLimits(daily_stop_loss=D("1.00")))
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G3, "EURUSD CALL 1m")
    await rig.idle()
    rig.signal(G3, "GBPUSD CALL 1m")
    rig.signal(G2, "USDJPY CALL 1m")
    await rig.idle()
    assert sorted(o.asset for o in rig.adapter.orders) == ["EURUSD", "USDJPY"]
    assert risk_kinds(rig) == ["group_daily_stop_loss"]
    await rig.stop()


async def test_every_blocked_order_is_a_stored_risk_event_naming_the_group() -> None:
    rig = make_rig(limits=RiskLimits(max_stake=D("0.50")))
    rig.add_group(PLAIN)
    await rig.start()
    rig.signal(G3, "EURUSD CALL 1m")
    await rig.idle()
    [event] = [e for e in rig.collect() if isinstance(e, RiskTripped)]
    assert event.name == "risk.tripped" and event.risk_event.group_id == 3
    assert event.risk_event.details is not None and event.risk_event.details["asset"] == "EURUSD"
    await rig.stop()


# --- the account guard ---


async def test_the_account_cannot_be_switched_while_a_chain_is_running() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    with pytest.raises(AccountSwitchRefusedError, match="1 chain"):
        await rig.engine.switch_account(AccountType.DEMO)
    rig.adapter.settle_all()
    await rig.idle()
    await rig.engine.switch_account(AccountType.DEMO)  # nothing running now
    await rig.stop()


async def test_the_account_cannot_be_switched_while_a_trade_of_an_ended_chain_is_open() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    [chain] = rig.engine.manager.active_chains()
    rig.engine.manager.end_chain(chain.id)
    with pytest.raises(AccountSwitchRefusedError, match="1 trade"):
        await rig.engine.switch_account(AccountType.DEMO)
    rig.adapter.settle_all()
    await rig.until(lambda: rig.engine.guard.open_trades == 0)
    await rig.stop()


async def test_real_money_needs_the_explicit_setting() -> None:
    rig = make_rig()  # the fake adapter was built without allow_real
    await rig.start()
    with pytest.raises(RealAccountNotAllowedError):
        await rig.engine.switch_account(AccountType.REAL)
    assert rig.adapter.account_type is AccountType.DEMO
    await rig.stop()
