"""Candles of any length from prices (decision D-85).

A candle covers `length` seconds aligned on the epoch, like a session's candles: M1 candles start at
:00 of every minute, M5 at :00, :05, :10 ... Its open is the first price inside it and its close the
last. A period without any price has no candle: a gap is never filled in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

UP, DOWN, EQUAL = 1, -1, 0


@dataclass(frozen=True, slots=True)
class Candle:
    start: int  # epoch seconds of its first second
    open: float
    high: float
    low: float
    close: float
    ticks: int  # prices inside it

    @property
    def colour(self) -> int:
        """`UP` (a buy candle), `DOWN` (a sell candle) or `EQUAL` (closed where it opened)."""
        if self.close > self.open:
            return UP
        if self.close < self.open:
            return DOWN
        return EQUAL

    @property
    def size(self) -> float:
        """From its low to its high."""
        return self.high - self.low


def candles_from_ticks(times: Sequence[int], quotes: Sequence[float], length: int) -> list[Candle]:
    """The candles of `length` seconds made from prices sorted by time."""
    if length <= 0:
        raise ValueError(f"a candle lasts at least 1 second, got {length}")
    found: list[Candle] = []
    start = -1
    open_ = high = low = close = 0.0
    ticks = 0
    for epoch, quote in zip(times, quotes, strict=True):
        begins = epoch - epoch % length
        if begins != start:
            if ticks:
                found.append(Candle(start, open_, high, low, close, ticks))
            start, open_, high, low, ticks = begins, quote, quote, quote, 0
        high = max(high, quote)
        low = min(low, quote)
        close = quote
        ticks += 1
    if ticks:
        found.append(Candle(start, open_, high, low, close, ticks))
    return found
