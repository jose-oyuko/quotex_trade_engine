"""Consolidations, breakouts and trends, found one candle at a time (decision D-85).

**Consolidation.** The last `candles` candles match the chosen pattern:
- `alternating` (the owner's): every candle the opposite colour of the one before; a candle that
  closes where it opened ends the run;
- `mixed`: the same, but `misses` candles of the window may fail to alternate;
- `tight`: the window's high to low is at most `width` times the average candle (high to low) of
  the `AVERAGE_OF` candles before it;
- `overlap`: every candle opens and closes inside the high and low of the one before;
- `choppy`: the window's net move (first open to last close) is at most `net_share` of all its
  candles' moves added up.
Its range is the window's lowest low to highest high. Every candle after it belongs to the
consolidation until the breakout; one that stays inside while the pattern goes on matching widens
the range with its wicks (and those of any candles beyond the range just before it).

**Breakout.** `breakout_candles` candles in a row beyond the range on the same side: their close
(`close`) or any part of them (`touch`, and not the other side too). A candle beyond the range
counts towards the breakout even when it still matches the pattern (a sell candle closing below
the range after a buy candle). The consolidation ends where they begin.

**Trend.** From the breakout until the next consolidation: it ends where that consolidation's
first candle starts, and that is known when the pattern completes (`stopped`). Detection starts
afresh after a breakout: the next consolidation is made of candles after it.

**Gaps.** A missing candle ends whatever was going on; nothing is guessed across it.

**Never looking ahead.** Everything is decided with the candles up to the current one, so feeding
the candles one by one finds exactly what a whole period does, and the live engine can run this.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from app.market.candles import DOWN, EQUAL, UP, Candle

AVERAGE_OF = 50  # `tight`: candles before the window that give the average candle
MIN_AVERAGE = 20  # ... and how many of them are needed before `tight` can match
MAX_CANDLES = 50

Direction = Literal["up", "down"]
ConsolidationEnd = Literal["breakout", "gap", "end"]
TrendEnd = Literal["consolidation", "gap", "end"]


class Pattern(StrEnum):
    ALTERNATING = "alternating"
    MIXED = "mixed"
    TIGHT = "tight"
    OVERLAP = "overlap"
    CHOPPY = "choppy"


class BreakBy(StrEnum):
    CLOSE = "close"
    TOUCH = "touch"


@dataclass(frozen=True, slots=True)
class MarketRules:
    """What counts as a consolidation and a breakout. Raises ValueError when out of bounds."""

    pattern: Pattern = Pattern.ALTERNATING
    candles: int = 5
    misses: int = 1  # `mixed` only
    width: float = 2.0  # `tight` only
    net_share: float = 0.2  # `choppy` only
    breakout_candles: int = 2
    breakout_by: BreakBy = BreakBy.CLOSE

    def __post_init__(self) -> None:
        if not 2 <= self.candles <= MAX_CANDLES:
            raise ValueError(f"a pattern needs 2 to {MAX_CANDLES} candles, got {self.candles}")
        if not 1 <= self.breakout_candles <= 10:
            raise ValueError(f"a breakout needs 1 to 10 candles, got {self.breakout_candles}")
        if self.pattern is Pattern.MIXED and not 0 <= self.misses <= self.candles - 2:
            raise ValueError(
                f"`mixed` allows 0 to {self.candles - 2} misses in {self.candles} candles, "
                f"got {self.misses}"
            )
        if self.pattern is Pattern.TIGHT and not 0 < self.width <= 20:
            raise ValueError(f"`tight` needs a width above 0 and at most 20, got {self.width}")
        if self.pattern is Pattern.CHOPPY and not 0 < self.net_share < 1:
            raise ValueError(f"`choppy` needs a net share between 0 and 1, got {self.net_share}")


# A sensible starting point for each pattern (Phase 29 report, section 8).
PATTERN_DEFAULTS: dict[Pattern, MarketRules] = {
    Pattern.ALTERNATING: MarketRules(Pattern.ALTERNATING, candles=5),
    Pattern.MIXED: MarketRules(Pattern.MIXED, candles=6, misses=1),
    Pattern.TIGHT: MarketRules(Pattern.TIGHT, candles=8, width=2.0),
    Pattern.OVERLAP: MarketRules(Pattern.OVERLAP, candles=4),
    Pattern.CHOPPY: MarketRules(Pattern.CHOPPY, candles=10, net_share=0.2),
}


@dataclass(frozen=True, slots=True)
class Breakout:
    start: int  # the first breakout candle's start
    known: int  # the end of the last one: when the breakout was known
    direction: Direction
    level: float  # the range's high (up) or low (down) that was broken
    close: float  # the close of the last breakout candle


@dataclass(slots=True)
class Consolidation:
    first: int  # its first candle's start
    found: int  # when the pattern was complete (the end of its last candle)
    end: int  # the end of its last candle: the breakout's start, a gap, or the end of the data
    high: float
    low: float
    breakout: Breakout | None = None
    ended: ConsolidationEnd | None = None


@dataclass(frozen=True, slots=True)
class Trend:
    start: int  # the breakout was known: the next candle's start
    end: int  # the next consolidation's first candle, a gap, or the end of the data
    stopped: int  # when its end was known
    direction: Direction
    open: float  # the breakout's close
    close: float  # the price where it ended
    ended: TrendEnd

    @property
    def move(self) -> float:
        """How far the price went in the breakout's direction (negative: against it)."""
        return self.close - self.open if self.direction == "up" else self.open - self.close


