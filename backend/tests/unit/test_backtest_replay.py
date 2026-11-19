"""The replay (decision D-84): Deriv's result rule, the live step rules of every strategy, and the
session's pair rules, on hand-made prices."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from app.backtest.replay import (
    BacktestSetup,
    Cancelled,
    Prices,
    StrategySetup,
    decide,
    replay,
    replay_window,
    run_chain,
)
from app.domain.enums import ChainStatus, Direction, SessionMode, Strategy
from app.engine.strategies import step_direction

D = Decimal
C, P = Direction.CALL, Direction.PUT
DAY = date(2023, 11, 15)  # a Wednesday
T10 = int(datetime(2023, 11, 15, 10, 0, tzinfo=UTC).timestamp())


def prices(quote: object = 100.0, start: int = T10 - 3600, end: int = T10 + 7200) -> Prices:
    """A price every second; `quote` is a number (flat: every trade ends equal, so every trade
    loses) or a function of the second."""
    times = list(range(start, end + 1))
    quotes = [quote(t) if callable(quote) else float(quote) for t in times]  # type: ignore[arg-type]
    return Prices(times, quotes, [(start, end)])


def setup(*strategies: StrategySetup, **changes: object) -> BacktestSetup:
    base = BacktestSetup(
        asset="1HZ75V",
        first_day=DAY,
        last_day=DAY,
        start_time=time(10, 0),
        end_time=time(10, 5),
        timezone="UTC",
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        duration_s=60,
        mode=SessionMode.SEQUENTIAL,
        pause_s=0,
        max_open_pairs=1,
        max_pairs=None,
        profit_target=None,
        loss_limit=None,
        base_stake=D(1),
        strategies=strategies or (StrategySetup(Strategy.NO_MARTINGALE, 0, ()),),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def doubling(strategy: Strategy, steps: int) -> StrategySetup:
    return StrategySetup(strategy, steps, tuple(D(2**k) for k in range(1, steps + 1)))


# ---- one trade -------------------------------------------------------------------------------


def test_the_entry_is_the_first_price_after_the_start_and_the_exit_the_last_at_the_end() -> None:
    p = Prices([100, 101, 130, 160, 161], [1.0, 2.0, 3.0, 4.0, 9.0], [(0, 1000)])
    trade = decide(p, C, D(1), 100.5, setup(duration_s=60))
    assert trade is not None
    assert (trade.start, trade.end, trade.entry, trade.exit) == (100, 160, 2.0, 4.0)
    assert trade.profit == D("0.88")
    lost = decide(p, P, D("2.50"), 100.5, setup(duration_s=60))
    assert lost is not None and lost.profit == D("-2.50")


def test_an_equal_exit_loses_both_ways_and_the_payout_is_the_assumption() -> None:
    p = prices(100.0)
    for direction in (C, P):
        trade = decide(p, direction, D(10), T10, setup())
        assert trade is not None and trade.profit == D(-10)
    rising = prices(lambda t: float(t))
    won = decide(rising, C, D(10), T10, setup(payout_pct=D("95.5")))
    assert won is not None and won.profit == D("9.55")


def test_no_price_data_is_never_guessed() -> None:
    p = Prices([T10 + 5], [1.0], [(T10, T10 + 30)])  # the end of the trade was not downloaded
    assert decide(p, C, D(1), T10, setup()) is None
    empty = Prices([], [], [(T10 - 100, T10 + 100)])  # downloaded, but no price at all
    assert decide(empty, C, D(1), T10, setup()) is None


# ---- one chain: the live step rules ------------------------------------------------------------


@pytest.mark.parametrize(
    "strategy",
    [Strategy.MARTINGALE, Strategy.FLIP_EVERY_LOSS, Strategy.TWO_STEP_FLIP, Strategy.GROWING_FLIP],
)
@pytest.mark.parametrize("origin", [C, P])
def test_a_losing_chain_follows_the_live_directions_and_stakes(
    strategy: Strategy, origin: Direction
) -> None:
    s = setup(doubling(strategy, 8))
    chain = run_chain(prices(100.0), s, 0, origin, T10, day=DAY, pair_no=1)
    assert chain is not None
    assert chain.status is ChainStatus.EXHAUSTED
    assert chain.end_reason == "all 9 trade(s) lost"
    assert [t.direction for t in chain.trades] == [
        step_direction(strategy, k, origin) for k in range(9)
    ]
    assert [t.stake for t in chain.trades] == [D(2**k) for k in range(9)]
    assert chain.profit == -sum(D(2**k) for k in range(9))


def test_growing_flip_goes_in_blocks_of_1_1_2_2_3() -> None:
    chain = run_chain(
        prices(100.0), setup(doubling(Strategy.GROWING_FLIP, 8)), 0, C, T10, day=DAY, pair_no=1
    )
    assert chain is not None
    assert [t.direction for t in chain.trades] == [C, P, C, C, P, P, C, C, C]


def test_each_step_starts_after_the_previous_trade_ended_plus_the_delays() -> None:
    s = setup(doubling(Strategy.MARTINGALE, 2), step_delay_s=1.0, order_delay_s=0.5)
    chain = run_chain(prices(100.0), s, 0, C, T10, day=DAY, pair_no=1)
    assert chain is not None
    assert [t.start for t in chain.trades] == [T10, T10 + 61, T10 + 122]


def test_a_win_ends_the_chain_at_its_step() -> None:
    # falling until 10:01:30, then rising: CALL loses the first trade and wins the second
    def quote(t: int) -> float:
        return float(-t if t <= T10 + 90 else t)

    s = setup(doubling(Strategy.MARTINGALE, 3))
    chain = run_chain(prices(quote), s, 0, C, T10, day=DAY, pair_no=1)
    assert chain is not None
    assert chain.status is ChainStatus.COMPLETED
    assert [t.won for t in chain.trades] == [False, True]
    assert chain.profit == D(-1) + D("1.76")


def test_a_step_without_price_data_ends_the_chain_there() -> None:
    p = prices(100.0, end=T10 + 70)  # the second trade's end was not downloaded
    chain = run_chain(p, setup(doubling(Strategy.MARTINGALE, 3)), 0, C, T10, day=DAY, pair_no=1)
    assert chain is not None
    assert chain.status is ChainStatus.FAILED and chain.end_reason == "no price data"
    assert len(chain.trades) == 1
    assert run_chain(prices(100.0, end=T10 + 30), setup(), 0, C, T10, day=DAY, pair_no=1) is None


# ---- a session window ----------------------------------------------------------------------


def window(s: BacktestSetup):  # type: ignore[no-untyped-def]
    [w] = s.windows()
    return w


def test_one_pair_at_a_time_opens_the_next_on_the_candle_after_both_chains_ended() -> None:
    s = setup()  # no martingale: each chain is one 60 s trade
    result = replay_window(prices(100.0), s, 0, window(s))
    # 10:00, then each pair as soon as the last result is known (0.5 s after the end counts as on
    # the candle), bought 0.5 s later: like live, each pair starts 1 s later than the one before
    assert result.pairs == 5
    assert [c.started for c in result.chains[::2]] == [T10 + 61 * k for k in range(5)]
    assert [c.origin for c in result.chains[:2]] == [C, P]
    assert result.stopped_by == "window_ended"

    paused = setup(pause_s=30)
    assert replay_window(prices(100.0), paused, 0, window(paused)).pairs == 3  # 10:00, :02, :04


def test_a_pair_at_every_candle_skips_rounds_when_too_many_are_open() -> None:
    s = setup(doubling(Strategy.MARTINGALE, 1), mode=SessionMode.EVERY_CANDLE, max_open_pairs=1)
    # each chain: 2 trades, the second starting 1 s after the first ended, so a pair is over at
    # 10:02:01.5 and the 10:02 candle still finds it open
    result = replay_window(prices(100.0), s, 0, window(s))
    assert result.pairs == 2  # 10:00 and 10:03
    assert result.skipped_rounds == 3  # 10:01, 10:02 and 10:04
    wide = replay_window(prices(100.0), replace(s, max_open_pairs=2), 0, window(s))
    assert (wide.pairs, wide.skipped_rounds) == (4, 1)  # only 10:02 finds two pairs open


def test_a_loss_limit_stops_new_pairs_and_lets_the_running_chains_finish() -> None:
    # rising prices: each pair's CALL wins 0.88 and its PUT loses 1, a loss of 0.12 a pair
    s = setup(loss_limit=D("0.30"))
    result = replay_window(prices(lambda t: float(t)), s, 0, window(s))
    assert result.pairs == 3
    assert result.stopped_by == "loss_limit"
    capped = setup(max_pairs=2)
    assert replay_window(prices(100.0), capped, 0, window(capped)).stopped_by == "max_pairs"
    target = setup(profit_target=D("0.50"), payout_pct=D(200))  # each pair makes 1.00
    assert replay_window(prices(lambda t: float(t)), target, 0, window(target)).pairs == 1


def test_a_round_without_price_data_opens_no_pair() -> None:
    s = setup()
    p = Prices(
        list(range(T10, T10 + 600)), [100.0] * 600, [(T10, T10 + 130), (T10 + 200, T10 + 600)]
    )
    result = replay_window(p, s, 0, window(s))
    # 10:02:02 and 10:03 reach into 10:02:11-10:03:19, which was not downloaded; 10:04 is fine
    assert result.no_data_rounds == 2
    assert result.pairs == 3


# ---- the whole backtest ----------------------------------------------------------------------


def test_the_windows_follow_the_days_the_zone_and_the_weekdays() -> None:
    s = setup(
        first_day=date(2023, 11, 13),  # Monday
        last_day=date(2023, 11, 19),  # Sunday
        weekdays=(0, 2, 4),
        timezone="UTC+3",
        start_time=time(1, 0),
        end_time=time(2, 0),
    )
    starts = [w.start for w in s.windows()]
    assert starts == [
        datetime(2023, 11, 12, 22, 0, tzinfo=UTC),  # Monday 01:00 at UTC+3
        datetime(2023, 11, 14, 22, 0, tzinfo=UTC),
        datetime(2023, 11, 16, 22, 0, tzinfo=UTC),
    ]


def test_every_strategy_is_compared_on_the_same_prices_and_the_figures_add_up() -> None:
    s = setup(
        StrategySetup(Strategy.NO_MARTINGALE, 0, ()),
        doubling(Strategy.MARTINGALE, 2),
        doubling(Strategy.GROWING_FLIP, 8),
    )
    result = replay(prices(100.0), s)
    flat, martingale, growing = result.totals
    assert result.windows == 1
    assert (flat.pairs, flat.chains, flat.trades, flat.exhausted) == (5, 10, 10, 10)
    assert flat.profit == D(-10) and flat.worst_drawdown == D(10)
    assert flat.most_in_play == D(2)  # the two legs of a pair at once
    assert martingale.trades == martingale.chains * 3
    assert martingale.largest_stake == D(4)
    assert martingale.longest_losing_run == martingale.chains
    assert growing.won_at_step == [0] * 9
    assert flat.won_at_step == [0]  # one entry per step of its own strategy
    assert growing.largest_stake == D(256)
    assert sum(len(c.trades) for c in result.chains if c.strategy == 2) == growing.trades
    assert flat.days == {"2023-11-15": [D(-10), 10, 10]}
    assert flat.stops == {"window_ended": 1}
    assert flat.equity[-1][1] == D(-10)


def test_the_same_prices_and_setup_always_give_the_same_result() -> None:
    s = setup(doubling(Strategy.TWO_STEP_FLIP, 4), mode=SessionMode.EVERY_CANDLE, max_open_pairs=3)
    wavy = prices(lambda t: float((t * 7919) % 101))
    first, second = replay(wavy, s), replay(wavy, s)
    assert first.totals == second.totals
    assert [(c.started, c.profit) for c in first.chains] == [
        (c.started, c.profit) for c in second.chains
    ]


def test_a_backtest_can_be_cancelled_and_reports_progress() -> None:
    s = setup(first_day=date(2023, 11, 13), last_day=date(2023, 11, 19))
    seen: list[float] = []
    replay(prices(100.0), s, progress=seen.append)
    assert seen[-1] == 1.0 and len(seen) == 7
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        replay(prices(100.0), s, cancel=stop)
