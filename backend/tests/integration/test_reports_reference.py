"""The SQL reports against a second, deliberately plain Python implementation, on thousands of
random trades. The hand-made history in `test_reports.py` pins exact numbers; this test catches
what a small table cannot: groups, accounts, statuses, draws, ranges, clocks and tie-breaks all
mixed together."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from random import Random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import RESULT_TRADE_STATUSES, AccountType, ChainStatus, Strategy, TradeStatus
from app.domain.records import ChainRecord, TradeRecord
from app.reports import queries
from app.reports.models import BreakdownKind, ReportFilter
from tests.reports_support import at, insert_history, random_history

Factory = async_sessionmaker[AsyncSession]
D = Decimal
GROUPS = 4


@pytest.fixture
async def history(session_factory: Factory) -> tuple[list[ChainRecord], list[TradeRecord]]:
    chains, trades = random_history(Random(20261102), 2_500, groups=GROUPS, days=20)  # noqa: S311
    await insert_history(session_factory, GROUPS, chains, trades)
    return chains, trades


# --- the reference: obvious loops, no SQL --------------------------------------------------


def resolved(trades: list[TradeRecord], flt: ReportFilter, strategies: dict[object, Strategy]):  # type: ignore[no-untyped-def]
    out = []
    for t in trades:
        if t.account_type is not flt.account_type or t.status not in RESULT_TRADE_STATUSES:
            continue
        if flt.group_id is not None and t.group_id != flt.group_id:
            continue
        if flt.asset is not None and t.asset != flt.asset:
            continue
        if flt.strategy is not None and strategies[t.chain_id] is not flt.strategy:
            continue
        assert t.settled_at is not None
        if flt.since is not None and t.settled_at < flt.since:
            continue
        if flt.until is not None and t.settled_at >= flt.until:
            continue
        out.append(t)
    return sorted(out, key=lambda t: t.settled_at)  # type: ignore[arg-type, return-value]


def local(t: TradeRecord, flt: ReportFilter) -> datetime:
    assert t.settled_at is not None
    return t.settled_at + timedelta(minutes=flt.utc_offset_minutes)


def reference_metrics(rows: list[TradeRecord]) -> tuple[int, int, int, int, Decimal, Decimal]:
    return (
        len(rows),
        sum(t.status is TradeStatus.WON for t in rows),
        sum(t.status is TradeStatus.LOST for t in rows),
        sum(t.status is TradeStatus.DRAW for t in rows),
        sum((t.profit or D(0) for t in rows), D(0)),
        sum((t.stake for t in rows), D(0)),
    )


def sql_metrics(m) -> tuple[int, int, int, int, Decimal, Decimal]:  # type: ignore[no-untyped-def]
    return (m.trades, m.wins, m.losses, m.draws, m.profit, m.staked)


FILTERS = [
    ReportFilter(AccountType.DEMO),
    ReportFilter(AccountType.REAL),
    ReportFilter(AccountType.DEMO, group_id=2),
    ReportFilter(AccountType.DEMO, asset="EURUSD", utc_offset_minutes=-180),
    ReportFilter(AccountType.DEMO, strategy=Strategy.MARTINGALE),
    ReportFilter(
        AccountType.DEMO, since=at(5, 7, 30), until=at(14, 18, 45), utc_offset_minutes=210
    ),
    ReportFilter(AccountType.REAL, group_id=3, since=at(10, 0)),
    ReportFilter(AccountType.DEMO, until=at(3, 0), utc_offset_minutes=-720),
]


@pytest.mark.parametrize(
    "flt", FILTERS, ids=lambda f: f"{f.account_type.value}-{f.group_id}-{f.asset}-{f.strategy}"
)
async def test_the_summary_matches_the_reference(
    session_factory: Factory, history, flt: ReportFilter
) -> None:  # type: ignore[no-untyped-def]
    chains, trades = history
    strategies = {c.id: c.strategy for c in chains}
    rows = resolved(trades, flt, strategies)
    async with session_factory() as session:
        summary = await queries.summary(session, flt)
    assert sql_metrics(summary.metrics) == reference_metrics(rows)

    # streaks and drawdown, in settle order
    win = loss = best_win = best_loss = 0
    cumulative = peak = worst = D(0)
    for t in rows:
        cumulative += t.profit or D(0)
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
        if t.status is TradeStatus.WON:
            win, loss = win + 1, 0
        elif t.status is TradeStatus.LOST:
            win, loss = 0, loss + 1
        else:
            win = loss = 0
        best_win, best_loss = max(best_win, win), max(best_loss, loss)
    assert (summary.streaks.longest_win, summary.streaks.longest_loss) == (best_win, best_loss)
    assert summary.streaks.current == (win if win else -loss)
    assert summary.drawdown.max_amount == worst
    assert summary.drawdown.current_amount == peak - cumulative

    # what is not counted: unresolved trades created in the range
    unresolved = [
        t
        for t in trades
        if t.account_type is flt.account_type
        and t.status not in RESULT_TRADE_STATUSES
        and (flt.group_id is None or t.group_id == flt.group_id)
        and (flt.asset is None or t.asset == flt.asset)
        and (flt.strategy is None or strategies[t.chain_id] is flt.strategy)
        and (flt.since is None or t.created_at >= flt.since)
        and (flt.until is None or t.created_at < flt.until)
    ]
    nc = summary.not_counted
    assert nc.failed == sum(t.status is TradeStatus.FAILED for t in unresolved)
    assert nc.unknown == sum(t.status is TradeStatus.UNKNOWN for t in unresolved)
    assert nc.open == sum(t.status in (TradeStatus.OPEN, TradeStatus.PENDING) for t in unresolved)


@pytest.mark.parametrize(
    "flt", FILTERS, ids=lambda f: f"{f.account_type.value}-{f.group_id}-{f.asset}-{f.strategy}"
)
async def test_every_breakdown_matches_the_reference(
    session_factory: Factory, history, flt: ReportFilter
) -> None:  # type: ignore[no-untyped-def]
    chains, trades = history
    strategies = {c.id: c.strategy for c in chains}
    rows = resolved(trades, flt, strategies)
    keys = {
        BreakdownKind.GROUP: lambda t: str(t.group_id),
        BreakdownKind.ASSET: lambda t: t.asset,
        BreakdownKind.STRATEGY: lambda t: strategies[t.chain_id].value,
        BreakdownKind.HOUR: lambda t: str(local(t, flt).hour),
        BreakdownKind.WEEKDAY: lambda t: str(local(t, flt).weekday()),
    }
    async with session_factory() as session:
        for kind, key_of in keys.items():
            expected: dict[str, list[TradeRecord]] = defaultdict(list)
            for t in rows:
                expected[key_of(t)].append(t)
            got = await queries.breakdown(session, flt, kind)
            by_key = {r.key: r for r in got if r.metrics.trades}
            assert set(by_key) == set(expected), kind
            for key, group in expected.items():
                assert sql_metrics(by_key[key].metrics) == reference_metrics(group), (kind, key)


@pytest.mark.parametrize(
    "flt", FILTERS[:6], ids=lambda f: f"{f.account_type.value}-{f.group_id}-{f.asset}"
)
async def test_the_daily_series_matches_the_reference(
    session_factory: Factory, history, flt: ReportFilter
) -> None:  # type: ignore[no-untyped-def]
    chains, trades = history
    rows = resolved(trades, flt, {c.id: c.strategy for c in chains})
    days: dict[str, list[Decimal]] = defaultdict(list)
    for t in rows:
        days[local(t, flt).strftime("%Y-%m-%d")].append(t.profit or D(0))
    running = D(0)
    expected = []
    for day in sorted(days):
        running += sum(days[day], D(0))
        expected.append((day, len(days[day]), sum(days[day], D(0)), running))
    async with session_factory() as session:
        points = await queries.equity(session, flt)
    assert [(p.day, p.trades, p.profit, p.cumulative) for p in points] == expected


@pytest.mark.parametrize(
    "flt", FILTERS[:6], ids=lambda f: f"{f.account_type.value}-{f.group_id}-{f.asset}"
)
async def test_the_chain_depth_matches_the_reference(
    session_factory: Factory, history, flt: ReportFilter
) -> None:  # type: ignore[no-untyped-def]
    chains, trades = history
    by_chain: dict[object, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        if t.status in RESULT_TRADE_STATUSES:
            by_chain[t.chain_id].append(t)
    selected = []
    for c in chains:
        if c.account_type is not flt.account_type or c.status in (
            ChainStatus.PENDING,
            ChainStatus.OPEN,
        ):
            continue
        if flt.group_id is not None and c.group_id != flt.group_id:
            continue
        if flt.asset is not None and c.asset != flt.asset:
            continue
        if flt.strategy is not None and c.strategy is not flt.strategy:
            continue
        if flt.since is not None and c.created_at < flt.since:
            continue
        if flt.until is not None and c.created_at >= flt.until:
            continue
        if by_chain.get(c.id):
            selected.append(c)

    async with session_factory() as session:
        report = await queries.depth(session, flt)
    assert report.chains == len(selected)
    assert report.completed == sum(c.status is ChainStatus.COMPLETED for c in selected)
    assert report.exhausted == sum(c.status is ChainStatus.EXHAUSTED for c in selected)
    total_profit = sum((t.profit or D(0) for c in selected for t in by_chain[c.id]), D(0))
    if selected:
        assert report.avg_chain_profit == (total_profit / len(selected)).quantize(D("0.01"))
    deepest = max((max(t.step for t in by_chain[c.id]) for c in selected), default=-1)
    assert len(report.steps) == deepest + 1
    for row in report.steps:
        step = row.step - 1
        reaching = [c for c in selected if max(t.step for t in by_chain[c.id]) >= step]
        here = [t for c in selected for t in by_chain[c.id] if t.step == step]
        ending = [c for c in selected if max(t.step for t in by_chain[c.id]) == step]
        assert row.chains_reaching == len(reaching)
        assert (row.trades, row.wins, row.losses) == (
            len(here),
            sum(t.status is TradeStatus.WON for t in here),
            sum(t.status is TradeStatus.LOST for t in here),
        )
        assert (row.staked, row.profit) == (
            sum((t.stake for t in here), D(0)),
            sum((t.profit or D(0) for t in here), D(0)),
        )
        assert row.chains_ending_here == len(ending)
        assert row.chains_won_here == sum(c.status is ChainStatus.COMPLETED for c in ending)
        assert row.chain_profit_ending_here == sum(
            (t.profit or D(0) for c in ending for t in by_chain[c.id]), D(0)
        )
