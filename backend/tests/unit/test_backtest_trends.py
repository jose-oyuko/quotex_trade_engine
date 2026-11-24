"""Opening pairs after a breakout (Phase 31, decision D-85): when the trends start and stop, that
nothing opens before a breakout is known, that running chains finish, and that the backtest's
detector finds what the Market page's scan finds."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from app.backtest.replay import (
    WARMUP_CANDLES,
    BacktestSetup,
    OpenRule,
    Prices,
    Run,
    StrategySetup,
    replay,
    replay_window,
    trend_spans,
)
from app.backtest.store import BacktestStore
from app.domain.enums import SessionMode, Strategy
from app.market.detector import MarketRules
from app.services.backtests import setup_from_json, setup_to_json, summary_to_json
from app.services.market import scan_stored

D = Decimal
DAY = date(2023, 11, 15)
T10 = int(datetime(2023, 11, 15, 10, 0, tzinfo=UTC).timestamp())

# The candles from 10:00, one a minute (open, close); flat at 100 before and flat after.
UP_DOWN = [(100, 101), (101, 100)]
CANDLES = [
    *UP_DOWN,
    *UP_DOWN,
    (100, 101),  # 10:00-10:04: five alternating candles, the range is 100 to 101
    (101, 103),
    (103, 105),  # 10:05, 10:06: two closes above 101, the breakout is known at 10:07
    *[(105 + k, 106 + k) for k in range(10)],  # 10:07-10:16: a rising trend
    (115, 114),
    (114, 115),
    (115, 114),
    (114, 115),  # 10:17-10:20: with 10:16 five alternating candles, found at 10:21
]
BREAKOUT_KNOWN = T10 + 7 * 60
NEXT_FOUND = T10 + 21 * 60


def quote(t: int) -> float:
    minute, second = divmod(t - T10, 60)
    if minute < 0:
        return 100.0
    if minute >= len(CANDLES):
        return float(CANDLES[-1][1])
    open_, close = CANDLES[minute]
    return open_ + (close - open_) * second / 59


def prices(start: int = T10 - 2 * 3600, end: int = T10 + 3 * 3600) -> Prices:
    times = list(range(start, end + 1))
    return Prices(times, [quote(t) for t in times], [(start, end)])


def setup(**changes: object) -> BacktestSetup:
    base = BacktestSetup(
        asset="1HZ75V",
        first_day=DAY,
        last_day=DAY,
        start_time=time(10, 0),
        end_time=time(11, 0),
        timezone="UTC",
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        duration_s=60,
        mode=SessionMode.EVERY_CANDLE,
        pause_s=0,
        max_open_pairs=50,
        max_pairs=None,
        profit_target=None,
        loss_limit=None,
        base_stake=D(1),
        strategies=(StrategySetup(Strategy.NO_MARTINGALE, 0, ()),),
        opens=(OpenRule.BREAKOUT,),
        trend_max_candles=None,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def window(s: BacktestSetup):  # type: ignore[no-untyped-def]
    [w] = s.windows()
    return w


def test_a_trend_runs_from_the_known_breakout_until_the_next_consolidation_is_known() -> None:
    s = setup()
    assert trend_spans(prices(), s, T10, T10 + 3600) == [(BREAKOUT_KNOWN, NEXT_FOUND)]
    capped = setup(trend_max_candles=5)
    assert trend_spans(prices(), capped, T10, T10 + 3600) == [
        (BREAKOUT_KNOWN, BREAKOUT_KNOWN + 300)
    ]
    # the cap only shortens: a trend ended earlier by a consolidation stays as it is
    long = setup(trend_max_candles=100)
    assert trend_spans(prices(), long, T10, T10 + 3600) == [(BREAKOUT_KNOWN, NEXT_FOUND)]


def test_pairs_open_only_after_a_breakout_is_known_and_stop_at_the_next_consolidation() -> None:
    s = setup()
    result = replay_window(prices(), s, 0, window(s), trend_spans(prices(), s, T10, T10 + 3600))
    starts = sorted({c.started for c in result.chains})
    # a pair at every candle from 10:07 to 10:20, bought 0.5 s after the candle
    assert starts == [BREAKOUT_KNOWN + 60 * k for k in range(14)]
    assert result.pairs == 14
    assert min(starts) >= BREAKOUT_KNOWN  # never before the breakout was known
    assert max(starts) < NEXT_FOUND
    assert (result.spans, result.active_s) == (1, NEXT_FOUND - BREAKOUT_KNOWN)

    capped = setup(trend_max_candles=5)
    early = replay_window(
        prices(), capped, 0, window(capped), trend_spans(prices(), capped, T10, T10 + 3600)
    )
    assert early.pairs == 5  # 10:07 to 10:11: the time ran out before the consolidation

    always = replay_window(prices(), s, 0, window(s))
    assert always.pairs == 60  # all through the window: every candle from 10:00


def test_running_chains_finish_after_the_trend_and_nothing_opens_until_the_next_breakout() -> None:
    martingale = StrategySetup(Strategy.MARTINGALE, 3, (D(2), D(4), D(8)))
    s = setup(strategies=(martingale,), mode=SessionMode.SEQUENTIAL)
    result = replay_window(prices(), s, 0, window(s), trend_spans(prices(), s, T10, T10 + 3600))
    assert result.pairs >= 1
    assert all(BREAKOUT_KNOWN <= c.started < NEXT_FOUND for c in result.chains)
    # the last pair's chains go on after the consolidation was found, until they end
    assert max(t.end for c in result.chains for t in c.trades) > NEXT_FOUND
    # the prices are flat from 10:21: no breakout, so no new pair for the rest of the window
    assert all(c.started < NEXT_FOUND for c in result.chains)


def test_a_trend_going_on_when_the_window_opens_is_traded_from_the_window_start() -> None:
    s = setup(start_time=time(10, 10))
    result = replay_window(prices(), s, 0, window(s), trend_spans(prices(), s, T10, T10 + 3600))
    assert min(c.started for c in result.chains) == T10 + 600
    assert result.pairs == 11  # 10:10 to 10:20


def test_the_backtest_finds_the_same_trends_as_the_market_page(tmp_path: Path) -> None:
    store = BacktestStore(tmp_path / "history.db")
    store.prepare(datetime(2023, 11, 16, tzinfo=UTC), cut_running=False)
    p = prices()
    store.add("1HZ75V", list(p.times), list(p.quotes))
    store.cover("1HZ75V", p.times[0], p.times[-1])
    s = setup(market=MarketRules(candles=5, breakout_candles=2))
    first = T10
    last = T10 + 3600
    page = scan_stored(store, "1HZ75V", first - WARMUP_CANDLES * 60, last, 60, s.market)
    expected = [(t.start, t.stopped) for t in page.found.trends if t.stopped > first]
    assert expected == [(BREAKOUT_KNOWN, NEXT_FOUND)]
    assert trend_spans(p, s, first, last) == expected


def test_each_strategy_runs_each_way_on_each_period_and_the_setup_round_trips() -> None:
    martingale = StrategySetup(Strategy.MARTINGALE, 1, (D(2),))
    s = setup(
        strategies=(StrategySetup(Strategy.NO_MARTINGALE, 0, ()), martingale),
        opens=(OpenRule.WINDOW, OpenRule.BREAKOUT),
        check_first_day=DAY,
        check_last_day=DAY,
        trend_max_candles=20,
    )
    assert len(s.runs()) == 8
    assert s.runs()[:3] == [
        Run(0, OpenRule.WINDOW, 1),
        Run(1, OpenRule.WINDOW, 1),
        Run(0, OpenRule.BREAKOUT, 1),
    ]
    result = replay(prices(), s)
    assert result.windows == 2
    assert [t.pairs for t in result.totals] == [60, 60, 14, 14] * 2
    assert {c.run for c in result.chains} == set(range(8))
    summary = summary_to_json(result, s, seconds=0.1)
    third = summary["strategies"][2]
    assert (third["index"], third["opens"], third["period"], third["spans"]) == (
        0,
        "breakout",
        1,
        1,
    )
    assert third["active_s"] == NEXT_FOUND - BREAKOUT_KNOWN
    assert setup_from_json(setup_to_json(s)) == s


def test_a_backtest_stored_before_phase_31_still_reads() -> None:
    data = setup_to_json(setup(opens=(OpenRule.WINDOW,), trend_max_candles=20))
    for key in ("opens", "market", "trend_max_candles", "check_first_day", "check_last_day"):
        del data[key]
    old = setup_from_json(data)
    assert old.opens == (OpenRule.WINDOW,)
    assert old.market == MarketRules()
    assert old.periods() == [(DAY, DAY)]