@dataclass(slots=True)
class Found:
    length: int
    consolidations: list[Consolidation] = field(default_factory=list)
    trends: list[Trend] = field(default_factory=list)


class Detector:
    """Feed it candles in time order; read what it found from `found`."""

    def __init__(self, rules: MarketRules, length: int) -> None:
        if length <= 0:
            raise ValueError(f"a candle lasts at least 1 second, got {length}")
        self.rules = rules
        self.found = Found(length)
        self._length = length
        self._window: deque[Candle] = deque()
        self._sizes: deque[float] = deque(maxlen=AVERAGE_OF)
        self._prev: Candle | None = None
        self._open: Consolidation | None = None
        self._trend: tuple[Breakout, Consolidation] | None = None
        self._run: list[Candle] = []
        self._run_way = 0
        self._finished = False

    @property
    def state(self) -> Literal["searching", "consolidating", "trending"]:
        if self._open is not None:
            return "consolidating"
        return "searching" if self._trend is None else "trending"

    def feed(self, candle: Candle) -> None:
        if self._finished:
            raise RuntimeError("the detector was finished")
        prev = self._prev
        if prev is not None:
            if candle.start < prev.start + self._length:
                raise ValueError("candles must come in time order, one per period")
            if candle.start != prev.start + self._length:
                self._close(prev.start + self._length, prev.close, "gap")
        self._prev = candle
        self._push(candle)
        matched = self._matches()
        cons = self._open
        if cons is None:
            if matched:
                self._found(candle)
            return
        cons.end = candle.start + self._length
        way = self._beyond(candle, cons)
        if way:  # beyond the range: towards a breakout, even if it still alternates
            if self._run and way != self._run_way:
                self._run.clear()
            self._run.append(candle)
            self._run_way = way
            if len(self._run) >= self.rules.breakout_candles:
                self._break(candle, cons)
            return
        if matched:  # back inside and still matching: the range takes in the candles' wicks
            for c in (*self._run, candle):
                cons.high = max(cons.high, c.high)
                cons.low = min(cons.low, c.low)
        self._run.clear()

    def finish(self) -> Found:
        """Close what is still going on at the end of the data (`ended="end"`)."""
        if not self._finished and self._prev is not None:
            self._close(self._prev.start + self._length, self._prev.close, "end")
        self._finished = True
        return self.found

    # --- what happens ---

    def _found(self, candle: Candle) -> None:
        first = self._window[0]
        cons = Consolidation(
            first=first.start,
            found=candle.start + self._length,
            end=candle.start + self._length,
            high=max(c.high for c in self._window),
            low=min(c.low for c in self._window),
        )
        if self._trend is not None:
            breakout, _ = self._trend
            self.found.trends.append(
                Trend(
                    start=breakout.known,
                    end=max(first.start, breakout.known),
                    stopped=cons.found,
                    direction=breakout.direction,
                    open=breakout.close,
                    close=first.open,
                    ended="consolidation",
                )
            )
            self._trend = None
        self._open = cons
        self._run.clear()

    def _break(self, candle: Candle, cons: Consolidation) -> None:
        up = self._run_way == UP
        breakout = Breakout(
            start=self._run[0].start,
            known=candle.start + self._length,
            direction="up" if up else "down",
            level=cons.high if up else cons.low,
            close=candle.close,
        )
        cons.end = breakout.start
        cons.breakout = breakout
        cons.ended = "breakout"
        self.found.consolidations.append(cons)
        self._open = None
        self._trend = (breakout, cons)
        self._run.clear()
        while self._window:  # the next consolidation is made of candles after the breakout
            self._sizes.append(self._window.popleft().size)

    def _close(self, at: int, price: float, why: Literal["gap", "end"]) -> None:
        if self._open is not None:
            self._open.ended = why
            self.found.consolidations.append(self._open)
            self._open = None
        if self._trend is not None:
            breakout, _ = self._trend
            self.found.trends.append(
                Trend(
                    start=breakout.known,
                    end=max(at, breakout.known),
                    stopped=max(at, breakout.known),
                    direction=breakout.direction,
                    open=breakout.close,
                    close=price,
                    ended=why,
                )
            )
            self._trend = None
        self._run.clear()
        self._window.clear()
        if why == "gap":
            self._sizes.clear()

    # --- the patterns ---

    def _push(self, candle: Candle) -> None:
        self._window.append(candle)
        if len(self._window) > self.rules.candles:
            self._sizes.append(self._window.popleft().size)

    def _matches(self) -> bool:
        return matches(self._window, self.rules, self._sizes)

    def _beyond(self, candle: Candle, cons: Consolidation) -> int:
        """`UP` or `DOWN` when the candle is beyond the range on that side, else 0."""
        if self.rules.breakout_by is BreakBy.CLOSE:
            if candle.close > cons.high:
                return UP
            return DOWN if candle.close < cons.low else 0
        above, below = candle.high > cons.high, candle.low < cons.low
        if above == below:
            return 0
        return UP if above else DOWN


