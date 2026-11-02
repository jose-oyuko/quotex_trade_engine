"""Report queries on a database of 100,000 trades (acceptance criterion of Phase 8).

Run with `-s` to see the timings that go into the phase report. The bounds are generous (several
times what this PC measures) so the test fails for a real regression, not a busy machine.
"""

from __future__ import annotations

import time
from random import Random

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import AccountType
from app.reports import queries
from app.reports.csvout import Delimiter, trades_csv
from app.reports.models import BreakdownKind, ReportFilter
from tests.reports_support import insert_history, random_history

Factory = async_sessionmaker[AsyncSession]
TRADES = 100_000
GROUPS = 6
BOUND_S = 4.0  # per report; typical is well under a second


async def timed(label: str, call, timings: dict[str, float]):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    result = await call()
    timings[label] = time.perf_counter() - started
    return result


async def test_every_report_is_fast_on_100k_trades(session_factory: Factory) -> None:
    chains: list = []  # type: ignore[type-arg]
    trades: list = []  # type: ignore[type-arg]
    rng = Random(100_000)  # noqa: S311
    while len(trades) < TRADES:
        more_chains, more_trades = random_history(rng, 5_000, groups=GROUPS, days=120)
        chains += more_chains
        trades += more_trades
    del trades[TRADES:]
    kept = {t.chain_id for t in trades}
    chains = [c for c in chains if c.id in kept]
    started = time.perf_counter()
    await insert_history(session_factory, GROUPS, chains, trades)
    seconds = time.perf_counter() - started
    print(f"\nseeded {len(trades):,} trades in {len(chains):,} chains in {seconds:.1f} s")

    demo = ReportFilter(AccountType.DEMO)
    in_range = ReportFilter(
        AccountType.DEMO, group_id=3, since=trades[10_000].created_at, utc_offset_minutes=-180
    )
    timings: dict[str, float] = {}
    async with session_factory() as session:
        summary = await timed(
            "summary (totals + streaks + drawdown)", lambda: queries.summary(session, demo), timings
        )
        for kind in BreakdownKind:
            await timed(
                f"breakdown by {kind.value}",
                lambda k=kind: queries.breakdown(session, demo, k),
                timings,
            )
        equity = await timed("daily equity curve", lambda: queries.equity(session, demo), timings)
        depth = await timed("chain depth", lambda: queries.depth(session, demo), timings)
        await timed(
            "summary, filtered (group + range)", lambda: queries.summary(session, in_range), timings
        )
        await timed("depth, filtered", lambda: queries.depth(session, in_range), timings)

        async def export() -> int:
            size = 0
            async for chunk in trades_csv(queries.export_trades(session, demo), Delimiter.COMMA):
                size += len(chunk)
            return size

        size = await timed("trades CSV export (all demo trades)", export, timings)

    width = max(len(k) for k in timings)
    for label, seconds in timings.items():
        print(f"  {label:<{width}}  {seconds * 1000:7.0f} ms")
    print(f"  CSV size {size / 1_000_000:.1f} MB")

    assert summary.metrics.trades > 50_000
    assert len(equity) > 100 and depth.chains > 20_000
    slow = {k: round(v, 2) for k, v in timings.items() if v > BOUND_S}
    assert slow == {}, slow
