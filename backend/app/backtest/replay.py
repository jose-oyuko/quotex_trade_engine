"""A trading session replayed on stored prices (decision D-84). Pure and synchronous: it is run in
a worker thread, reads nothing but the prices it is given, and the same prices and setup always
give the same result.

**The rules are the live ones.** Each leg of a pair is a chain run by the engine's own `Chain`
(and so by `app/engine/strategies.py`): step directions, stakes, the end of a chain. The session's
pairs follow the scheduler's rules (docs/DOMAIN.md, "Trading sessions"): the windows of
`app/sessions/schedule.py`, a pair at the start of the window, then one pair at a time
(`sequential`) or a pair at every candle up to a number open at once (`every_candle`); a profit
target, loss limit or maximum number of pairs stops new pairs and lets the running chains finish.

**A trade is decided like Deriv does (D-82).** The contract starts at the purchase second; the
entry is the first price after it; the end is the start plus the trade length; the exit is the
latest price at or before the end. Rise wins when the exit is strictly above the entry, Fall
strictly below; equal loses. A win pays `stake x payout %`.

**Timing.** An order is bought `order_delay_s` after the moment it is decided (a candle, or the
previous trade's end plus `step_delay_s`), as measured live. A result is known `RESULT_AFTER_S`
after the end, which is when the next candle sees the pair as still open.

**What is not guessed.** A trade whose seconds were not downloaded, or that has no price in them,
is not decided: a pair whose first trades lack prices is not opened (`no_data_rounds`), and a chain
whose next step lacks them ends there (`failed`, "no price data").

**Opening after a breakout (decision D-85, Phase 31).** Instead of all through the window, pairs
may open only while a trend is on. The detector of `app/market/detector.py` reads candles of the
trade length made from the same prices, from `WARMUP_CANDLES` before a period's first window. A
trend starts when its breakout is known (the end of the last breakout candle, never earlier) and
stops when the next consolidation is known or after `trend_max_candles`, whichever is first. Inside
a window pairs open as the session's mode says, only in those stretches; running chains finish,
then it waits for the next breakout. A stretch already going on when a window opens is traded from
the window's start.

**Runs.** Every strategy is replayed with every chosen way of opening, on each period: a second
period (`check_first_day` to `check_last_day`) judges settings chosen on the first.
"""

from __future__ import annotations

import heapq
import math
import threading
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from app.brokers.base import TradeOutcome
from app.domain.enums import (
    AccountType,
    Broker,
    ChainStatus,
    Direction,
    RepeatKind,
    SessionMode,
    Strategy,
)
from app.domain.records import SessionRecord
from app.engine.chain import Chain, ChainSpec
from app.market.candles import candles_from_ticks
from app.market.detector import MarketRules, scan
from app.sessions.schedule import Window, local_date, next_boundary, windows_between

CENT = Decimal("0.01")
RESULT_AFTER_S = 0.5  # a result is known this long after a trade's end
ON_BOUNDARY_S = 5  # the scheduler: within 5 s after a candle boundary counts as on it
EQUITY_POINTS = 400  # the profit curve is thinned to about this many points
_NOW = datetime(1970, 1, 1, tzinfo=UTC)  # the chains' own clock is not used here
_NO_ID = UUID(int=0)
WARMUP_CANDLES = 100  # candles before a period's first window that the detector reads first
MAX_RUNS = 12  # strategies x ways of opening x periods


class OpenRule(StrEnum):
    """When a backtest opens pairs."""

    WINDOW = "window"  # all through the window, like a session today
    BREAKOUT = "breakout"  # only while a trend is on, after a breakout


@dataclass(slots=True, frozen=True)
class Run:
    """One strategy replayed one way on one period (1, or 2: the period that judges)."""

    strategy: int  # index into the setup's strategies
    opens: OpenRule
    period: int


class Cancelled(Exception):
    """The owner cancelled the backtest."""


@dataclass(slots=True, frozen=True)
class StrategySetup:
    strategy: Strategy
    max_steps: int
    multipliers: tuple[Decimal, ...]


