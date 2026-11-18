"""Reports by broker (decision D-75, Phase 21): each broker's money is reported on its own unless
"all brokers" is chosen, and the figures agree with the Trades page filtered the same way."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.enums import AccountType, Broker, ChainStatus, TradeStatus
from app.reports import queries
from app.reports.models import BreakdownKind, ReportFilter
from tests.api_support import running_api
from tests.factories import NOW, make_chain, make_group, make_trade

Factory = async_sessionmaker[AsyncSession]
D = Decimal

# The seed, worked out by hand:
#   Quotex group: one chain, step 0 lost (-1.00), step 1 won (+1.60)  -> 2 trades, +0.60
#   Deriv group:  one chain, won (+0.88); another lost (-1.00); one failed (not counted)
#                 -> 2 resolved trades, -0.12, staked 2.00
QUOTEX_PROFIT, DERIV_PROFIT = D("0.60"), D("-0.12")


async def seed(factory: Factory) -> None:
    async with factory.begin() as db:
        quotex = await GroupRepository(db).add(make_group(title="Quotex group"))
        deriv = await GroupRepository(db).add(
            make_group(title="Deriv group", telegram_chat_id=-1002, broker=Broker.DERIV)
        )
    assert quotex.id is not None and deriv.id is not None
    when = NOW + timedelta(minutes=5)

    async def chain_with(
        group_id: int, broker: Broker, results: list[tuple[TradeStatus, str]]
    ) -> None:
        chain = make_chain(group_id, status=ChainStatus.COMPLETED, broker=broker)
        async with factory.begin() as db:
            await ChainRepository(db).upsert(chain)
            for step, (status, profit) in enumerate(results):
                await TradeRepository(db).upsert(
                    make_trade(
                        chain.id,
                        group_id,
                        step=step,
                        status=status,
                        profit=None if profit == "" else D(profit),
                        stake=D("1.00"),
                        payout_pct=88 if broker is Broker.DERIV else 80,
                        settled_at=when + timedelta(seconds=step),
                        broker=broker,
                    )
                )

    await chain_with(
        quotex.id, Broker.QUOTEX, [(TradeStatus.LOST, "-1.00"), (TradeStatus.WON, "1.60")]
    )
    await chain_with(deriv.id, Broker.DERIV, [(TradeStatus.WON, "0.88")])
    await chain_with(deriv.id, Broker.DERIV, [(TradeStatus.LOST, "-1.00")])
    await chain_with(deriv.id, Broker.DERIV, [(TradeStatus.FAILED, "")])


async def test_each_broker_is_reported_on_its_own(session_factory: Factory) -> None:
    await seed(session_factory)
    async with session_factory() as db:
        quotex = await queries.summary(db, ReportFilter(AccountType.DEMO, broker=Broker.QUOTEX))
        deriv = await queries.summary(db, ReportFilter(AccountType.DEMO, broker=Broker.DERIV))
        both = await queries.summary(db, ReportFilter(AccountType.DEMO))
        deriv_depth = await queries.depth(db, ReportFilter(AccountType.DEMO, broker=Broker.DERIV))
    assert (quotex.metrics.trades, quotex.metrics.profit) == (2, QUOTEX_PROFIT)
    assert (deriv.metrics.trades, deriv.metrics.profit) == (2, DERIV_PROFIT)
    assert deriv.not_counted.failed == 1 and quotex.not_counted.failed == 0
    assert (both.metrics.trades, both.metrics.profit) == (4, QUOTEX_PROFIT + DERIV_PROFIT)
    assert deriv_depth.chains == 2  # the two Deriv chains with a result


async def test_the_breakdown_by_broker_names_each_broker(session_factory: Factory) -> None:
    await seed(session_factory)
    async with session_factory() as db:
        rows = await queries.breakdown(db, ReportFilter(AccountType.DEMO), BreakdownKind.BROKER)
    assert [(r.key, r.label, r.metrics.trades, r.metrics.profit) for r in rows] == [
        ("quotex", "Quotex", 2, QUOTEX_PROFIT),
        ("deriv", "Deriv", 2, DERIV_PROFIT),
    ]


async def test_the_broker_report_agrees_with_the_trades_page(tmp_path: Path) -> None:
    async with running_api(tmp_path, seed=seed) as rig:
        default = (await rig.client.get("/api/v1/reports/summary")).json()
        assert default["filter"]["broker"] == "quotex"  # never two brokers' money unasked
        assert D(default["metrics"]["profit"]) == QUOTEX_PROFIT

        for broker, profit in (("quotex", QUOTEX_PROFIT), ("deriv", DERIV_PROFIT)):
            summary = (
                await rig.client.get("/api/v1/reports/summary", params={"broker": broker})
            ).json()
            trades: Any = (await rig.client.get("/api/v1/trades", params={"broker": broker})).json()
            resolved = [t for t in trades["items"] if t["status"] in ("won", "lost", "draw")]
            assert all(t["broker"] == broker for t in trades["items"])
            assert summary["metrics"]["trades"] == len(resolved) == 2
            assert D(summary["metrics"]["profit"]) == sum(D(t["profit"]) for t in resolved)
            assert D(summary["metrics"]["profit"]) == profit

        everything = (
            await rig.client.get("/api/v1/reports/summary", params={"broker": "all"})
        ).json()
        assert everything["filter"]["broker"] is None
        assert everything["metrics"]["trades"] == 4

        chains = (await rig.client.get("/api/v1/chains", params={"broker": "deriv"})).json()
        assert chains["total"] == 3 and all(c["broker"] == "deriv" for c in chains["items"])

        breakdown = (
            await rig.client.get(
                "/api/v1/reports/breakdown", params={"by": "broker", "broker": "all"}
            )
        ).json()
        assert [(r["key"], r["label"]) for r in breakdown["rows"]] == [
            ("quotex", "Quotex"),
            ("deriv", "Deriv"),
        ]

        csv = await rig.client.get("/api/v1/reports/export/trades.csv", params={"broker": "deriv"})
        lines = csv.content.decode("utf-8-sig").splitlines()
        header = lines[0].split(",")
        assert header[2:4] == ["account", "broker"]
        assert len(lines) == 4  # the three Deriv trades (the failed one too) and the header
        assert all(line.split(",")[3] == "deriv" for line in lines[1:])


async def test_an_unknown_broker_is_refused(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        response = await rig.client.get("/api/v1/reports/summary", params={"broker": "iq"})
        assert response.status_code == 422
