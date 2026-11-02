"""Response shapes for the reports. Money is text (never a float); rates and ratios are plain
numbers between 0 and 1 (a win rate of 0.55 is 55%)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import AccountType, Strategy
from app.reports.models import (
    SAMPLE_SMALL,
    SAMPLE_TINY,
    BreakdownKind,
    BreakdownRow,
    DepthReport,
    EquityPoint,
    Metrics,
    ReportFilter,
    Summary,
)


class FilterOut(BaseModel):
    """The filters the numbers below were computed with, echoed back."""

    account_type: AccountType
    since: datetime | None
    until: datetime | None
    group_id: int | None
    strategy: Strategy | None
    asset: str | None
    utc_offset_minutes: int


class MetricsOut(BaseModel):
    trades: int = Field(description="Trades with a known result.")
    wins: int
    losses: int
    draws: int
    win_rate: float | None = Field(description="wins / trades, 0 to 1; null with no trades.")
    profit: Decimal = Field(description="Net result; negative is a loss.")
    staked: Decimal = Field(description="Total stake of these trades.")
    roi: float | None = Field(description="profit / staked; null when nothing was staked.")
    avg_stake: Decimal | None
    avg_payout_pct: float | None
    sample: Literal["tiny", "small", "ok"] = Field(
        description="How much to trust the numbers: tiny (< 10 trades), small (< 30), ok."
    )


class BreakdownRowOut(BaseModel):
    key: str
    label: str
    metrics: MetricsOut


class BreakdownOut(BaseModel):
    filter: FilterOut
    by: BreakdownKind
    rows: list[BreakdownRowOut]


class NotCountedOut(BaseModel):
    failed: int
    unknown: int
    open: int


class StreaksOut(BaseModel):
    longest_win: int
    longest_loss: int
    current: int = Field(description="Wins in a row now (positive) or losses in a row (negative).")


class DrawdownOut(BaseModel):
    max_amount: Decimal
    peak_day: str | None = Field(description="Null when the high point was the start of the range.")
    trough_day: str | None
    current_amount: Decimal


class ExpectationOut(BaseModel):
    breakeven_win_rate: float | None
    actual_win_rate: float | None
    edge: float | None
    z_score: float | None
    verdict: Literal[
        "not_enough_data", "consistent_with_break_even", "above_break_even", "below_break_even"
    ]


class SampleGuideOut(BaseModel):
    tiny_below: int = SAMPLE_TINY
    small_below: int = SAMPLE_SMALL


class SummaryOut(BaseModel):
    filter: FilterOut
    metrics: MetricsOut
    not_counted: NotCountedOut
    streaks: StreaksOut
    drawdown: DrawdownOut
    expectation: ExpectationOut
    first_day: str | None
    last_day: str | None
    sample_guide: SampleGuideOut


class EquityPointOut(BaseModel):
    day: str
    trades: int
    profit: Decimal
    cumulative: Decimal


class EquityOut(BaseModel):
    filter: FilterOut
    points: list[EquityPointOut]


class DepthRowOut(BaseModel):
    step: int = Field(description="Trade number in the chain; 1 is the original signal's trade.")
    chains_reaching: int
    share_of_chains: float
    trades: int
    wins: int
    losses: int
    staked: Decimal
    profit: Decimal
    chains_ending_here: int
    chains_won_here: int
    chain_profit_ending_here: Decimal


class DepthOut(BaseModel):
    filter: FilterOut
    chains: int
    completed: int
    exhausted: int
    other: int
    avg_chain_profit: Decimal | None
    steps: list[DepthRowOut]


def filter_out(flt: ReportFilter) -> FilterOut:
    return FilterOut(
        account_type=flt.account_type,
        since=flt.since,
        until=flt.until,
        group_id=flt.group_id,
        strategy=flt.strategy,
        asset=flt.asset,
        utc_offset_minutes=flt.utc_offset_minutes,
    )


def metrics_out(m: Metrics) -> MetricsOut:
    return MetricsOut(
        trades=m.trades,
        wins=m.wins,
        losses=m.losses,
        draws=m.draws,
        win_rate=m.win_rate,
        profit=m.profit,
        staked=m.staked,
        roi=m.roi,
        avg_stake=m.avg_stake,
        avg_payout_pct=m.avg_payout_pct,
        sample=m.sample,
    )


def breakdown_out(flt: ReportFilter, kind: BreakdownKind, rows: list[BreakdownRow]) -> BreakdownOut:
    return BreakdownOut(
        filter=filter_out(flt),
        by=kind,
        rows=[
            BreakdownRowOut(key=r.key, label=r.label, metrics=metrics_out(r.metrics)) for r in rows
        ],
    )


def summary_out(flt: ReportFilter, s: Summary) -> SummaryOut:
    return SummaryOut(
        filter=filter_out(flt),
        metrics=metrics_out(s.metrics),
        not_counted=NotCountedOut(
            failed=s.not_counted.failed, unknown=s.not_counted.unknown, open=s.not_counted.open
        ),
        streaks=StreaksOut(
            longest_win=s.streaks.longest_win,
            longest_loss=s.streaks.longest_loss,
            current=s.streaks.current,
        ),
        drawdown=DrawdownOut(
            max_amount=s.drawdown.max_amount,
            peak_day=s.drawdown.peak_day,
            trough_day=s.drawdown.trough_day,
            current_amount=s.drawdown.current_amount,
        ),
        expectation=ExpectationOut(
            breakeven_win_rate=s.expectation.breakeven_win_rate,
            actual_win_rate=s.expectation.actual_win_rate,
            edge=s.expectation.edge,
            z_score=s.expectation.z_score,
            verdict=s.expectation.verdict,
        ),
        first_day=s.first_day,
        last_day=s.last_day,
        sample_guide=SampleGuideOut(),
    )


def equity_out(flt: ReportFilter, points: list[EquityPoint]) -> EquityOut:
    return EquityOut(
        filter=filter_out(flt),
        points=[
            EquityPointOut(day=p.day, trades=p.trades, profit=p.profit, cumulative=p.cumulative)
            for p in points
        ],
    )


def depth_out(flt: ReportFilter, d: DepthReport) -> DepthOut:
    return DepthOut(
        filter=filter_out(flt),
        chains=d.chains,
        completed=d.completed,
        exhausted=d.exhausted,
        other=d.other,
        avg_chain_profit=d.avg_chain_profit,
        steps=[
            DepthRowOut(
                step=r.step,
                chains_reaching=r.chains_reaching,
                share_of_chains=r.share_of_chains,
                trades=r.trades,
                wins=r.wins,
                losses=r.losses,
                staked=r.staked,
                profit=r.profit,
                chains_ending_here=r.chains_ending_here,
                chains_won_here=r.chains_won_here,
                chain_profit_ending_here=r.chain_profit_ending_here,
            )
            for r in d.steps
        ],
    )