@dataclass(slots=True, frozen=True)
class BacktestSetup:
    """A session-shaped setup (the fields mean what they mean on a session), the days to replay,
    the strategies to compare, and the assumptions."""

    asset: str
    first_day: date  # local days in `timezone`, both included
    last_day: date
    start_time: time
    end_time: time
    timezone: str
    weekdays: tuple[int, ...]
    duration_s: int
    mode: SessionMode
    pause_s: int
    max_open_pairs: int
    max_pairs: int | None  # per window
    profit_target: Decimal | None  # per window
    loss_limit: Decimal | None  # per window
    base_stake: Decimal
    strategies: tuple[StrategySetup, ...]
    payout_pct: Decimal = Decimal(88)
    order_delay_s: float = 0.5
    step_delay_s: float = 1.0
    opens: tuple[OpenRule, ...] = (OpenRule.WINDOW,)
    market: MarketRules = field(default_factory=MarketRules)
    trend_max_candles: int | None = 20  # None: until the next consolidation only
    check_first_day: date | None = None  # the second period, which judges the settings
    check_last_day: date | None = None

    def periods(self) -> list[tuple[date, date]]:
        """The first period, and the second one when there is one."""
        found = [(self.first_day, self.last_day)]
        if self.check_first_day is not None and self.check_last_day is not None:
            found.append((self.check_first_day, self.check_last_day))
        return found

    def runs(self) -> list[Run]:
        """Period by period, way by way, strategy by strategy."""
        return [
            Run(index, opens, period)
            for period in range(1, len(self.periods()) + 1)
            for opens in self.opens
            for index in range(len(self.strategies))
        ]

    def all_windows(self) -> list[Window]:
        """The windows of every period, oldest period first."""
        return [w for period in range(1, len(self.periods()) + 1) for w in self.windows(period)]

    def windows(self, period: int = 1) -> list[Window]:
        """The session windows that start on the days of a period."""
        first_day, last_day = self.periods()[period - 1]
        session = SessionRecord(
            name="backtest",
            enabled=True,
            group_id=0,
            asset=self.asset,
            duration_s=self.duration_s,
            start_time=self.start_time,
            end_time=self.end_time,
            timezone=self.timezone,
            repeat=RepeatKind.WEEKDAYS,
            weekdays=self.weekdays,
            pause_s=self.pause_s,
            created_at=_NOW,
            updated_at=_NOW,
            once_after=_NOW,
        )
        # from a day before to two days after: a zone ahead of or behind UTC still finds the
        # windows of its first and last local days
        since = datetime.combine(first_day, time(0), tzinfo=UTC) - timedelta(days=1)
        until = datetime.combine(last_day, time(0), tzinfo=UTC) + timedelta(days=2)
        return [
            w
            for w in windows_between(session, since, until)
            if first_day <= local_date(w.start, self.timezone) <= last_day
        ]


# ---- prices ------------------------------------------------------------------------------------


@dataclass(slots=True)
class Prices:
    """The stored prices of one asset, oldest first, and the seconds that were downloaded."""

    times: Sequence[int]
    quotes: Sequence[float]
    covered: Sequence[tuple[int, int]]  # merged, oldest first
    _starts: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._starts = [a for a, _ in self.covered]

    def downloaded(self, start: int, end: int) -> bool:
        i = bisect_right(self._starts, start) - 1
        return i >= 0 and self.covered[i][1] >= end

    def entry_exit(self, start: int, end: int) -> tuple[float, float] | None:
        """Deriv's entry (the first price after `start`) and exit (the latest at or before
        `end`), or None when that cannot be known from what was downloaded."""
        if not self.downloaded(start, end):
            return None
        first = bisect_right(self.times, start)
        last = bisect_right(self.times, end) - 1
        if first > last:
            return None
        return self.quotes[first], self.quotes[last]


# ---- one chain ---------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SimTrade:
    start: int  # the contract's start second
    end: int
    direction: Direction
    stake: Decimal
    entry: float
    exit: float
    profit: Decimal

    @property
    def won(self) -> bool:
        return self.profit > 0


@dataclass(slots=True)
class SimChain:
    strategy: int  # index into the setup's strategies
    day: date
    pair_no: int
    origin: Direction
    status: ChainStatus
    end_reason: str
    trades: list[SimTrade]
    run: int = 0  # index into the setup's runs

    @property
    def profit(self) -> Decimal:
        return sum((t.profit for t in self.trades), Decimal(0))

    @property
    def known_at(self) -> float:
        """When the chain's last result was known."""
        return self.trades[-1].end + RESULT_AFTER_S

    @property
    def started(self) -> int:
        return self.trades[0].start


