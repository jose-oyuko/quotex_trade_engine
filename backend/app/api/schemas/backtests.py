"""Backtests (decision D-84): a session-shaped setup replayed on stored prices, and its results."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.api.schemas.groups import MAX_BASE_STAKE, MAX_STEPS, Multiplier
from app.api.schemas.market import MarketRulesIn
from app.backtest.replay import MAX_RUNS, OpenRule
from app.domain.enums import ChainStatus, Direction, SessionMode, Strategy
from app.engine.strategies import max_steps_of
from app.market.detector import MarketRules
from app.signals.timezones import InvalidTimezoneError, parse_timezone

Money = Annotated[Decimal, Field(gt=0, le=MAX_BASE_STAKE, max_digits=12, decimal_places=2)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
BacktestState = Literal["running", "done", "failed", "cancelled"]


class BacktestStrategyIn(BaseModel):
    """One strategy to compare: the same rules as a session's (steps and multipliers)."""

    model_config = ConfigDict(extra="forbid")

    strategy: Strategy
    max_steps: int = Field(ge=0, le=MAX_STEPS)
    multipliers: list[Multiplier] = Field(default_factory=list, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def _one_multiplier_per_step(self) -> Self:
        if self.strategy is Strategy.NO_MARTINGALE and self.max_steps:
            raise ValueError("no martingale has no steps: set max_steps to 0")
        if len(self.multipliers) != self.max_steps:
            raise ValueError(
                "need exactly one multiplier per step: "
                f"max_steps={self.max_steps}, got {len(self.multipliers)}"
            )
        limit = max_steps_of(self.strategy)
        if limit is not None and self.max_steps > limit:
            raise ValueError(
                f"growing flip has at most {limit} steps (9 trades in all), got {self.max_steps}"
            )
        return self


class BacktestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = Field(default=None, description="Shown in the list; made up if empty.")
    asset: str = Field(min_length=2, max_length=30, pattern=r"^\w+$")
    first_day: date = Field(description="The first day replayed, in `timezone`.")
    last_day: date = Field(description="The last day replayed (included). At most 92 days.")
    start_time: time = Field(description="The session window, wall-clock in `timezone`.")
    end_time: time = Field(description="Before `start_time`: the window crosses midnight.")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    weekdays: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6],
        min_length=1,
        max_length=7,
        description="0 = Monday ... 6 = Sunday.",
    )
    duration_s: int = Field(ge=15, le=86_400, description="The trade (and candle) length.")
    mode: SessionMode = SessionMode.SEQUENTIAL
    pause_s: int = Field(default=0, ge=0, le=86_400)
    max_open_pairs: int = Field(default=1, ge=1, le=50)
    max_pairs: int | None = Field(default=None, ge=1, le=100_000, description="Per window.")
    profit_target: Money | None = Field(default=None, description="Per window.")
    loss_limit: Money | None = Field(default=None, description="Per window.")
    base_stake: Money
    strategies: list[BacktestStrategyIn] = Field(min_length=1, max_length=6)
    payout_pct: Decimal = Field(
        default=Decimal(88),
        gt=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Assumed: a win pays stake x this %. Deriv keeps no past payouts.",
    )
    order_delay_s: float = Field(
        default=0.5, ge=0, le=10, description="From deciding a trade to its purchase."
    )
    step_delay_s: float = Field(
        default=1.0, ge=0, le=60, description="From a trade's end to deciding the next step."
    )
    opens: list[OpenRule] = Field(
        default_factory=lambda: [OpenRule.WINDOW],
        min_length=1,
        max_length=2,
        description="When pairs open: `window` (all through it), `breakout` (only while a trend "
        "is on, after a breakout), or both, compared side by side.",
    )
    market: MarketRulesIn = Field(
        default_factory=MarketRulesIn,
        description="`breakout`: what counts as a consolidation and a breakout.",
    )
    trend_max_candles: int | None = Field(
        default=20,
        ge=1,
        le=10_000,
        description="`breakout`: stop opening pairs this many candles after the breakout, or "
        "earlier at the next consolidation; null: only at the next consolidation.",
    )
    check_first_day: date | None = Field(
        default=None, description="A second period, to judge settings chosen on the first."
    )
    check_last_day: date | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.last_day < self.first_day:
            raise ValueError("the last day must not be before the first")
        if (self.last_day - self.first_day).days + 1 > 92:
            raise ValueError("at most 92 days per backtest")
        if (self.check_first_day is None) != (self.check_last_day is None):
            raise ValueError("the second period needs both its first and its last day")
        if self.check_first_day is not None and self.check_last_day is not None:
            if self.check_last_day < self.check_first_day:
                raise ValueError("the second period's last day must not be before its first")
            if (self.check_last_day - self.check_first_day).days + 1 > 92:
                raise ValueError("at most 92 days in the second period")
        if len(set(self.opens)) != len(self.opens):
            raise ValueError("each way of opening at most once")
        periods = 1 if self.check_first_day is None else 2
        if len(self.strategies) * len(self.opens) * periods > MAX_RUNS:
            raise ValueError(f"at most {MAX_RUNS} runs: strategies x ways of opening x periods")
        try:
            self.market_rules()
        except ValueError as exc:
            raise ValueError(f"market: {exc}") from exc
        if self.start_time == self.end_time:
            raise ValueError("the start and the end of the window must differ")
        if any(not 0 <= d <= 6 for d in self.weekdays) or len(set(self.weekdays)) != len(
            self.weekdays
        ):
            raise ValueError("weekdays are distinct numbers from 0 (Monday) to 6 (Sunday)")
        try:
            parse_timezone(self.timezone)
        except InvalidTimezoneError as exc:
            raise ValueError(str(exc)) from exc
        return self

    def market_rules(self) -> MarketRules:
        m = self.market
        return MarketRules(
            pattern=m.pattern,
            candles=m.candles,
            misses=m.misses,
            width=m.width,
            net_share=m.net_share,
            breakout_candles=m.breakout_candles,
            breakout_by=m.breakout_by,
        )


