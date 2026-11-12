"""Reports by trading session (decision D-71): a session's trades are the trades of its hidden
group, so the figures must agree with the Trades page for that group."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.enums import AccountType, ChainStatus, Strategy, TradeStatus
from app.reports import queries
from app.reports.models import BreakdownKind, ReportFilter
from tests.api_support import running_api
from tests.factories import NOW, make_chain, make_group, make_trade
from tests.integration.test_session_storage import add_session

Factory = async_sessionmaker[AsyncSession]
D = Decimal
DEMO = ReportFilter(AccountType.DEMO)

# What the seed below holds, worked out by hand:
#   session "Test session": chain A step 0 lost (-1.00, stake 1.00), step 1 won (+1.60, stake 2.00);
#                           chain B step 0 won (+0.80, stake 1.00); one failed trade (not counted)
#                           -> 3 resolved trades, 2 wins, 1 loss, profit +1.40, staked 4.00
#   a Telegram group:       one won (+0.80) and one lost (-1.00) trade, which must stay out of it
SESSION_PROFIT, SESSION_STAKED = D("1.40"), D("4.00")


async def seed(factory: Factory) -> None:
    hidden, session = await add_session(factory, id=None)
    assert hidden.id is not None and session.id is not None
    async with factory.begin() as db:
        telegram = await GroupRepository(db).add(make_group())
    assert telegram.id is not None
    when = NOW + timedelta(minutes=5)

    async def chain_with(group_id: int, results: list[tuple[TradeStatus, str, str]]) -> None:
        chain = make_chain(
            group_id, strategy=Strategy.FLIP_EVERY_LOSS, status=ChainStatus.COMPLETED
        )
        async with factory.begin() as db:
            await ChainRepository(db).upsert(chain)
            for step, (status, profit, stake) in enumerate(results):
                await TradeRepository(db).upsert(
                    make_trade(
                        chain.id,
                        group_id,
                        step=step,
                        status=status,
                        profit=None if profit == "" else D(profit),
                        stake=D(stake),
                        payout_pct=80,
                        settled_at=when + timedelta(seconds=step),
                    )
                )

    await chain_with(
        hidden.id,
        [(TradeStatus.LOST, "-1.00", "1.00"), (TradeStatus.WON, "1.60", "2.00")],
    )
    await chain_with(hidden.id, [(TradeStatus.WON, "0.80", "1.00")])
    await chain_with(hidden.id, [(TradeStatus.FAILED, "", "1.00")])
    await chain_with(
        telegram.id, [(TradeStatus.WON, "0.80", "1.00"), (TradeStatus.LOST, "-1.00", "1.00")]
    )


async def test_the_breakdown_by_session_lists_the_sessions_and_leaves_telegram_groups_out(
    session_factory: Factory,
) -> None:
    await seed(session_factory)
    async with session_factory() as db:
        rows = await queries.breakdown(db, DEMO, BreakdownKind.SESSION)
    assert [(r.key, r.label) for r in rows] == [("1", "Test session")]
    m = rows[0].metrics
    assert (m.trades, m.wins, m.losses, m.draws) == (3, 2, 1, 0)
    assert (m.profit, m.staked) == (SESSION_PROFIT, SESSION_STAKED)


async def test_the_session_filter_keeps_only_that_sessions_trades(session_factory: Factory) -> None:
    await seed(session_factory)
    async with session_factory() as db:
        everything = await queries.summary(db, DEMO)
        only = await queries.summary(db, ReportFilter(AccountType.DEMO, session_id=1))
        nothing = await queries.summary(db, ReportFilter(AccountType.DEMO, session_id=99))
        depth = await queries.depth(db, ReportFilter(AccountType.DEMO, session_id=1))
    assert everything.metrics.trades == 5  # three of the session and two of the Telegram group
    assert (only.metrics.trades, only.metrics.profit) == (3, SESSION_PROFIT)
    assert (only.not_counted.failed, only.not_counted.unknown) == (1, 0)
    assert nothing.metrics.trades == 0
    assert depth.chains == 2  # chains with a result: not the failed one, not the Telegram group's


async def test_the_session_report_agrees_with_the_trades_page(tmp_path: Path) -> None:
    async with running_api(tmp_path, seed=seed) as rig:
        sessions = (await rig.client.get("/api/v1/sessions")).json()["items"]
        assert [s["id"] for s in sessions] == [1]
        group_id = sessions[0]["group_id"]

        summary = (await rig.client.get("/api/v1/reports/summary", params={"session_id": 1})).json()
        assert summary["filter"]["session_id"] == 1
        trades: Any = (await rig.client.get("/api/v1/trades", params={"group_id": group_id})).json()
        resolved = [t for t in trades["items"] if t["status"] in ("won", "lost", "draw")]
        assert summary["metrics"]["trades"] == len(resolved) == 3
        assert D(summary["metrics"]["profit"]) == sum(D(t["profit"]) for t in resolved)

        breakdown = (
            await rig.client.get("/api/v1/reports/breakdown", params={"by": "session"})
        ).json()
        assert [(r["key"], r["label"]) for r in breakdown["rows"]] == [("1", "Test session")]
        assert breakdown["rows"][0]["metrics"]["trades"] == summary["metrics"]["trades"]

        csv_rows = await rig.client.get(
            "/api/v1/reports/export/breakdown.csv", params={"by": "session"}
        )
        assert csv_rows.status_code == 200 and "Test session" in csv_rows.text