def decide(
    prices: Prices,
    direction: Direction,
    stake: Decimal,
    bought_at: float,
    setup: BacktestSetup,
) -> SimTrade | None:
    start = math.floor(bought_at)
    end = start + setup.duration_s
    found = prices.entry_exit(start, end)
    if found is None:
        return None
    entry, exit_ = found
    won = exit_ > entry if direction is Direction.CALL else exit_ < entry
    profit = (
        (stake * setup.payout_pct / 100).quantize(CENT, rounding=ROUND_HALF_UP) if won else -stake
    )
    return SimTrade(start, end, direction, stake, entry, exit_, profit)


def run_chain(
    prices: Prices,
    setup: BacktestSetup,
    index: int,
    origin: Direction,
    decided_at: float,
    *,
    day: date,
    pair_no: int,
) -> SimChain | None:
    """One leg, step after step, through the engine's own `Chain`. None if even its first trade
    has no price data (the pair is then not opened)."""
    strategy = setup.strategies[index]
    chain = Chain(
        ChainSpec(
            id=_NO_ID,
            group_id=0,
            signal_id=None,
            asset=setup.asset,
            origin_direction=origin,
            duration_s=setup.duration_s,
            account_type=AccountType.DEMO,
            strategy=strategy.strategy,
            base_stake=setup.base_stake,
            multipliers=strategy.multipliers,
            max_steps=strategy.max_steps,
            broker=Broker.DERIV,
        ),
        _NOW,
    )
    trades: list[SimTrade] = []
    plan = chain.plan()
    bought_at = decided_at + setup.order_delay_s
    while True:
        trade = decide(prices, plan.direction, plan.stake, bought_at, setup)
        if trade is None:
            if not trades:
                return None
            chain.fail("no price data", _NOW)
            break
        if not trades:
            chain.mark_open(_NOW)
        trades.append(trade)
        following = chain.apply_result(TradeOutcome.WON if trade.won else TradeOutcome.LOST, _NOW)
        if following is None:
            break
        plan = following
        bought_at = trade.end + setup.step_delay_s + setup.order_delay_s
    return SimChain(
        strategy=index,
        day=day,
        pair_no=pair_no,
        origin=origin,
        status=chain.status,
        end_reason=chain.end_reason or "",
        trades=trades,
    )


# ---- the trends ------------------------------------------------------------------------------


def trend_spans(
    prices: Prices, setup: BacktestSetup, first: int, last: int
) -> list[tuple[int, int]]:
    """When pairs may open after a breakout, between `first` and `last` (epoch seconds): from
    the moment each breakout is known until the next consolidation is known or
    `trend_max_candles` have passed. The detector reads the candles of the trade length one by
    one, from `WARMUP_CANDLES` before `first`."""
    length = setup.duration_s
    lo = bisect_left(prices.times, first - WARMUP_CANDLES * length)
    hi = bisect_right(prices.times, last)
    candles = candles_from_ticks(prices.times[lo:hi], prices.quotes[lo:hi], length)
    spans: list[tuple[int, int]] = []
    for trend in scan(candles, setup.market, length).trends:
        end = trend.stopped
        if setup.trend_max_candles is not None:
            end = min(end, trend.start + setup.trend_max_candles * length)
        if end > trend.start and end > first and trend.start < last:
            spans.append((trend.start, end))
    return spans


def _within(
    spans: Sequence[tuple[int, int]], start: float, end: float
) -> list[tuple[float, float]]:
    """The parts of `spans` inside `start`..`end`."""
    return [(max(a, start), min(b, end)) for a, b in spans if b > start and a < end]


# ---- one window --------------------------------------------------------------------------------


@dataclass(slots=True)
class WindowResult:
    chains: list[SimChain] = field(default_factory=list)
    pairs: int = 0
    skipped_rounds: int = 0  # every_candle: the limit of open pairs was reached
    no_data_rounds: int = 0
    stopped_by: str = "window_ended"
    spans: int = 0  # stretches in which pairs could open (the window itself, or its trends)
    active_s: float = 0  # their seconds in all


class _Run:
    """A window's running profit, checked as each result becomes known, in time order."""

    def __init__(self, setup: BacktestSetup) -> None:
        self.setup = setup
        self.profit = Decimal(0)
        self.pending: list[tuple[float, int, Decimal]] = []
        self.seq = 0
        self.stopped_by: str | None = None

    def add(self, chain: SimChain) -> None:
        for trade in chain.trades:
            self.seq += 1
            heapq.heappush(self.pending, (trade.end + RESULT_AFTER_S, self.seq, trade.profit))

    def until(self, moment: float) -> None:
        """Apply every result known by `moment`."""
        while self.pending and self.pending[0][0] <= moment:
            _, _, profit = heapq.heappop(self.pending)
            self.profit += profit
            if self.stopped_by is None:
                target, limit = self.setup.profit_target, self.setup.loss_limit
                if target is not None and self.profit >= target:
                    self.stopped_by = "profit_target"
                elif limit is not None and self.profit <= -limit:
                    self.stopped_by = "loss_limit"


