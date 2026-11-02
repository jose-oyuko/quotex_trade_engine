"""The report queries: SQL aggregations over the stored trades and chains.

Everything is computed by the database (`GROUP BY`, `SUM`, `COUNT`) except the three figures that
need the trades in order - streaks, drawdown and the daily running total - which are one streamed
pass over two small columns. Money is summed as integer cents by the database and converted at the
edge, so no report ever adds floats together.

Read-only: nothing here writes, and a report never holds a transaction open longer than its query.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, Select, String, case, func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chain, Group, Trade
from app.domain.enums import RESULT_TRADE_STATUSES, ChainStatus, TradeStatus
from app.reports.models import (
    EMPTY_METRICS,
    BreakdownKind,
    BreakdownRow,
    DepthReport,
    DepthRow,
    Drawdown,
    EquityPoint,
    ExportRow,
    Metrics,
    NotCounted,
    ReportFilter,
    Streaks,
    Summary,
    expectation_of,
)
from app.reports.sql import LocalPart

PARTITION = 5_000  # rows fetched per round trip when streaming
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _money(cents: int | None) -> Decimal:
    return Decimal(cents or 0).scaleb(-2)


def _range(column: Any, flt: ReportFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if flt.since is not None:
        conditions.append(column >= flt.since)
    if flt.until is not None:
        conditions.append(column < flt.until)
    return conditions


def _selectors(flt: ReportFilter) -> list[ColumnElement[bool]]:
    """The filters that are not about time or result."""
    conditions: list[ColumnElement[bool]] = [Trade.account_type == flt.account_type]
    if flt.group_id is not None:
        conditions.append(Trade.group_id == flt.group_id)
    if flt.asset is not None:
        conditions.append(Trade.asset == flt.asset)
    if flt.strategy is not None:
        conditions.append(Chain.strategy == flt.strategy)
    return conditions


def _resolved_trades[S: Select[Any]](stmt: S, flt: ReportFilter) -> S:
    """Restrict a `SELECT ... FROM trades` to the resolved trades the filter describes."""
    if flt.strategy is not None:
        stmt = stmt.join(Chain, Chain.id == Trade.chain_id)
    return stmt.where(
        *_selectors(flt),
        Trade.status.in_(RESULT_TRADE_STATUSES),
        *_range(Trade.settled_at, flt),
    )


def _metric_columns() -> tuple[Any, ...]:
    return (
        func.count().label("n"),
        func.sum(case((Trade.status == TradeStatus.WON, 1), else_=0)).label("wins"),
        func.sum(case((Trade.status == TradeStatus.LOST, 1), else_=0)).label("losses"),
        func.sum(case((Trade.status == TradeStatus.DRAW, 1), else_=0)).label("draws"),
        type_coerce(func.sum(Trade.profit), BigInteger).label("profit"),
        type_coerce(func.sum(Trade.stake), BigInteger).label("staked"),
        func.avg(Trade.payout_pct).label("avg_payout"),
    )


def _metrics(row: Sequence[Any]) -> Metrics:
    n, wins, losses, draws, profit, staked, avg_payout = row
    return Metrics(
        trades=int(n or 0),
        wins=int(wins or 0),
        losses=int(losses or 0),
        draws=int(draws or 0),
        profit=_money(profit),
        staked=_money(staked),
        avg_payout_pct=None if avg_payout is None else float(avg_payout),
    )


# --- breakdowns ---


async def breakdown(
    session: AsyncSession, flt: ReportFilter, kind: BreakdownKind
) -> list[BreakdownRow]:
    """Resolved trades grouped by group, asset, strategy, hour of day or weekday."""
    labels: Any
    key: Any
    match kind:
        case BreakdownKind.GROUP:
            key, labels = Trade.group_id, Group.title
        case BreakdownKind.ASSET:
            key = labels = Trade.asset
        case BreakdownKind.STRATEGY:
            key = labels = Chain.strategy
        case BreakdownKind.HOUR:
            key = labels = LocalPart(Trade.settled_at, "hour", flt.utc_offset_minutes)
        case BreakdownKind.WEEKDAY:
            key = labels = LocalPart(Trade.settled_at, "weekday", flt.utc_offset_minutes)

    stmt: Select[Any] = select(key.label("key"), labels.label("label"), *_metric_columns())
    stmt = stmt.select_from(Trade)
    if kind is BreakdownKind.GROUP:
        stmt = stmt.join(Group, Group.id == Trade.group_id)
    if kind is BreakdownKind.STRATEGY and flt.strategy is None:
        stmt = stmt.join(Chain, Chain.id == Trade.chain_id)
    stmt = _resolved_trades(stmt, flt).group_by(key, labels)

    rows: dict[str, BreakdownRow] = {}
    for row in (await session.execute(stmt)).all():
        raw_key, raw_label, *rest = row
        rows[_key_text(raw_key)] = BreakdownRow(
            key=_key_text(raw_key),
            label=_label(kind, raw_key, raw_label),
            metrics=_metrics(tuple(rest)),
        )
    if kind is BreakdownKind.HOUR:  # every hour has a bar, quiet ones included
        return [rows.get(str(h)) or _empty(str(h), f"{h:02d}:00") for h in range(24)]
    if kind is BreakdownKind.WEEKDAY:
        return [rows.get(str(d)) or _empty(str(d), WEEKDAYS[d]) for d in range(7)]
    return sorted(rows.values(), key=lambda r: (-r.metrics.profit, r.label))


def _key_text(value: object) -> str:
    return str(getattr(value, "value", value))


def _label(kind: BreakdownKind, key: object, label: object) -> str:
    if kind is BreakdownKind.HOUR:
        return f"{int(str(key)):02d}:00"
    if kind is BreakdownKind.WEEKDAY:
        return WEEKDAYS[int(str(key))]
    return _key_text(label)


def _empty(key: str, label: str) -> BreakdownRow:
    return BreakdownRow(key, label, EMPTY_METRICS)


# --- summary: totals, what is missing, streaks, drawdown ---


async def summary(session: AsyncSession, flt: ReportFilter) -> Summary:
    totals = (await session.execute(_resolved_trades(select(*_metric_columns()), flt))).one()
    metrics = _metrics(tuple(totals))
    scan = await _scan(session, flt)
    return Summary(
        metrics=metrics,
        not_counted=await _not_counted(session, flt),
        streaks=scan.streaks,
        drawdown=scan.drawdown,
        expectation=expectation_of(metrics.wins, metrics.losses, metrics.avg_payout_pct),
        first_day=scan.first_day,
        last_day=scan.last_day,
    )


async def _not_counted(session: AsyncSession, flt: ReportFilter) -> NotCounted:
    unresolved = (TradeStatus.FAILED, TradeStatus.UNKNOWN, TradeStatus.OPEN, TradeStatus.PENDING)
    stmt = select(Trade.status, func.count()).select_from(Trade)
    if flt.strategy is not None:
        stmt = stmt.join(Chain, Chain.id == Trade.chain_id)
    stmt = stmt.where(
        *_selectors(flt), Trade.status.in_(unresolved), *_range(Trade.created_at, flt)
    ).group_by(Trade.status)
    counts = {TradeStatus(status): int(n) for status, n in (await session.execute(stmt)).all()}
    return NotCounted(
        failed=counts.get(TradeStatus.FAILED, 0),
        unknown=counts.get(TradeStatus.UNKNOWN, 0),
        open=counts.get(TradeStatus.OPEN, 0) + counts.get(TradeStatus.PENDING, 0),
    )


class _Scan:
    def __init__(self, streaks: Streaks, drawdown: Drawdown, daily: list[EquityPoint]) -> None:
        self.streaks = streaks
        self.drawdown = drawdown
        self.daily = daily

    @property
    def first_day(self) -> str | None:
        return self.daily[0].day if self.daily else None

    @property
    def last_day(self) -> str | None:
        return self.daily[-1].day if self.daily else None


async def _scan(session: AsyncSession, flt: ReportFilter) -> _Scan:
    """One streamed pass over the resolved trades in the order they settled."""
    day = LocalPart(Trade.settled_at, "day", flt.utc_offset_minutes)
    stmt = _resolved_trades(
        select(
            day.label("day"),
            type_coerce(Trade.status, String),
            type_coerce(Trade.profit, BigInteger),
        ).select_from(Trade),
        flt,
    ).order_by(Trade.settled_at, Trade.id)

    cumulative = peak = max_drawdown = 0
    peak_day = peak_day_at_max = trough_day = None
    win_run = loss_run = longest_win = longest_loss = 0
    daily: dict[str, list[int]] = {}  # day -> [trades, profit_cents, cumulative_at_close]

    result = await session.stream(stmt)
    async for rows in result.partitions(PARTITION):
        for trade_day, status, cents in rows:
            profit = cents or 0
            cumulative += profit
            if cumulative > peak:
                peak, peak_day = cumulative, trade_day
            elif peak - cumulative > max_drawdown:
                max_drawdown, peak_day_at_max, trough_day = peak - cumulative, peak_day, trade_day
            bucket = daily.setdefault(trade_day, [0, 0, 0])
            bucket[0] += 1
            bucket[1] += profit
            bucket[2] = cumulative
            if status == TradeStatus.WON:
                win_run, loss_run = win_run + 1, 0
                longest_win = max(longest_win, win_run)
            elif status == TradeStatus.LOST:
                win_run, loss_run = 0, loss_run + 1
                longest_loss = max(longest_loss, loss_run)
            else:  # a draw ends a run without being part of one
                win_run = loss_run = 0

    current = win_run if win_run else -loss_run
    return _Scan(
        Streaks(longest_win, longest_loss, current),
        Drawdown(
            max_amount=_money(max_drawdown),
            peak_day=peak_day_at_max if max_drawdown else None,
            trough_day=trough_day if max_drawdown else None,
            current_amount=_money(peak - cumulative),
        ),
        [EquityPoint(d, v[0], _money(v[1]), _money(v[2])) for d, v in sorted(daily.items())],
    )


async def equity(session: AsyncSession, flt: ReportFilter) -> list[EquityPoint]:
    """The result of each day that had trades, with the running total at its close."""
    return (await _scan(session, flt)).daily


# --- chain depth: how far chains go and what they cost ---


async def depth(session: AsyncSession, flt: ReportFilter) -> DepthReport:
    """For every step: how many chains got that far, what the trades at that step staked and
    earned, and how chains that ended there fared overall. Chains are placed in the range by the
    time they started, and only trades with a result count."""
    chain_filter: list[ColumnElement[bool]] = [
        Chain.account_type == flt.account_type,
        Chain.status.notin_((ChainStatus.PENDING, ChainStatus.OPEN)),
        *_range(Chain.created_at, flt),
    ]
    if flt.group_id is not None:
        chain_filter.append(Chain.group_id == flt.group_id)
    if flt.asset is not None:
        chain_filter.append(Chain.asset == flt.asset)
    if flt.strategy is not None:
        chain_filter.append(Chain.strategy == flt.strategy)

    per_chain = (
        select(
            Chain.id.label("chain_id"),
            Chain.status.label("chain_status"),
            func.max(Trade.step).label("reached"),
            type_coerce(func.sum(Trade.profit), BigInteger).label("profit"),
        )
        .select_from(Chain)
        .join(Trade, Trade.chain_id == Chain.id)
        .where(*chain_filter, Trade.status.in_(RESULT_TRADE_STATUSES))
        .group_by(Chain.id, Chain.status)
        .subquery()
    )
    ending = (
        select(
            per_chain.c.reached,
            func.count().label("chains"),
            func.sum(case((per_chain.c.chain_status == ChainStatus.COMPLETED, 1), else_=0)).label(
                "completed"
            ),
            func.sum(case((per_chain.c.chain_status == ChainStatus.EXHAUSTED, 1), else_=0)).label(
                "exhausted"
            ),
            func.sum(per_chain.c.profit).label("profit"),
        )
        .group_by(per_chain.c.reached)
        .order_by(per_chain.c.reached)
    )
    by_step = (
        select(
            Trade.step,
            func.count().label("trades"),
            func.sum(case((Trade.status == TradeStatus.WON, 1), else_=0)).label("wins"),
            func.sum(case((Trade.status == TradeStatus.LOST, 1), else_=0)).label("losses"),
            type_coerce(func.sum(Trade.stake), BigInteger).label("staked"),
            type_coerce(func.sum(Trade.profit), BigInteger).label("profit"),
        )
        .select_from(Chain)
        .join(Trade, Trade.chain_id == Chain.id)
        .where(*chain_filter, Trade.status.in_(RESULT_TRADE_STATUSES))
        .group_by(Trade.step)
        .order_by(Trade.step)
    )

    ended = {int(r[0]): r for r in (await session.execute(ending)).all()}
    steps = {int(r[0]): r for r in (await session.execute(by_step)).all()}
    total = sum(int(r[1]) for r in ended.values())
    completed = sum(int(r[2] or 0) for r in ended.values())
    exhausted = sum(int(r[3] or 0) for r in ended.values())
    total_profit = sum(int(r[4] or 0) for r in ended.values())

    rows: list[DepthRow] = []
    last = max(steps, default=-1)
    for step in range(last + 1):
        reaching = sum(int(r[1]) for reached, r in ended.items() if reached >= step)
        trades_row = steps.get(step)
        end_row = ended.get(step)
        rows.append(
            DepthRow(
                step=step + 1,
                chains_reaching=reaching,
                share_of_chains=reaching / total if total else 0.0,
                trades=int(trades_row[1]) if trades_row else 0,
                wins=int(trades_row[2] or 0) if trades_row else 0,
                losses=int(trades_row[3] or 0) if trades_row else 0,
                staked=_money(trades_row[4]) if trades_row else Decimal(0),
                profit=_money(trades_row[5]) if trades_row else Decimal(0),
                chains_ending_here=int(end_row[1]) if end_row else 0,
                chains_won_here=int(end_row[2] or 0) if end_row else 0,
                chain_profit_ending_here=_money(end_row[4]) if end_row else Decimal(0),
            )
        )
    return DepthReport(
        chains=total,
        completed=completed,
        exhausted=exhausted,
        other=total - completed - exhausted,
        avg_chain_profit=(_money(total_profit) / total).quantize(Decimal("0.01"))
        if total
        else None,
        steps=rows,
    )


# --- export ---


def _cents_text(cents: int | None) -> str:
    if cents is None:
        return ""
    sign, whole = ("-", -cents) if cents < 0 else ("", cents)
    return f"{sign}{whole // 100}.{whole % 100:02d}"


def _utc_text(value: object) -> str:
    """`2026-11-02 10:05:00`. SQLite hands back the stored UTC text, which only needs trimming;
    another database may return a datetime."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:19].replace("T", " ")
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[attr-defined, no-any-return]


