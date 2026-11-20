"""The statistics of a scan on candles with a known answer (decision D-85)."""

from __future__ import annotations

import pytest

from app.market.detector import PATTERN_DEFAULTS, MarketRules, Pattern, scan
from app.market.stats import (
    BREAK_EVEN,
    MAX_TRADES,
    Rate,
    compare,
    flip_depth,
    market_stats,
    spread,
)
from tests.unit.test_market_detector import ALTERNATING, M1, bars


def depth(text: str, i: int = 0) -> int | None:
    candles = bars(text)
    return flip_depth(candles, [0] * len(candles), i)


def test_a_spread_has_the_median_quartiles_and_longest() -> None:
    s = spread([5, 1, 3, 2, 4])
    assert (s.count, s.mean, s.median, s.q1, s.q3, s.longest) == (5, 3.0, 3.0, 2.0, 4.0, 5)
    assert spread([]).count == 0
    assert spread([7]).q1 == spread([7]).q3 == 7.0


def test_a_rate_comes_with_its_95_percent_range() -> None:
    rate = Rate(50, 100)
    assert rate.share == 0.5
    assert rate.low == pytest.approx(0.404, abs=0.001)
    assert rate.high == pytest.approx(0.596, abs=0.001)
    assert (Rate(0, 0).share, Rate(0, 0).low, Rate(0, 0).high) == (0.0, 0.0, 1.0)
    assert round(BREAK_EVEN, 4) == 0.5319


def test_a_flip_pair_goes_as_deep_as_the_candles_alternate() -> None:
    assert depth("UUU") == 1  # the Fall leg loses once, then follows the colour
    assert depth("UDUU") == 3
    assert depth("EUU") == 2  # an equal candle loses for both legs
    assert depth("UDUDUDUDUD") == MAX_TRADES  # followed no further than a chain goes
    assert depth("UD") is None  # not settled before the data ends
    candles = bars("UDUU")
    assert flip_depth(candles, [0, 0, 1, 1], 0) is None  # nor across a gap


def test_the_figures_of_a_period_with_two_consolidations() -> None:
    candles = bars("UDUDU BB UUU UDUDU BB U")
    found = scan(candles, ALTERNATING, M1)
    stats = market_stats(candles, found, ALTERNATING, deep=5)
    assert (stats.candles, stats.consolidations, stats.breakouts) == (18, 2, 2)
    assert stats.in_consolidation == 10 / 18
    # the first trend: from candle 7 until the next consolidation was found after candle 14
    assert (stats.trend_wait.count, stats.trend_wait.median) == (1, 8.0)
    # from candle 0 the pattern is complete 5 candles on; from candle 1 (too late for the first
    # consolidation) only after candle 14, 14 candles on; from candle 11 on, never
    assert stats.any_wait.count == 11 and stats.any_wait.longest == 14
    assert (stats.first_with.hits, stats.first_with.total) == (2, 2)
    assert (stats.trend_with.hits, stats.trend_with.total) == (4, 4)
    # pairs opened on candles 0 and 10 lose 5 trades in a row, inside the consolidations; the one
    # on candle 10 was still "trending": that consolidation was only known after candle 14
    assert (stats.deep_any.hits, stats.deep_trend.hits) == (2, 1)
    assert (stats.described.hits, stats.described.total) == (10, 10)


def test_every_pattern_is_compared_on_the_same_candles() -> None:
    candles = bars("UDUDU BB UUU UDUDU BB U" * 3)
    rows = compare(candles, M1)
    assert [rules.pattern for rules, _ in rows] == list(Pattern)
    assert rows[0][0] == PATTERN_DEFAULTS[Pattern.ALTERNATING] == MarketRules()
    assert all(stats.candles == len(candles) for _, stats in rows)