def replay_window(
    prices: Prices,
    setup: BacktestSetup,
    index: int,
    window: Window,
    spans: Sequence[tuple[int, int]] | None = None,
) -> WindowResult:
    """One strategy in one window: all through it, or only in `spans` (the trends)."""
    result = WindowResult()
    run = _Run(setup)
    day = local_date(window.start, setup.timezone)
    start, end = window.start.timestamp(), window.end.timestamp()
    active = [(start, end)] if spans is None else _within(spans, start, end)
    length = setup.duration_s
    moment = start
    open_until: list[float] = []  # every_candle: when each opened pair is over

    def open_pair(at: float) -> list[SimChain] | None:
        legs = [
            run_chain(prices, setup, index, d, at, day=day, pair_no=result.pairs + 1)
            for d in (Direction.CALL, Direction.PUT)
        ]
        if any(leg is None for leg in legs):
            result.no_data_rounds += 1
            return None
        chains = [leg for leg in legs if leg is not None]
        result.pairs += 1
        result.chains.extend(chains)
        for chain in chains:
            run.add(chain)
        return chains

    for span_start, span_end in active:
        result.spans += 1
        result.active_s += span_end - span_start
        moment = max(moment, span_start)  # a pair still running from the last stretch: wait
        while moment < span_end:
            run.until(moment)
            if run.stopped_by is not None:
                result.stopped_by = run.stopped_by
                return result
            if setup.max_pairs is not None and result.pairs >= setup.max_pairs:
                result.stopped_by = "max_pairs"
                return result
            if setup.mode is SessionMode.EVERY_CANDLE:
                busy = sum(1 for t in open_until if t > moment)
                if busy >= setup.max_open_pairs:
                    result.skipped_rounds += 1
                else:
                    chains = open_pair(moment)
                    if chains is not None:
                        open_until.append(max(c.known_at for c in chains))
                moment = _next_candle(moment, length, after=True)
                continue
            chains = open_pair(moment)
            if chains is None:
                moment = _next_candle(moment, length, after=True)
                continue
            over = max(c.known_at for c in chains) + setup.pause_s
            moment = _next_candle(over, length)
    return result


def _next_candle(moment: float, length_s: int, *, after: bool = False) -> float:
    """The scheduler's next pair time: on a candle boundary (within 5 s after one counts)."""
    if not after:
        boundary = math.floor(moment / length_s) * length_s
        if moment - boundary <= ON_BOUNDARY_S:
            return moment
    at = datetime.fromtimestamp(moment, UTC)
    return next_boundary(at, length_s, after=after).timestamp()


# ---- the whole backtest ------------------------------------------------------------------------


@dataclass(slots=True)
class Totals:
    """What a strategy did over the whole backtest."""

    windows: int = 0
    pairs: int = 0
    chains: int = 0
    trades: int = 0
    trades_won: int = 0
    won_at_step: list[int] = field(default_factory=list)  # chains won at step k
    exhausted: int = 0  # every step lost
    no_data_chains: int = 0  # cut short for lack of price data
    skipped_rounds: int = 0
    no_data_rounds: int = 0
    profit: Decimal = Decimal(0)
    staked: Decimal = Decimal(0)
    largest_stake: Decimal = Decimal(0)
    most_in_play: Decimal = Decimal(0)  # the most money in open trades at one moment
    worst_drawdown: Decimal = Decimal(0)
    worst_drawdown_at: int | None = None  # when the trough was reached
    longest_losing_run: int = 0  # chains lost one after the other
    spans: int = 0  # stretches in which pairs could open
    active_s: float = 0  # their seconds in all
    stops: dict[str, int] = field(default_factory=dict)  # how windows ended
    days: dict[str, list[Decimal | int]] = field(default_factory=dict)  # day: profit, chains, lost
    equity: list[tuple[int, Decimal]] = field(default_factory=list)  # (time, running profit)


@dataclass(slots=True)
class BacktestResult:
    totals: list[Totals]  # one per run, in the order of `BacktestSetup.runs()`
    chains: list[SimChain]
    windows: int  # of all periods
    runs: list[Run] = field(default_factory=list)


