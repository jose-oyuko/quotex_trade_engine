"""`npm run latency`: medians and percentiles of the timings stored on every trade."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.enums import AccountType, TradeStatus
from scripts.latency_report import collect, describe, format_report, main, percentile
from tests.factories import NOW, make_chain, make_group, make_trade

Factory = async_sessionmaker[AsyncSession]
MS = 1_000_000


def test_percentiles_use_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 0.5) == 3.0
    assert percentile(values, 0.95) == 5.0
    assert percentile(values, 0.0) == 1.0
    assert percentile([7.0], 0.99) == 7.0


def test_describe_summarises_and_handles_nothing() -> None:
    stats = describe([5.0, 1.0, 3.0, 2.0, 4.0])
    assert stats is not None
    assert (stats.count, stats.median_ms, stats.p95_ms, stats.max_ms) == (5, 3.0, 5.0, 5.0)
    assert describe([]) is None


async def seed(factory: Factory, dbfile: Path) -> None:
    async with factory.begin() as session:
        group = await GroupRepository(session).add(make_group())
        assert group.id is not None
        chain = make_chain(group.id)
        await ChainRepository(session).upsert(chain)
        trades = TradeRepository(session)
        for n in range(1, 6):  # five first trades: signal -> order of 1..5 ms, decision 0.5..2.5
            base = n * 10_000 * MS
            await trades.upsert(
                make_trade(
                    chain.id, group.id, step=0, status=TradeStatus.WON,
                    t_msg_received_ns=base, t_parsed_ns=base + MS // 10,
                    t_decided_ns=base + n * MS // 2, t_order_sent_ns=base + n * MS,
                    t_order_acked_ns=base + n * MS + 100 * MS,
                )
            )  # fmt: skip
        # a follow-up has no message time; a real-money trade; a refused one; one older than a week
        await trades.upsert(
            make_trade(
                chain.id, group.id, step=1, status=TradeStatus.LOST,
                t_decided_ns=10 * MS, t_order_sent_ns=11 * MS, t_order_acked_ns=51 * MS,
            )
        )  # fmt: skip
        await trades.upsert(
            make_trade(
                chain.id, group.id, step=0, status=TradeStatus.WON, account_type=AccountType.REAL,
                t_msg_received_ns=0, t_decided_ns=1 * MS, t_order_sent_ns=9 * MS,
                t_order_acked_ns=99 * MS,
            )
        )  # fmt: skip
        await trades.upsert(
            make_trade(chain.id, group.id, status=TradeStatus.FAILED, t_order_sent_ns=MS)
        )
        await trades.upsert(
            make_trade(
                chain.id, group.id, status=TradeStatus.WON, created_at=NOW - timedelta(days=30),
                t_msg_received_ns=0, t_order_sent_ns=777 * MS,
            )
        )  # fmt: skip


async def test_the_report_reads_the_timings_stored_on_the_trades(
    session_factory: Factory, tmp_path: Path
) -> None:
    await seed(session_factory, tmp_path)
    path = session_factory.kw["bind"].url.database  # the SQLite file the fixture created
    with sqlite3.connect(path) as db:
        demo = collect(db, account="demo")["demo"]
        everything = collect(db)
    signal, decision, ack = demo["signal -> order"], demo["decision -> order"], demo["order -> ack"]
    assert signal is not None and decision is not None and ack is not None
    # first trades only (a follow-up has no message time); the 30-day-old one is in "all time"
    assert signal.count == 6 and signal.median_ms == 3.5 and signal.max_ms == 777.0
    assert decision.count == 6  # the five first trades and the follow-up (the old one has none)
    assert ack.count == 6 and ack.median_ms == 100.0  # 5 x 100 ms and one of 40 ms
    assert set(everything) == {"demo", "real"}  # kept apart: demo and real are never mixed
    real_signal = everything["real"]["signal -> order"]
    assert real_signal is not None and (real_signal.count, real_signal.median_ms) == (1, 9.0)


async def test_a_period_and_an_account_narrow_the_report(
    session_factory: Factory, tmp_path: Path
) -> None:
    await seed(session_factory, tmp_path)
    path = session_factory.kw["bind"].url.database
    with sqlite3.connect(path) as db:
        recent = collect(db, account="demo", since=NOW - timedelta(days=7))["demo"]
    signal = recent["signal -> order"]
    assert signal is not None and signal.count == 5 and signal.max_ms == 5.0  # the old one is out


async def test_the_text_report_and_the_command(
    session_factory: Factory, tmp_path: Path, capsys: object
) -> None:
    await seed(session_factory, tmp_path)
    path = session_factory.kw["bind"].url.database
    with sqlite3.connect(path) as db:
        text = format_report(collect(db))
    assert "DEMO account" in text and "REAL account" in text
    assert "signal -> order" in text and "median" in text and "99th" in text
    assert format_report({}).startswith("No timed trades yet")
    assert main(["--database", str(path), "--account", "demo", "--days", "7"]) == 0
    assert main(["--database", str(tmp_path / "missing.db")]) == 1
