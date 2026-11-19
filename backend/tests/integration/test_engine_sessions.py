"""Trading sessions (decisions D-71 to D-73): the scheduler opens a pair of opposite chains on its
schedule, one pair at a time, and stops softly. Everything runs on the fake Quotex with timers that
move only when the test says so."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from app.domain.enums import (
    AccountType,
    Broker,
    ChainStatus,
    Direction,
    RepeatKind,
    RunEndReason,
    RunState,
    SessionMode,
    SignalStatus,
    Strategy,
)
from app.engine.errors import (
    AccountSwitchRefusedError,
    NoActiveRunError,
    SessionRunActiveError,
    TelegramNotConnectedError,
)
from app.engine.risk import RiskLimits
from app.events.types import ChainStarted, SignalReceived
from app.quotex.base import TradeOutcome
from app.sessions.scheduler import SessionConfig
from tests.factories import make_session_run
from tests.session_support import SESSION_GROUP, SessionRig, make_session_rig

CALL, PUT = Direction.CALL, Direction.PUT
WON, LOST = TradeOutcome.WON, TradeOutcome.LOST
D = Decimal


def at(hour: int, minute: int = 0, second: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


async def open_first_pair(s: SessionRig) -> None:
    """Start the scheduler and run time up to the window start: the first pair is out."""
    await s.start()
    await s.timers.advance_to(at(11))
    await s.rig.until(lambda: len(s.adapter.orders) >= 2)


# --- when the first pair goes out ---


async def test_the_first_pair_goes_out_at_the_start_time_and_not_before() -> None:
    s = make_session_rig()
    await s.start()

    await s.timers.advance_to(at(10, 59, 59))
    assert s.adapter.orders == []
    # a minute before the window the asset was made ready, so the first order does not pay for it
    assert s.adapter.prepare_calls == [("EURUSD", 300)]

    await s.timers.advance_to(at(11))
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    call, put = s.adapter.orders
    assert (call.direction, put.direction) == (CALL, PUT)
    assert (call.amount, put.amount) == (1, 1)  # each leg is a base-stake first trade
    assert {t.created_at for t in s.rig.trades("EURUSD")} == {at(11)}  # exactly the start time

    run = s.run()
    assert (run.state, run.pairs_opened, run.started_by) == (RunState.RUNNING, 1, "schedule")
    await s.stop()


async def test_the_two_legs_are_chains_of_the_hidden_group_marked_with_their_run() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    chains = s.chains()
    assert len(chains) == 2
    assert {c.group_id for c in chains} == {SESSION_GROUP}
    assert {c.session_run_id for c in chains} == {s.run().id}
    assert {c.pair_no for c in chains} == {1}
    assert {c.origin_direction for c in chains} == {CALL, PUT}
    # each chain's inbox row is published first, so the database has it when the chain row comes
    events = s.rig.collect()
    for chain in chains:
        row = next(
            i
            for i, e in enumerate(events)
            if isinstance(e, SignalReceived) and e.signal.id == chain.signal_id
        )
        started = next(
            i
            for i, e in enumerate(events)
            if isinstance(e, ChainStarted) and e.chain.id == chain.id
        )
        assert row < started
        assert events[row].signal.status is SignalStatus.PARSED  # type: ignore[attr-defined]
    await s.stop()


async def test_a_window_that_is_open_when_the_scheduler_starts_is_not_started() -> None:
    s = make_session_rig(now=at(11, 30))
    await s.start()
    await s.timers.advance_to(at(13))
    assert s.adapter.orders == [] and s.runs() == []

    await s.timers.advance_to(at(11, day=2))  # the next scheduled window starts normally
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert len(s.runs()) == 1
    await s.stop()


# --- one pair at a time ---


async def test_no_new_pair_opens_while_a_pair_is_running() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    await s.timers.advance_to(at(11, 40))  # eight candles later, both chains still open
    assert len(s.adapter.orders) == 2
    assert s.run().pairs_opened == 1
    await s.stop()


async def test_after_the_pair_is_over_the_next_one_opens_at_the_next_candle() -> None:
    s = make_session_rig()
    s.adapter.script_results(WON, LOST, WON)  # CALL wins, PUT loses, the PUT chain's recovery wins
    await open_first_pair(s)
    call, put = s.adapter.orders

    s.adapter.settle(call.order_id)
    await s.timers.advance_to(at(11, 5))
    s.adapter.settle(put.order_id)  # the loser goes into recovery: a flipped trade at base x 2
    await s.rig.until(lambda: len(s.adapter.orders) == 3)
    recovery = s.adapter.orders[2]
    assert (recovery.direction, recovery.amount) == (CALL, 2)  # flipped PUT, base 1.00 x 2.0
    assert s.run().pairs_opened == 1

    await s.timers.advance_to(at(11, 10, 30))  # the recovery settles after its own candle
    s.adapter.settle(recovery.order_id)
    await s.timers.settle()
    assert len(s.adapter.orders) == 3  # 11:10:30 is mid-candle: the next pair waits
    await s.timers.advance_to(at(11, 14, 59))
    assert len(s.adapter.orders) == 3

    await s.timers.advance_to(at(11, 15))
    await s.rig.until(lambda: len(s.adapter.orders) == 5)
    assert [(o.direction, o.amount) for o in s.adapter.orders[3:]] == [(CALL, 1), (PUT, 1)]
    assert s.run().pairs_opened == 2
    await s.stop()


async def test_a_pair_that_ends_just_after_a_candle_began_counts_as_on_the_boundary() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    await s.timers.advance_to(at(11, 5, 1))  # both settle one second after the candle ended
    s.settle_orders()
    await s.rig.until(lambda: len(s.adapter.orders) == 4)  # the 11:05 pair went out at once
    assert s.run().pairs_opened == 2
    await s.stop()


async def test_the_pause_between_pairs_is_waited_after_both_chains_ended() -> None:
    s = make_session_rig(pause_s=600)
    await open_first_pair(s)

    await s.timers.advance_to(at(11, 5))
    s.settle_orders()  # both chains end at 11:05
    await s.timers.advance_to(at(11, 14, 59))
    assert len(s.adapter.orders) == 2  # ten minutes of pause, then the next candle: 11:15
    await s.timers.advance_to(at(11, 15))
    await s.rig.until(lambda: len(s.adapter.orders) == 4)
    await s.stop()


async def test_no_pair_opens_at_or_after_the_end_of_the_window() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    await s.timers.advance_to(at(11, 56))
    s.settle_orders()  # the next candle is 12:00, which is the end of the window
    await s.timers.advance_to(at(12, 10))
    assert len(s.adapter.orders) == 2
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.WINDOW_ENDED)
    await s.stop()


# --- stopping: no new pairs, the chains already running finish (D-72) ---


async def test_at_the_end_of_the_window_the_running_chains_finish_and_no_pair_follows() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    await s.timers.advance_to(at(12))
    assert s.run().state is RunState.STOPPING  # nothing new, but nothing cut off either
    assert len(s.rig.engine.manager.active_chains(SESSION_GROUP)) == 2

    s.settle_orders()
    await s.timers.settle()
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.WINDOW_ENDED)
    assert len(s.adapter.orders) == 2
    await s.stop()


async def test_the_profit_target_stops_new_pairs_but_the_losing_chain_finishes_its_recovery() -> (
    None
):
    s = make_session_rig(profit_target=D("0.80"))
    s.adapter.script_results(WON, LOST, WON)
    await open_first_pair(s)
    call, put = s.adapter.orders

    s.adapter.settle(call.order_id)  # +0.80: the target
    await s.timers.settle()
    assert (s.run().state, s.run().profit) == (RunState.STOPPING, D("0.80"))

    s.adapter.settle(put.order_id)  # lost: its recovery still goes out
    await s.rig.until(lambda: len(s.adapter.orders) == 3)
    s.adapter.settle(s.adapter.orders[2].order_id)
    await s.timers.advance_to(at(11, 30))

    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.PROFIT_TARGET)
    assert (run.pairs_opened, run.profit) == (1, D("0.80") - 1 + D("1.60"))
    assert len(s.adapter.orders) == 3  # no second pair
    await s.stop()


async def test_the_loss_limit_stops_new_pairs_and_does_not_cap_the_loss() -> None:
    s = make_session_rig(loss_limit=D("1.00"))
    s.adapter.script_results(LOST, WON, LOST, LOST)
    await open_first_pair(s)
    call, put = s.adapter.orders

    s.adapter.settle(call.order_id)  # -1.00: the limit
    await s.timers.settle()
    assert s.run().state is RunState.STOPPING

    await s.rig.until(lambda: len(s.adapter.orders) == 3)  # the CALL chain still recovers...
    s.adapter.settle(
        s.adapter.orders[2].order_id
    )  # ...and loses again: the total is past the limit
    await s.rig.until(lambda: len(s.adapter.orders) == 4)
    s.adapter.settle(s.adapter.orders[3].order_id)
    s.adapter.settle(put.order_id)
    await s.timers.advance_to(at(11, 30))

    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.LOSS_LIMIT)
    assert run.profit < -1  # more than the limit was lost: it stops new pairs, it is not a cap
    assert run.pairs_opened == 1
    await s.stop()


async def test_the_maximum_number_of_pairs_ends_the_run_once_the_last_pair_is_over() -> None:
    s = make_session_rig(max_pairs=1)
    await open_first_pair(s)
    assert s.run().state is RunState.STOPPING  # the last pair is out: nothing more will open

    s.settle_orders()
    await s.timers.settle()
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.MAX_PAIRS)
    await s.stop()


async def test_the_owner_can_stop_a_run_and_the_running_chains_finish() -> None:
    s = make_session_rig()
    s.adapter.script_results(LOST, WON, WON)
    await open_first_pair(s)

    stopped = s.scheduler.stop_run(1)
    assert stopped.state is RunState.STOPPING
    s.adapter.settle(s.adapter.orders[0].order_id)  # a loss: the chain still recovers
    await s.rig.until(lambda: len(s.adapter.orders) == 3)
    s.settle_orders()
    await s.timers.advance_to(at(11, 30))

    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.STOPPED)
    assert run.pairs_opened == 1 and len(s.adapter.orders) == 3
    await s.stop()


async def test_the_kill_switch_ends_the_run() -> None:
    s = make_session_rig()
    await open_first_pair(s)

    s.rig.engine.manager.engage_kill_switch()
    await s.timers.settle()
    assert s.run().state is RunState.STOPPING

    s.settle_orders()
    await s.timers.advance_to(at(11, 30))
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.KILL_SWITCH)
    assert len(s.adapter.orders) == 2
    await s.stop()


async def test_the_first_reason_to_stop_is_the_one_recorded() -> None:
    s = make_session_rig(max_pairs=1, profit_target=D("0.50"))
    await open_first_pair(s)  # max pairs reached as the pair opens
    s.scheduler.stop_run(1)  # a later reason changes nothing
    s.settle_orders()
    await s.timers.settle()
    assert s.run().end_reason is RunEndReason.MAX_PAIRS
    await s.stop()


# --- a round that cannot be traded is skipped, and nothing is sent ---


async def test_a_closed_asset_skips_the_round_and_the_next_candle_tries_again() -> None:
    s = make_session_rig()
    s.adapter.add_asset("EURUSD", payout=80, is_open=False)
    await s.start()

    await s.timers.advance_to(at(11))
    assert s.adapter.orders == []
    run = s.run()
    assert run.rounds_skipped == 1 and run.pairs_opened == 0
    assert run.note is not None and "closed" in run.note

    s.adapter.set_open("EURUSD", True)
    await s.timers.advance_to(at(11, 4, 59))
    assert s.adapter.orders == []
    await s.timers.advance_to(at(11, 5))
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert s.run().pairs_opened == 1
    await s.stop()


async def test_a_payout_below_the_minimum_sends_nothing() -> None:
    s = make_session_rig(min_payout_pct=90)  # the asset pays 80
    await s.start()
    await s.timers.advance_to(at(11, 10, 30))
    assert s.adapter.orders == []
    run = s.run()
    assert run.rounds_skipped == 3 and "below the minimum 90%" in (run.note or "")
    await s.stop()


async def test_a_lost_connection_skips_the_round() -> None:
    s = make_session_rig()
    await s.start()
    s.adapter.simulate_connection_loss()
    await s.timers.advance_to(at(11))
    assert s.adapter.orders == []
    assert "not connected" in (s.run().note or "")
    await s.stop()


async def test_a_leg_refused_after_the_other_went_out_is_a_lopsided_pair() -> None:
    s = make_session_rig(limits=RiskLimits(max_concurrent_trades=1))
    await open_first_pair_one_leg(s)

    run = s.run()
    assert run.lopsided_pairs == 1 and run.pairs_opened == 1
    failed = [c for c in s.chains() if c.status is ChainStatus.FAILED]
    assert len(failed) == 1
    assert len(s.adapter.orders) == 1  # only one order ever left
    await s.stop()


async def open_first_pair_one_leg(s: SessionRig) -> None:
    await s.start()
    await s.timers.advance_to(at(11))
    await s.rig.until(lambda: len(s.adapter.orders) >= 1)
    await s.timers.settle()


# --- the schedule: once, chosen days, a window missed ---


async def test_a_once_session_runs_one_window_and_never_again() -> None:
    s = make_session_rig(repeat=RepeatKind.ONCE, weekdays=())
    await open_first_pair(s)
    await s.timers.advance_to(at(11, 56))
    s.settle_orders()  # the next candle is the end of the window: the run is over
    await s.timers.advance_to(at(12, 5))
    assert s.run().state is RunState.ENDED

    await s.timers.advance_to(at(11, day=3))  # two days later, the same time of day
    assert len(s.runs()) == 1
    await s.stop()


async def test_a_weekday_session_runs_on_its_days_only() -> None:
    s = make_session_rig(weekdays=(0, 1, 2, 3, 4))  # Monday to Friday; 1 Nov 2026 is a Sunday
    await s.start()
    await s.timers.advance_to(at(11, 30))
    assert s.runs() == []  # Sunday: nothing

    await s.timers.advance_to(at(11, day=2))  # Monday 11:00
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert len(s.runs()) == 1
    await s.stop()


async def test_a_disabled_session_never_starts() -> None:
    s = make_session_rig(enabled=False)
    await s.start()
    await s.timers.advance_to(at(11, 30))
    assert s.adapter.orders == [] and s.runs() == []
    await s.stop()


async def test_a_session_saved_while_waiting_is_noticed() -> None:
    s = make_session_rig(enabled=False)
    await s.start()
    await s.timers.advance_to(at(10, 30))
    s.scheduler.set_session(SessionConfig(replace(s.session, enabled=True), s.settings))
    await s.timers.advance_to(at(11))
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    await s.stop()


# --- start now, one at a time, the account ---


async def test_start_now_opens_the_first_pair_at_once_not_at_a_boundary() -> None:
    s = make_session_rig(now=at(10, 7, 13))
    await s.start()

    run = s.scheduler.start_now(1)
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert run.started_by == "manual"
    assert {t.created_at for t in s.rig.trades("EURUSD")} == {at(10, 7, 13)}
    assert run.window_end == at(11, 7, 13)  # the usual one-hour window, from now

    with pytest.raises(SessionRunActiveError):
        s.scheduler.start_now(1)  # only one session runs at a time
    await s.stop()


async def test_a_scheduled_window_is_skipped_while_another_run_is_in_progress() -> None:
    s = make_session_rig(now=at(10, 30))
    await s.start()
    s.scheduler.start_now(1)  # runs until 11:30, across the 11:00 window of the same session
    await s.rig.until(lambda: len(s.adapter.orders) == 2)

    await s.timers.advance_to(at(11, 10))
    assert len(s.runs()) == 1  # the 11:00 window did not start a second run
    await s.stop()


async def test_stopping_when_nothing_runs_is_refused() -> None:
    s = make_session_rig()
    await s.start()
    with pytest.raises(NoActiveRunError):
        s.scheduler.stop_run(1)
    await s.stop()


async def test_the_account_cannot_be_switched_during_a_run() -> None:
    s = make_session_rig()
    await open_first_pair(s)
    with pytest.raises(AccountSwitchRefusedError, match="trading session"):
        await s.engine.switch_account(AccountType.REAL)
    await s.stop()


# --- restart, engine stop, Telegram off ---


async def test_a_run_found_going_after_a_restart_carries_on_in_its_window() -> None:
    s = make_session_rig(now=at(11, 31), mode=SessionMode.EVERY_CANDLE)  # M5, 11:00-12:00
    leftover = make_session_run(
        started_at=at(11),
        updated_at=at(11, 12),  # the application stopped soon after 11:12
        window_end=at(12),
        state=RunState.RUNNING,
        pairs_opened=3,
        profit=D("1.50"),
    )
    assert s.scheduler.recover([leftover]) == 0  # nothing ended
    await s.start()

    run = s.run()
    assert run.id == leftover.id and run.state is RunState.RUNNING
    assert run.rounds_skipped == 4  # 11:15, 11:20, 11:25 and 11:30 were missed
    assert "4 round(s) missed while the application was not running" in (run.note or "")
    assert (run.pairs_opened, run.profit) == (3, D("1.50"))  # its counters carry on

    await s.timers.advance_to(at(11, 34, 59))
    assert s.adapter.orders == []  # nothing is sent late: the next candle is 11:35
    await s.timers.advance_to(at(11, 35))
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert s.run().pairs_opened == 4
    await s.stop()


async def test_a_run_whose_window_ended_meanwhile_ends_as_interrupted() -> None:
    s = make_session_rig(now=at(11, 30))
    leftover = make_session_run(started_at=at(11), window_end=at(11, 20), state=RunState.RUNNING)

    assert s.scheduler.recover([leftover]) == 1
    [run] = s.runs()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.INTERRUPTED)
    assert "its window ended in the meantime" in (run.note or "")

    await s.start()
    await s.timers.advance_to(at(11, 50))
    assert s.adapter.orders == []  # an open window is not started by the restart itself
    await s.stop()


async def test_a_run_does_not_carry_on_when_the_kill_switch_is_on() -> None:
    s = make_session_rig(now=at(11, 30))
    s.engine.manager.engage_kill_switch()
    leftover = make_session_run(started_at=at(11), window_end=at(12), state=RunState.RUNNING)
    assert s.scheduler.recover([leftover]) == 1
    [run] = s.runs()
    assert run.end_reason is RunEndReason.INTERRUPTED and "kill switch" in (run.note or "")
    await s.stop()


async def test_a_run_that_was_stopping_or_whose_session_is_off_does_not_carry_on() -> None:
    s = make_session_rig(now=at(11, 30))
    stopping = make_session_run(started_at=at(11), window_end=at(12), state=RunState.STOPPING)
    assert s.scheduler.recover([stopping]) == 1
    s.scheduler.set_session(
        replace(s.scheduler.sessions()[0], session=replace(s.session, enabled=False))
    )
    going = make_session_run(started_at=at(11), window_end=at(12), state=RunState.RUNNING)
    assert s.scheduler.recover([going]) == 1
    notes = [r.note or "" for r in s.runs()]
    assert any("already stopping" in n for n in notes)
    assert any("switched off" in n for n in notes)
    await s.stop()


async def test_start_now_reads_the_payout_before_its_first_pair() -> None:
    s = make_session_rig(now=at(13))  # outside the window: nothing was prepared ahead
    await s.start()
    assert s.adapter.prepare_calls == []
    s.scheduler.start_now(1)
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    assert s.adapter.prepare_calls == [("EURUSD", 300)]
    await s.stop()


async def test_start_now_on_deriv_trades_from_its_first_round() -> None:
    s = make_session_rig(
        now=at(13), with_deriv=True, broker=Broker.DERIV, asset="R_75", duration_s=60
    )
    await s.start()
    fake = s.rig.deriv
    assert fake is not None
    s.scheduler.start_now(1)
    await s.rig.until(lambda: len(fake.orders) == 2)
    assert fake.prepare_calls == [("R_75", 60)]
    assert s.run().rounds_skipped == 0
    await s.stop()


async def test_a_round_without_a_payout_asks_deriv_so_the_next_round_trades() -> None:
    s = make_session_rig(
        now=at(13),
        with_deriv=True,
        broker=Broker.DERIV,
        asset="R_75",
        duration_s=60,
        mode=SessionMode.EVERY_CANDLE,
        max_open_pairs=3,
    )
    await s.start()
    fake = s.rig.deriv
    assert fake is not None
    s.scheduler.start_now(1)
    await s.rig.until(lambda: len(fake.orders) == 2)
    fake.simulate_connection_loss()  # a new connection forgets the payouts
    fake.simulate_connection_restored()

    await s.timers.advance_to(at(13, 1))
    run = s.run()
    assert run.rounds_skipped == 1 and "payout of R_75 is not known" in (run.note or "")
    await s.timers.advance_to(at(13, 2))
    await s.rig.until(lambda: len(fake.orders) == 4)  # asked for it: the next round trades
    await s.stop()


async def test_stopping_the_engine_ends_the_run() -> None:
    s = make_session_rig()
    await open_first_pair(s)
    await s.engine.stop()
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.ENGINE_STOPPED)
    await s.rig.tasks.shutdown()


async def test_closing_the_application_leaves_the_run_going_for_the_next_start() -> None:
    s = make_session_rig()
    await open_first_pair(s)
    await s.engine.stop(closing=True)  # Ctrl+C, not the owner pressing Stop
    run = s.run()
    assert run.state is RunState.RUNNING and run.ended_at is None
    assert "the application closed while this run was going" in (run.note or "")
    await s.rig.tasks.shutdown()


async def test_sessions_run_without_a_telegram_login() -> None:
    s = make_session_rig(with_telegram=False)
    assert s.engine.listener is None and not s.engine.telegram_enabled

    await open_first_pair(s)
    assert len(s.adapter.orders) == 2
    with pytest.raises(TelegramNotConnectedError):
        await s.engine.list_chats()
    await s.stop()


async def test_a_session_in_another_zone_starts_by_its_own_clock() -> None:
    s = make_session_rig(timezone="UTC-3", start_time=time(8, 0), end_time=time(9, 0))
    await s.start()
    await s.timers.advance_to(at(10, 59, 59))
    assert s.adapter.orders == []
    await s.timers.advance_to(at(11))
    await s.rig.until(lambda: len(s.adapter.orders) == 2)
    await s.stop()


async def test_the_chains_of_a_session_are_not_limited_by_decision_d9() -> None:
    """Two flip chains run at once in the hidden group (D-9 allows one in a Telegram group)."""
    s = make_session_rig(strategy=Strategy.FLIP_EVERY_LOSS)
    await open_first_pair(s)
    assert len(s.rig.engine.manager.active_chains(SESSION_GROUP)) == 2
    await s.stop()


async def test_a_growing_flip_pair_mirrors_its_two_legs_step_by_step() -> None:
    """Decision D-83: both legs on the same candle, each following the pattern from its own first
    direction; every loss sends the next step at once; the ninth loss ends the chain."""
    from app.events.types import TradeOpened

    s = make_session_rig(strategy=Strategy.GROWING_FLIP, multipliers=("2.0",) * 8)
    s.adapter.script_results(*([LOST] * 18))
    await open_first_pair(s)
    for step in range(1, 9):
        s.adapter.settle_all()
        await s.rig.until(lambda step=step: len(s.adapter.orders) == 2 * (step + 1))
    s.adapter.settle_all()
    await s.rig.idle()

    legs: dict[object, list[Direction]] = {}
    for event in s.rig.collect():
        if isinstance(event, TradeOpened) and event.trade.broker_order_id is not None:
            legs.setdefault(event.trade.chain_id, []).append(event.trade.direction)
    call_leg, put_leg = sorted(legs.values(), key=lambda d: d[0] is not CALL)
    assert call_leg == [CALL, PUT, CALL, CALL, PUT, PUT, CALL, CALL, CALL]
    assert put_leg == [PUT, CALL, PUT, PUT, CALL, CALL, PUT, PUT, PUT]
    assert {c.status for c in s.chains()} == {ChainStatus.EXHAUSTED}
    await s.stop()
