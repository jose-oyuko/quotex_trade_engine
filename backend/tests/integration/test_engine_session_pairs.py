"""Trading sessions, second mode (decision D-73): a pair at every candle, whatever is still running,
up to a limit of open pairs. Each pair's chains stay fully independent of the others."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.domain.enums import ChainStatus, Direction, RunEndReason, RunState, SessionMode
from app.quotex.base import TradeOutcome
from tests.session_support import SESSION_GROUP, SessionRig, make_session_rig

CALL, PUT = Direction.CALL, Direction.PUT
WON, LOST = TradeOutcome.WON, TradeOutcome.LOST
D = Decimal


def at(hour: int, minute: int = 0, second: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


def candle_rig(max_open_pairs: int = 3, **overrides: object) -> SessionRig:
    return make_session_rig(
        mode=SessionMode.EVERY_CANDLE, max_open_pairs=max_open_pairs, **overrides
    )


async def until_orders(s: SessionRig, count: int) -> None:
    await s.timers.settle()
    await s.rig.until(lambda: len(s.adapter.orders) == count)


# --- a pair at every candle, up to the limit ---


async def test_a_pair_opens_at_every_candle_until_the_maximum_is_open() -> None:
    s = candle_rig(max_open_pairs=3)
    await s.start()

    await s.timers.advance_to(at(11))
    await until_orders(s, 2)
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)
    await s.timers.advance_to(at(11, 10))
    await until_orders(s, 6)  # three pairs open, none has ended
    assert s.run().pairs_opened == 3

    await s.timers.advance_to(at(11, 15))  # the fourth candle finds the limit reached
    await s.timers.settle()
    assert len(s.adapter.orders) == 6
    run = s.run()
    assert (run.pairs_opened, run.rounds_skipped) == (3, 1)
    assert run.note is not None and "limit is 3" in run.note

    s.settle_orders(upto=2)  # the first pair ends: room for one more
    await s.timers.advance_to(at(11, 20))
    await until_orders(s, 8)
    assert s.run().pairs_opened == 4
    assert sorted({c.pair_no for c in s.chains() if c.pair_no}) == [1, 2, 3, 4]
    await s.stop()


async def test_a_limit_of_one_waits_for_the_pair_to_end_but_opens_on_a_candle() -> None:
    s = candle_rig(max_open_pairs=1)
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)

    await s.timers.advance_to(at(11, 5, 1))  # the pair is still running at the next candle
    assert len(s.adapter.orders) == 2 and s.run().rounds_skipped == 1

    s.settle_orders()
    await s.timers.advance_to(at(11, 9, 59))
    assert len(s.adapter.orders) == 2  # a pair opens on a candle, not the moment room appears
    await s.timers.advance_to(at(11, 10))
    await until_orders(s, 4)
    await s.stop()


async def test_the_pause_is_not_used_in_this_mode() -> None:
    s = candle_rig(max_open_pairs=5, pause_s=3600)
    await s.start()
    await s.timers.advance_to(at(11, 10))
    await until_orders(s, 6)  # 11:00, 11:05, 11:10 whatever the pause says
    await s.stop()


async def test_no_boundary_is_missed_or_doubled_however_time_jumps() -> None:
    s = candle_rig(max_open_pairs=20)
    await s.start()

    await s.timers.advance_to(at(11, 32))  # one big jump: every candle in it still gets its pair
    await s.rig.until(lambda: len(s.adapter.orders) == 14)
    created = {t.created_at for t in s.rig.trades("EURUSD")}
    assert created == {at(11, m) for m in range(0, 31, 5)}  # 11:00 ... 11:30, each once
    assert s.run().pairs_opened == 7
    await s.stop()


async def test_a_start_now_run_opens_at_once_and_then_on_the_candles() -> None:
    s = candle_rig(max_open_pairs=4, now=at(10, 7, 13))
    await s.start()
    s.scheduler.start_now(1)
    await until_orders(s, 2)
    assert {t.created_at for t in s.rig.trades("EURUSD")} == {at(10, 7, 13)}

    await s.timers.advance_to(at(10, 10))
    await until_orders(s, 4)
    assert {t.created_at for t in s.rig.trades("EURUSD")} == {at(10, 7, 13), at(10, 10)}
    await s.stop()


async def test_a_round_that_cannot_be_traded_is_skipped_and_the_next_candle_tries_again() -> None:
    s = candle_rig(max_open_pairs=3)
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)

    s.adapter.set_open("EURUSD", False)
    await s.timers.advance_to(at(11, 5))
    await s.timers.settle()
    assert len(s.adapter.orders) == 2 and "closed" in (s.run().note or "")

    s.adapter.set_open("EURUSD", True)
    await s.timers.advance_to(at(11, 10))
    await until_orders(s, 4)
    assert s.run().rounds_skipped == 1
    await s.stop()


# --- the pairs do not influence each other ---


async def test_each_pair_follows_its_own_steps_and_stakes() -> None:
    s = candle_rig(max_open_pairs=3)
    s.adapter.script_results(LOST, WON, WON, WON, WON, WON)  # only the first order loses
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)

    s.adapter.settle(s.adapter.orders[0].order_id)  # pair 1's CALL loses: recovery at base x 2
    await until_orders(s, 3)
    assert (s.adapter.orders[2].direction, s.adapter.orders[2].amount) == (PUT, 2)

    await s.timers.advance_to(at(11, 5))  # pair 2 starts fresh, at the base stake
    await until_orders(s, 5)
    assert [(o.direction, o.amount) for o in s.adapter.orders[3:]] == [(CALL, 1), (PUT, 1)]
    steps = {(c.pair_no, c.origin_direction): c.step for c in s.chains()}
    assert steps[(1, CALL)] == 1 and steps[(1, PUT)] == 0 and steps[(2, CALL)] == 0
    await s.stop()


async def test_ending_one_chain_leaves_every_other_chain_of_every_pair_running() -> None:
    s = candle_rig(max_open_pairs=3)
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)

    manager = s.rig.engine.manager
    chains = manager.active_chains(SESSION_GROUP)
    assert len(chains) == 4
    victim = next(c for c in chains if c.spec.pair_no == 2 and c.spec.origin_direction is CALL)
    manager.end_chain(victim.id)
    remaining = manager.active_chains(SESSION_GROUP)
    assert len(remaining) == 3 and victim not in remaining
    assert all(c.status in (ChainStatus.OPEN, ChainStatus.PENDING) for c in remaining)
    assert s.run().state is RunState.RUNNING  # one chain ending does not end the run or the pair
    await s.stop()


# --- stopping with several pairs open: every chain of every pair finishes ---


async def test_the_window_end_leaves_all_open_pairs_to_finish() -> None:
    s = candle_rig(max_open_pairs=3)
    await s.start()
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)

    await s.timers.advance_to(at(12))
    assert s.run().state is RunState.STOPPING
    assert len(s.rig.engine.manager.active_chains(SESSION_GROUP)) == 6  # nothing cut off
    assert len(s.adapter.orders) == 6  # three pairs were allowed; later candles found the limit
    assert s.run().pairs_opened == 3

    s.settle_orders()
    await s.timers.settle()
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.WINDOW_ENDED)
    assert s.rig.engine.manager.active_chains(SESSION_GROUP) == []
    await s.stop()


async def test_the_profit_target_stops_new_pairs_but_every_open_chain_finishes() -> None:
    s = candle_rig(max_open_pairs=3, profit_target=D("0.80"))
    s.adapter.script_results(WON, LOST, WON, WON)
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)

    s.adapter.settle(s.adapter.orders[0].order_id)  # +0.80 reaches the target
    await s.timers.settle()
    assert s.run().state is RunState.STOPPING

    await s.timers.advance_to(at(11, 5))
    await s.timers.settle()
    assert len(s.adapter.orders) == 2  # the 11:05 candle gets no pair

    s.adapter.settle(s.adapter.orders[1].order_id)  # the loser still recovers
    await until_orders(s, 3)
    s.adapter.settle(s.adapter.orders[2].order_id)
    await s.timers.advance_to(at(11, 20))
    run = s.run()
    assert (run.state, run.end_reason, run.pairs_opened) == (
        RunState.ENDED,
        RunEndReason.PROFIT_TARGET,
        1,
    )
    await s.stop()


async def test_the_maximum_number_of_pairs_ends_the_run_when_the_last_pair_is_over() -> None:
    s = candle_rig(max_open_pairs=5, max_pairs=2)
    await s.start()
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)
    assert s.run().state is RunState.STOPPING  # the second pair is out: no third

    await s.timers.advance_to(at(11, 10))
    assert len(s.adapter.orders) == 4
    s.settle_orders()
    await s.timers.settle()
    run = s.run()
    assert (run.state, run.end_reason, run.pairs_opened) == (
        RunState.ENDED,
        RunEndReason.MAX_PAIRS,
        2,
    )
    await s.stop()


async def test_the_owner_can_stop_a_run_with_pairs_open_and_the_recoveries_still_go_out() -> None:
    s = candle_rig(max_open_pairs=3)
    s.adapter.script_results(WON, WON, LOST, WON, WON, WON)
    await s.start()
    await s.timers.advance_to(at(11))
    await until_orders(s, 2)
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)

    s.scheduler.stop_run(1)
    s.adapter.settle(s.adapter.orders[2].order_id)  # pair 2's CALL loses: it recovers all the same
    await until_orders(s, 5)
    s.settle_orders()
    await s.timers.advance_to(at(11, 30))
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.STOPPED)
    assert run.pairs_opened == 2 and len(s.adapter.orders) == 5
    await s.stop()


async def test_the_kill_switch_ends_a_run_with_pairs_open() -> None:
    s = candle_rig(max_open_pairs=3)
    await s.start()
    await s.timers.advance_to(at(11, 5))
    await until_orders(s, 4)

    s.rig.engine.manager.engage_kill_switch()
    await s.timers.settle()
    assert s.run().state is RunState.STOPPING
    s.settle_orders()
    await s.timers.advance_to(at(11, 30))
    run = s.run()
    assert (run.state, run.end_reason) == (RunState.ENDED, RunEndReason.KILL_SWITCH)
    assert len(s.adapter.orders) == 4
    await s.stop()


async def test_the_last_candle_before_the_end_of_the_window_ends_the_run_early() -> None:
    s = candle_rig(max_open_pairs=20)
    await s.start()
    await s.timers.advance_to(at(11, 55))
    await s.rig.until(lambda: len(s.adapter.orders) == 24)  # 11:00 ... 11:55 is 12 pairs
    assert s.run().state is RunState.STOPPING  # the next candle is the end: nothing more to open
    s.settle_orders()
    await s.timers.settle()
    assert s.run().end_reason is RunEndReason.WINDOW_ENDED
    await s.stop()