type Progress = Callable[[float], None]


def replay(
    prices: Prices,
    setup: BacktestSetup,
    *,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> BacktestResult:
    """Every run of the setup (a strategy, a way of opening, a period) over every window of its
    period. Raises `Cancelled`."""
    runs = setup.runs()
    windows = {period: setup.windows(period) for period in range(1, len(setup.periods()) + 1)}
    spans: dict[int, list[tuple[int, int]]] = {}
    if OpenRule.BREAKOUT in setup.opens:
        for period, own_windows in windows.items():
            if own_windows:
                first = int(own_windows[0].start.timestamp())
                last = int(own_windows[-1].end.timestamp())
                spans[period] = trend_spans(prices, setup, first, last)
    totals = [Totals() for _ in runs]
    chains: list[SimChain] = []
    jobs = sum(len(windows[r.period]) for r in runs) or 1
    done = 0
    for number, (run, total) in enumerate(zip(runs, totals, strict=True)):
        own: list[SimChain] = []
        trends = spans.get(run.period, []) if run.opens is OpenRule.BREAKOUT else None
        for window in windows[run.period]:
            if cancel is not None and cancel.is_set():
                raise Cancelled
            result = replay_window(prices, setup, run.strategy, window, trends)
            _count_window(total, result)
            own.extend(result.chains)
            done += 1
            if progress is not None:
                progress(done / jobs)
        for chain in own:
            chain.run = number
        _count_chains(total, own, setup.strategies[run.strategy])
        chains.extend(own)
    return BacktestResult(
        totals=totals,
        chains=chains,
        windows=sum(len(w) for w in windows.values()),
        runs=runs,
    )


def _count_window(total: Totals, result: WindowResult) -> None:
    total.windows += 1
    total.pairs += result.pairs
    total.skipped_rounds += result.skipped_rounds
    total.no_data_rounds += result.no_data_rounds
    total.spans += result.spans
    total.active_s += result.active_s
    total.stops[result.stopped_by] = total.stops.get(result.stopped_by, 0) + 1


def _count_chains(total: Totals, chains: list[SimChain], strategy: StrategySetup) -> None:
    longest = strategy.max_steps + 1
    total.won_at_step = [0] * longest
    settles: list[tuple[float, Decimal]] = []
    moves: list[tuple[int, int, Decimal]] = []  # (time, 0 = end before 1 = start, stake)
    for chain in chains:
        total.chains += 1
        if chain.status is ChainStatus.COMPLETED:
            total.won_at_step[len(chain.trades) - 1] += 1
        elif chain.status is ChainStatus.EXHAUSTED:
            total.exhausted += 1
        else:
            total.no_data_chains += 1
        day = total.days.setdefault(chain.day.isoformat(), [Decimal(0), 0, 0])
        day[0] = Decimal(day[0]) + chain.profit
        day[1] = int(day[1]) + 1
        day[2] = int(day[2]) + (1 if chain.status is ChainStatus.EXHAUSTED else 0)
        for trade in chain.trades:
            total.trades += 1
            total.trades_won += 1 if trade.won else 0
            total.staked += trade.stake
            total.largest_stake = max(total.largest_stake, trade.stake)
            settles.append((trade.end + RESULT_AFTER_S, trade.profit))
            moves.append((trade.start, 1, trade.stake))
            moves.append((trade.end, 0, trade.stake))
    in_play = Decimal(0)
    for _, kind, stake in sorted(moves, key=lambda m: (m[0], m[1])):
        in_play += stake if kind == 1 else -stake
        total.most_in_play = max(total.most_in_play, in_play)
    settles.sort(key=lambda s: s[0])
    running = peak = Decimal(0)
    step = max(1, len(settles) // EQUITY_POINTS)
    for i, (at, profit) in enumerate(settles):
        running += profit
        peak = max(peak, running)
        if peak - running > total.worst_drawdown:
            total.worst_drawdown = peak - running
            total.worst_drawdown_at = int(at)
        if i % step == 0 or i == len(settles) - 1:
            total.equity.append((int(at), running))
    total.profit = running
    streak = 0
    for chain in sorted(chains, key=lambda c: c.known_at):
        if chain.status is ChainStatus.EXHAUSTED:
            streak += 1
            total.longest_losing_run = max(total.longest_losing_run, streak)
        elif chain.status is ChainStatus.COMPLETED:
            streak = 0
