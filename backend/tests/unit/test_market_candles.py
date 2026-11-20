"""Candles of any length from prices (decision D-85)."""

from __future__ import annotations

import pytest

from app.market.candles import DOWN, EQUAL, UP, Candle, candles_from_ticks

T0 = 1_700_000_100  # a multiple of 300: an M1 and an M5 boundary


def test_m1_candles_open_on_the_first_price_and_close_on_the_last() -> None:
    times = [T0, T0 + 10, T0 + 59, T0 + 60, T0 + 119]
    quotes = [10.0, 12.0, 11.0, 11.5, 9.0]
    first, second = candles_from_ticks(times, quotes, 60)
    assert first == Candle(T0, 10.0, 12.0, 10.0, 11.0, 3)
    assert second == Candle(T0 + 60, 11.5, 11.5, 9.0, 9.0, 2)
    assert (first.colour, second.colour) == (UP, DOWN)
    assert first.size == 2.0


def test_m5_candles_start_on_the_five_minutes() -> None:
    times = list(range(T0 - 30, T0 + 600))
    found = candles_from_ticks(times, [1.0] * len(times), 300)
    assert [c.start - T0 for c in found] == [-300, 0, 300]
    assert [c.ticks for c in found] == [30, 300, 300]
    assert found[1].colour == EQUAL


def test_a_minute_without_prices_stays_a_gap() -> None:
    times = [T0, T0 + 30, T0 + 125]  # nothing from T0 + 60 to T0 + 119
    found = candles_from_ticks(times, [1.0, 2.0, 3.0], 60)
    assert [c.start - T0 for c in found] == [0, 120]


def test_no_prices_make_no_candles_and_a_length_is_at_least_a_second() -> None:
    assert candles_from_ticks([], [], 60) == []
    with pytest.raises(ValueError, match="at least 1 second"):
        candles_from_ticks([T0], [1.0], 0)