class DayOut(BaseModel):
    day: date
    profit: Decimal
    chains: int
    lost: int = Field(description="Chains that lost every step.")


class EquityPointOut(BaseModel):
    at: datetime
    profit: Decimal = Field(description="The running profit when this result was known.")


class StrategyResultOut(BaseModel):
    """One run: a strategy, replayed one way (`opens`) on one period."""

    strategy: Strategy
    max_steps: int
    multipliers: list[Decimal]
    index: int | None = Field(
        default=None, description="Index into the setup's strategies (null before Phase 31)."
    )
    opens: OpenRule = OpenRule.WINDOW
    period: int = Field(default=1, description="1, or 2: the period that judges the settings.")
    spans: int = Field(
        default=0, description="Stretches in which pairs could open: windows, or trends."
    )
    active_s: int = Field(default=0, description="Their seconds in all.")
    windows: int
    pairs: int
    chains: int
    trades: int
    trades_won: int
    won_at_step: list[int] = Field(description="Chains won at step 0, 1, 2 ...")
    exhausted: int = Field(description="Chains that lost every step.")
    no_data_chains: int = Field(description="Chains cut short for lack of price data.")
    skipped_rounds: int = Field(description="Candles with too many pairs open (every candle).")
    no_data_rounds: int = Field(description="Pairs not opened for lack of price data.")
    profit: Decimal
    staked: Decimal
    largest_stake: Decimal
    most_in_play: Decimal = Field(description="The most money in open trades at one moment.")
    worst_drawdown: Decimal = Field(description="The deepest fall from a running-profit peak.")
    worst_drawdown_at: datetime | None
    longest_losing_run: int = Field(description="Chains lost one after another, at most.")
    stops: dict[str, int] = Field(description="How the windows ended: `window_ended`, ...")
    days: list[DayOut]
    equity: list[EquityPointOut]


class BacktestSummaryOut(BaseModel):
    windows: int
    seconds: float = Field(description="How long the replay took.")
    strategies: list[StrategyResultOut]


class BacktestItemOut(BaseModel):
    id: int
    name: str
    state: BacktestState
    progress: float = Field(ge=0, le=1)
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    asset: str
    first_day: date
    last_day: date
    strategies: list[Strategy]


class BacktestOut(BacktestItemOut):
    setup: BacktestIn
    summary: BacktestSummaryOut | None


class BacktestsOut(BaseModel):
    items: list[BacktestItemOut]


class BacktestTradeOut(BaseModel):
    start: datetime
    end: datetime
    direction: Direction
    stake: Decimal
    entry: float
    exit: float
    profit: Decimal


class BacktestChainOut(BaseModel):
    strategy: int = Field(description="Index into the result's runs (`summary.strategies`).")
    seq: int
    day: date
    pair_no: int
    origin: Direction = Field(description="The leg: the first trade's direction.")
    started: datetime
    status: ChainStatus = Field(description="`completed` (won), `exhausted`, or `failed`.")
    steps: int = Field(description="Trades in the chain.")
    profit: Decimal
    trades: list[BacktestTradeOut]


class BacktestChainsOut(BaseModel):
    items: list[BacktestChainOut]
    total: int


class BacktestPairOut(BaseModel):
    at: datetime = Field(description="When the pair's first trades started.")
    profit: Decimal = Field(description="Both legs together.")
    lost: bool = Field(description="A leg lost every step.")


class BacktestPairsOut(BaseModel):
    items: list[BacktestPairOut] = Field(description="Oldest first.")
    total: int = Field(description="All the run's pairs; `items` stops at 20,000.")