def _uuid_text(value: object) -> str:
    if isinstance(value, str) and len(value) == 32:  # SQLite keeps UUIDs as 32 hex digits
        return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"
    return str(value)


async def export_trades(session: AsyncSession, flt: ReportFilter) -> AsyncIterator[list[ExportRow]]:
    """Every trade in the range (whatever its status), oldest first, in batches. Here the range is
    the time the trade was *created*, because a trade that never settled has no settle time.
    Columns are read as raw stored values and turned into text directly (see `ExportRow`)."""
    stmt = (
        select(
            type_coerce(Trade.id, String),
            type_coerce(Trade.chain_id, String),
            type_coerce(Trade.created_at, String),
            type_coerce(Trade.settled_at, String),
            type_coerce(Trade.account_type, String),
            Trade.group_id,
            Group.title,
            type_coerce(Chain.strategy, String),
            Trade.asset,
            type_coerce(Trade.direction, String),
            Trade.step,
            Trade.duration_s,
            type_coerce(Trade.stake, BigInteger),
            Trade.payout_pct,
            type_coerce(Trade.status, String),
            type_coerce(Trade.profit, BigInteger),
            Trade.error,
        )
        .select_from(Trade)
        .join(Chain, Chain.id == Trade.chain_id)
        .join(Group, Group.id == Trade.group_id)
        .where(*_selectors(flt), *_range(Trade.created_at, flt))
        .order_by(Trade.created_at, Trade.id)
    )
    result = await session.stream(stmt)
    async for rows in result.partitions(PARTITION):
        yield [
            ExportRow(
                trade_id=_uuid_text(r[0]),
                chain_id=_uuid_text(r[1]),
                created_at=_utc_text(r[2]),
                settled_at=_utc_text(r[3]),
                account_type=r[4],
                group_id=r[5],
                group_title=r[6],
                strategy=r[7],
                asset=r[8],
                direction=r[9],
                step=r[10] + 1,
                duration_s=r[11],
                stake=_cents_text(r[12]),
                payout_pct=r[13],
                status=r[14],
                profit=_cents_text(r[15]),
                error=r[16],
            )
            for r in rows
        ]