def matches(window: Sequence[Candle], rules: MarketRules, sizes: Sequence[float]) -> bool:
    """Whether the last `rules.candles` candles of `window` match the pattern. `sizes`: the sizes
    of the candles before the window (`tight` only)."""
    if len(window) < rules.candles:
        return False
    window = list(window)[-rules.candles :]
    match rules.pattern:
        case Pattern.ALTERNATING:
            return window[0].colour != EQUAL and all(
                b.colour == -a.colour for a, b in pairwise(window)
            )
        case Pattern.MIXED:
            changes = sum(
                1 for a, b in pairwise(window) if b.colour != EQUAL and b.colour == -a.colour
            )
            return changes >= rules.candles - 1 - rules.misses
        case Pattern.TIGHT:
            if len(sizes) < MIN_AVERAGE:
                return False
            average = sum(sizes) / len(sizes)
            span = max(c.high for c in window) - min(c.low for c in window)
            return average > 0 and span <= rules.width * average
        case Pattern.OVERLAP:
            return all(
                a.low <= min(b.open, b.close) and max(b.open, b.close) <= a.high
                for a, b in pairwise(window)
            )
        case Pattern.CHOPPY:
            total = sum(abs(c.close - c.open) for c in window)
            net = abs(window[-1].close - window[0].open)
            return total > 0 and net <= rules.net_share * total


def scan(candles: Iterable[Candle], rules: MarketRules, length: int) -> Found:
    """Every consolidation, breakout and trend in a run of candles."""
    detector = Detector(rules, length)
    for candle in candles:
        detector.feed(candle)
    return detector.finish()
