"""What the consolidations and trends of a period add up to (decision D-85), and the comparisons
that decide whether trading only the trends could help.

**Flip chains and alternating candles.** A pair is two chains, Rise and Fall, on one candle with
`flip_every_loss`. One of them loses the first trade, flips to the candle's colour and, from then
on, loses every trade while the candles alternate (an equal candle loses too). So a pair started
on a candle goes as deep as the alternation that follows it, and these figures count it from the
candles' colours alone. This is an approximation of a real trade (a trade's entry is the first
price after it is bought, not the candle's open): the backtests replay the real thing.

**Fair comparisons.**
- *Waiting:* after a breakout the detector starts afresh, so the candles until the next
  consolidation is found are compared with the same count from any candle, also started afresh.
- *Deep pairs:* pairs started while trending, against pairs started at any candle.
- Every share comes with its 95% range (Wilson), so a difference within that range is noise.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from app.market.candles import EQUAL, Candle
from app.market.detector import (
    AVERAGE_OF,
    PATTERN_DEFAULTS,
    Found,
    MarketRules,
    Pattern,
    matches,
    scan,
)

DEEP = 6  # trades lost in a row that count as a deep pair
MAX_TRADES = 9  # a flip chain is followed at most this far
PAYOUT = 0.88
BREAK_EVEN = 1 / (1 + PAYOUT)  # the share of wins that pays for the losses: 53.2%


@dataclass(frozen=True, slots=True)
class Spread:
    """A count of candles: how many, the average, median, quartiles and the longest."""

    count: int
    mean: float
    median: float
    q1: float
    q3: float
    longest: int


@dataclass(frozen=True, slots=True)
class Rate:
    hits: int
    total: int

    @property
    def share(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def low(self) -> float:
        return _wilson(self.hits, self.total)[0]

    @property
    def high(self) -> float:
        return _wilson(self.hits, self.total)[1]


@dataclass(frozen=True, slots=True)
class MarketStats:
    candles: int
    consolidations: int
    breakouts: int
    in_consolidation: float  # share of candles inside a consolidation
    trend_wait: Spread  # candles from a breakout until the next consolidation was found
    any_wait: Spread  # the same from any candle
    first_with: Rate  # the candle after a breakout went the breakout's way
    trend_with: Rate  # the candles of the trends that went the breakout's way
    deep: int  # trades lost in a row that make a pair deep
    deep_any: Rate  # pairs started at any candle that went deep
    deep_trend: Rate  # ... started while trending
    deep_consolidation: Rate  # ... started while a consolidation was known
    described: Rate  # candles of deep stretches that lie inside a consolidation


def spread(values: Sequence[int]) -> Spread:
    if not values:
        return Spread(0, 0.0, 0.0, 0.0, 0.0, 0)
    ordered = sorted(values)
    if len(ordered) == 1:
        q1 = q3 = float(ordered[0])
    else:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    return Spread(
        count=len(ordered),
        mean=statistics.fmean(ordered),
        median=float(statistics.median(ordered)),
        q1=q1,
        q3=q3,
        longest=ordered[-1],
    )


def _wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    p = hits / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def _segments(candles: Sequence[Candle], length: int) -> list[int]:
    """For each candle, the number of the gap-free run it belongs to."""
    seg: list[int] = []
    for i, c in enumerate(candles):
        new = i > 0 and c.start != candles[i - 1].start + length
        seg.append((seg[-1] + (1 if new else 0)) if seg else 0)
    return seg


def flip_depth(candles: Sequence[Candle], seg: Sequence[int], i: int) -> int | None:
    """Trades lost in a row by the worse leg of a flip pair opened on candle `i` (0 to
    `MAX_TRADES`), or None when the data ends (or a gap comes) before it is settled."""
    worst = 0
    for way in (1, -1):
        lost = 0
        for j in range(i, i + MAX_TRADES):
            if j >= len(candles) or seg[j] != seg[i]:
                return None
            colour = candles[j].colour
            if colour != EQUAL and colour == way:
                break
            lost += 1
            way = -way
        worst = max(worst, lost)
    return worst


def _fresh_waits(
    candles: Sequence[Candle], seg: Sequence[int], rules: MarketRules
) -> list[int | None]:
    """For each candle: candles until the pattern is complete using only candles from it on
    (None: a gap or the end comes first)."""
    n, size = len(candles), rules.candles
    complete = [False] * n  # the window ending at this candle matches
    sizes: deque[float] = deque(maxlen=AVERAGE_OF)
    for t in range(n):
        if t > 0 and seg[t] != seg[t - 1]:
            sizes.clear()
        start = t - size + 1
        if start >= 0 and seg[start] == seg[t]:
            complete[t] = matches(candles[start : t + 1], rules, sizes)
            sizes.append(candles[start].size)
    waits: list[int | None] = [None] * n
    following: int | None = None  # the next complete window's last candle, from the end back
    for t in range(n - 1, -1, -1):
        if t + 1 < n and seg[t + 1] != seg[t]:
            following = None
        if complete[t]:
            following = t
        # from candle s, the first window that fits is the one ending at s + size - 1
        s = t - size + 1
        if s >= 0 and seg[s] == seg[t] and following is not None:
            waits[s] = following - s + 1
    return waits


def market_stats(
    candles: Sequence[Candle], found: Found, rules: MarketRules, *, deep: int = DEEP
) -> MarketStats:
    length = found.length
    seg = _segments(candles, length)
    index = {c.start: i for i, c in enumerate(candles)}
    n = len(candles)

    inside = [False] * n  # inside a consolidation, from its first candle to its end
    known = [False] * n  # a consolidation is known: from when it was found to its end
    for cons in found.consolidations:
        for start in range(cons.first, cons.end, length):
            i = index.get(start)
            if i is not None:
                inside[i] = True
                known[i] = known[i] or start >= cons.found
    trending = [False] * n  # from the breakout until the next consolidation was found
    for trend in found.trends:
        for start in range(trend.start, trend.stopped, length):
            i = index.get(start)
            if i is not None:
                trending[i] = True

    depths = [flip_depth(candles, seg, i) for i in range(n)]
    deep_any = deep_trend = deep_cons = (0, 0)
    stretched = [False] * n  # a candle of a stretch that took a pair deep
    for i, d in enumerate(depths):
        if d is None:
            continue
        hit = d >= deep
        deep_any = (deep_any[0] + hit, deep_any[1] + 1)
        if trending[i]:
            deep_trend = (deep_trend[0] + hit, deep_trend[1] + 1)
        if known[i]:
            deep_cons = (deep_cons[0] + hit, deep_cons[1] + 1)
        if hit:
            for j in range(i, min(i + d, n)):
                stretched[j] = True
    described = sum(1 for i in range(n) if stretched[i] and inside[i])

    first_with = trend_with = (0, 0)
    for trend in found.trends:
        way = 1 if trend.direction == "up" else -1
        i = index.get(trend.start)
        if i is not None and trend.end > trend.start:
            first_with = (first_with[0] + (candles[i].colour == way), first_with[1] + 1)
        for start in range(trend.start, trend.end, length):
            k = index.get(start)
            if k is not None:
                trend_with = (trend_with[0] + (candles[k].colour == way), trend_with[1] + 1)

    waits = _fresh_waits(candles, seg, rules)
    return MarketStats(
        candles=n,
        consolidations=len(found.consolidations),
        breakouts=sum(1 for c in found.consolidations if c.breakout is not None),
        in_consolidation=sum(inside) / n if n else 0.0,
        trend_wait=spread(
            [(t.stopped - t.start) // length for t in found.trends if t.ended == "consolidation"]
        ),
        any_wait=spread([w for w in waits if w is not None]),
        first_with=Rate(*first_with),
        trend_with=Rate(*trend_with),
        deep=deep,
        deep_any=Rate(*deep_any),
        deep_trend=Rate(*deep_trend),
        deep_consolidation=Rate(*deep_cons),
        described=Rate(described, sum(stretched)),
    )


def compare(
    candles: Sequence[Candle], length: int, *, deep: int = DEEP
) -> list[tuple[MarketRules, MarketStats]]:
    """Every pattern with its default settings, on the same candles."""
    return [
        (rules, market_stats(candles, scan(candles, rules, length), rules, deep=deep))
        for rules in (PATTERN_DEFAULTS[p] for p in Pattern)
    ]
