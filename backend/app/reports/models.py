"""What the reports compute, as plain values (no framework). `queries.py` fills them from the
database; the API turns them into JSON; the CSV writer turns them into rows.

Definitions used everywhere (decision D-47):
- A trade is **resolved** when its result is known: won, lost or draw. Only resolved trades have a
  profit, and only resolved trades count in profit, win rate and the like. Failed, unknown and open
  trades are reported separately (`NotCounted`) so the owner can see what is missing.
- **Profit** is the figure stored on the trade: positive for a win, negative for a loss.
- **Win rate** is wins divided by resolved trades. **ROI** is profit divided by the money staked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from app.domain.enums import AccountType, Strategy

# How much data it takes before a number means anything. Below TINY a win rate is noise; below SMALL
# it is a hint at best. The dashboard repeats these words next to the numbers.
SAMPLE_TINY = 10
SAMPLE_SMALL = 30

type Sample = Literal["tiny", "small", "ok"]


def sample_of(trades: int) -> Sample:
    if trades < SAMPLE_TINY:
        return "tiny"
    return "small" if trades < SAMPLE_SMALL else "ok"


MAX_UTC_OFFSET_MINUTES = 14 * 60


@dataclass(slots=True, frozen=True)
class ReportFilter:
    """Which trades a report looks at. Demo and real are never mixed: `account_type` is required.

    `since` is inclusive and `until` exclusive. Trades are placed in the range by the time they
    settled (chains by the time they started). `utc_offset_minutes` shifts the clock used for
    "hour of day", "weekday" and the daily series; it is a fixed offset, so a zone that observes
    daylight saving is off by an hour for part of the year.
    """

    account_type: AccountType
    since: datetime | None = None
    until: datetime | None = None
    group_id: int | None = None
    strategy: Strategy | None = None
    asset: str | None = None
    utc_offset_minutes: int = 0

    def __post_init__(self) -> None:
        if abs(self.utc_offset_minutes) > MAX_UTC_OFFSET_MINUTES:
            raise ValueError("utc_offset_minutes must be between -840 and 840")
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("the start of the range must be before its end")


class BreakdownKind(StrEnum):
    GROUP = "group"
    ASSET = "asset"
    STRATEGY = "strategy"
    HOUR = "hour"
    WEEKDAY = "weekday"


@dataclass(slots=True, frozen=True)
class Metrics:
    trades: int  # resolved trades
    wins: int
    losses: int
    draws: int
    profit: Decimal
    staked: Decimal
    avg_payout_pct: float | None  # over the trades that recorded a payout

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.trades if self.trades else None

    @property
    def roi(self) -> float | None:
        return float(self.profit / self.staked) if self.staked else None

    @property
    def avg_stake(self) -> Decimal | None:
        return (self.staked / self.trades).quantize(Decimal("0.01")) if self.trades else None

    @property
    def sample(self) -> Sample:
        return sample_of(self.trades)


EMPTY_METRICS = Metrics(0, 0, 0, 0, Decimal(0), Decimal(0), None)


@dataclass(slots=True, frozen=True)
class BreakdownRow:
    key: str
    label: str
    metrics: Metrics


@dataclass(slots=True, frozen=True)
class NotCounted:
    """Trades in the range whose result is not known, so they are in no profit figure."""

    failed: int
    unknown: int
    open: int


@dataclass(slots=True, frozen=True)
class Streaks:
    longest_win: int
    longest_loss: int
    current: int  # positive: this many wins in a row now; negative: this many losses; 0: none yet


@dataclass(slots=True, frozen=True)
class Drawdown:
    """The biggest fall of the running total from a high point to a later low point."""

    max_amount: Decimal  # zero or positive
    peak_day: str | None  # local day (YYYY-MM-DD) of the high point
    trough_day: str | None
    current_amount: Decimal  # how far below its high point the total is now


Verdict = Literal[
    "not_enough_data", "consistent_with_break_even", "above_break_even", "below_break_even"
]


@dataclass(slots=True, frozen=True)
class Expectation:
    """Is the win rate really better than chance? With a payout of p, a trade wins back p of its
    stake and loses all of it, so it breaks even at 1/(1+p). A strategy cannot beat that on average
    by changing stake sizes: only the win rate matters. `z_score` says how many standard errors the
    actual win rate is from break-even; beyond +/-2 it is unlikely to be luck."""

    breakeven_win_rate: float | None
    actual_win_rate: float | None
    edge: float | None  # actual minus break-even
    z_score: float | None
    verdict: Verdict


def expectation_of(wins: int, losses: int, avg_payout_pct: float | None) -> Expectation:
    decided = wins + losses
    if decided == 0 or avg_payout_pct is None or avg_payout_pct <= 0:
        return Expectation(None, None, None, None, "not_enough_data")
    breakeven = 1 / (1 + avg_payout_pct / 100)
    actual = wins / decided
    z = (actual - breakeven) / math.sqrt(breakeven * (1 - breakeven) / decided)
    if decided < SAMPLE_SMALL:
        verdict: Verdict = "not_enough_data"
    elif z >= 2:
        verdict = "above_break_even"
    elif z <= -2:
        verdict = "below_break_even"
    else:
        verdict = "consistent_with_break_even"
    return Expectation(breakeven, actual, actual - breakeven, z, verdict)


@dataclass(slots=True, frozen=True)
class Summary:
    metrics: Metrics
    not_counted: NotCounted
    streaks: Streaks
    drawdown: Drawdown
    expectation: Expectation
    first_day: str | None
    last_day: str | None


@dataclass(slots=True, frozen=True)
class EquityPoint:
    day: str  # local day, YYYY-MM-DD
    trades: int
    profit: Decimal  # that day's result
    cumulative: Decimal  # running total at the end of the day


@dataclass(slots=True, frozen=True)
class DepthRow:
    """One step of the chains. `step` counts from 1: trade 1 is the original signal's trade."""

    step: int
    chains_reaching: int
    share_of_chains: float
    trades: int
    wins: int
    losses: int
    staked: Decimal
    profit: Decimal  # of the trades placed at this step
    chains_ending_here: int
    chains_won_here: int  # chains whose last trade was this one and won
    chain_profit_ending_here: Decimal  # whole-chain result of the chains that ended at this step


@dataclass(slots=True, frozen=True)
class DepthReport:
    chains: int  # chains with at least one resolved trade
    completed: int
    exhausted: int
    other: int  # stopped, failed, unknown
    avg_chain_profit: Decimal | None
    steps: list[DepthRow] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ExportRow:
    """One trade as written to the CSV file. Everything is already text (money with a dot, times in
    UTC), because a long history is millions of cells and converting each one twice is waste."""

    created_at: str
    settled_at: str
    account_type: str
    group_id: int
    group_title: str
    strategy: str
    asset: str
    direction: str
    step: int  # from 1
    duration_s: int
    stake: str
    payout_pct: int | None
    status: str
    profit: str
    error: str | None
    trade_id: str
    chain_id: str
