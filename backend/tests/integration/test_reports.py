"""The report queries against the hand-made history in `tests/reports_support.py`.

Every figure below was computed by hand from that table; the working is in the comments.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chain
from app.domain.enums import AccountType, Strategy
from app.reports import queries
from app.reports.models import BreakdownKind, ReportFilter
from tests.reports_support import at, seed_hand_made_history

Factory = async_sessionmaker[AsyncSession]
D = Decimal
DEMO = ReportFilter(account_type=AccountType.DEMO)


@pytest.fixture(autouse=True)
async def history(session_factory: Factory) -> None:
    await seed_hand_made_history(session_factory)


async def run[T](factory: Factory, call):  # type: ignore[no-untyped-def]
    async with factory() as session:
        return await call(session)


# --- the summary ---------------------------------------------------------------------------------
# Resolved demo trades t1..t9: results L W W L L L L W W -> 4 wins, 5 losses, 9 trades.
# profit  -1 +1.6 +0.8 -1 -2 -4 -2 +3.4 +1.7 = -2.50      staked 1+2+1+1+2+4+2+4+2 = 19.00
# average payout (6 x 80 + 3 x 85) / 9 = 735 / 9 = 81.666...


async def test_the_summary_totals(session_factory: Factory) -> None:
    summary = await run(session_factory, lambda s: queries.summary(s, DEMO))
    m = summary.metrics
    assert (m.trades, m.wins, m.losses, m.draws) == (9, 4, 5, 0)
    assert m.profit == D("-2.50") and m.staked == D("19.00")
    assert m.win_rate == pytest.approx(4 / 9)
    assert m.roi == pytest.approx(-2.5 / 19)  # -0.1316
    assert m.avg_payout_pct == pytest.approx(735 / 9)
    assert m.avg_stake == D("2.11")  # 19 / 9 = 2.111...
    assert m.sample == "tiny"  # fewer than 10 trades: nothing to read into


async def test_what_is_not_counted_is_reported_not_hidden(session_factory: Factory) -> None:
    summary = await run(session_factory, lambda s: queries.summary(s, DEMO))
    assert (summary.not_counted.failed, summary.not_counted.unknown) == (1, 1)  # t10, t11
    assert summary.not_counted.open == 1  # t12


async def test_a_trade_that_is_still_pending_counts_as_open(session_factory: Factory) -> None:
    from app.db.repositories import TradeRepository
    from app.domain.enums import TradeStatus
    from app.domain.records import TradeRecord
    from tests.factories import make_trade

    async with session_factory() as session:
        chain_id = (await session.execute(select(Chain.id).where(Chain.asset == "EURUSD"))).first()[
            0
        ]  # type: ignore[index]
    async with session_factory.begin() as session:
        pending: TradeRecord = make_trade(
            chain_id, 1, status=TradeStatus.PENDING, created_at=at(4, 14)
        )
        await TradeRepository(session).upsert(pending)
    summary = await run(session_factory, lambda s: queries.summary(s, DEMO))
    assert summary.not_counted.open == 2  # t12 (open) and the pending one


async def test_streaks(session_factory: Factory) -> None:
    # in the order they settled: L W W L L L L W W
    streaks = (await run(session_factory, lambda s: queries.summary(s, DEMO))).streaks
    assert streaks.longest_win == 2  # t2,t3 (and t8,t9)
    assert streaks.longest_loss == 4  # t4..t7
    assert streaks.current == 2  # the last two were wins


async def test_drawdown(session_factory: Factory) -> None:
    # running total after each trade: -1.00 0.60 1.40 0.40 -1.60 -5.60 -7.60 -4.20 -2.50
    # highest point 1.40 (Mon 11-02), lowest after it -7.60 (Tue 11-03 23:30) -> 9.00
    drawdown = (await run(session_factory, lambda s: queries.summary(s, DEMO))).drawdown
    assert drawdown.max_amount == D("9.00")
    assert (drawdown.peak_day, drawdown.trough_day) == ("2026-11-02", "2026-11-03")
    assert drawdown.current_amount == D("3.90")  # 1.40 - (-2.50)


async def test_expected_against_actual(session_factory: Factory) -> None:
    # break-even win rate at a payout of 81.67% is 1 / 1.81667 = 0.5505; actual 4/9 = 0.4444
    # standard error sqrt(0.5505 x 0.4495 / 9) = 0.1658 -> z = (0.4444 - 0.5505) / 0.1658 = -0.64
    e = (await run(session_factory, lambda s: queries.summary(s, DEMO))).expectation
    assert e.breakeven_win_rate == pytest.approx(0.55046, abs=1e-4)
    assert e.actual_win_rate == pytest.approx(0.44444, abs=1e-4)
    assert e.edge == pytest.approx(-0.10602, abs=1e-4)
    assert e.z_score == pytest.approx(-0.639, abs=1e-2)
    assert e.verdict == "not_enough_data"  # nine trades say nothing, whatever the z-score


async def test_the_first_and_last_day(session_factory: Factory) -> None:
    summary = await run(session_factory, lambda s: queries.summary(s, DEMO))
    assert (summary.first_day, summary.last_day) == ("2026-11-02", "2026-11-04")


# --- demo and real are never mixed -------------------------------------------------------


async def test_real_money_is_reported_on_its_own(session_factory: Factory) -> None:
    real = ReportFilter(account_type=AccountType.REAL)
    summary = await run(session_factory, lambda s: queries.summary(s, real))
    assert (summary.metrics.trades, summary.metrics.wins) == (1, 1)  # only t13
    assert summary.metrics.profit == D("0.80")
    groups = await run(session_factory, lambda s: queries.breakdown(s, real, BreakdownKind.GROUP))
    assert [(r.label, r.metrics.trades) for r in groups] == [("Alpha", 1)]


# --- breakdowns ----------------------------------------------------------------------------------


def table(rows):  # type: ignore[no-untyped-def]
    """(label, trades, wins, losses, profit, staked) for each row, to compare at a glance."""
    return [
        (
            r.label,
            r.metrics.trades,
            r.metrics.wins,
            r.metrics.losses,
            r.metrics.profit,
            r.metrics.staked,
        )
        for r in rows
    ]


async def test_by_group(session_factory: Factory) -> None:
    # Alpha: t1..t6  2 wins 4 losses, profit -1+1.6+0.8-1-2-4 = -5.60, staked 11.00
    # Beta:  t7..t9  2 wins 1 loss,   profit -2+3.4+1.7 = +3.10,        staked 8.00
    rows = await run(session_factory, lambda s: queries.breakdown(s, DEMO, BreakdownKind.GROUP))
    assert table(rows) == [  # best first
        ("Beta", 3, 2, 1, D("3.10"), D("8.00")),
        ("Alpha", 6, 2, 4, D("-5.60"), D("11.00")),
    ]
    assert [r.key for r in rows] == ["2", "1"]


async def test_by_asset(session_factory: Factory) -> None:
    # EURUSD: t1 t2 t3 t9  3 wins 1 loss, profit -1+1.6+0.8+1.7 = +3.10, staked 1+2+1+2 = 6.00
    # GBPUSD: t4 t5 t6 t7 t8  1 win 4 losses, profit -1-2-4-2+3.4 = -5.60, staked 1+2+4+2+4 = 13.00
    rows = await run(session_factory, lambda s: queries.breakdown(s, DEMO, BreakdownKind.ASSET))
    assert table(rows) == [
        ("EURUSD", 4, 3, 1, D("3.10"), D("6.00")),
        ("GBPUSD", 5, 1, 4, D("-5.60"), D("13.00")),
    ]


async def test_by_strategy_uses_the_strategy_each_trade_was_run_under(
    session_factory: Factory,
) -> None:
    rows = await run(session_factory, lambda s: queries.breakdown(s, DEMO, BreakdownKind.STRATEGY))
    assert table(rows) == [  # martingale = group 1's chains, flip = group 2's
        ("flip_every_loss", 3, 2, 1, D("3.10"), D("8.00")),
        ("martingale", 6, 2, 4, D("-5.60"), D("11.00")),
    ]


async def test_by_hour_of_day_in_utc_has_a_row_for_every_hour(session_factory: Factory) -> None:
    # settled hours (UTC): t1 10, t2 10, t3 14, t4 9, t5 9, t6 9, t7 23, t8 0, t9 12
    rows = await run(session_factory, lambda s: queries.breakdown(s, DEMO, BreakdownKind.HOUR))
    assert [r.key for r in rows] == [str(h) for h in range(24)]
    by_hour = {r.key: (r.metrics.trades, r.metrics.profit) for r in rows if r.metrics.trades}
    assert by_hour == {
        "9": (3, D("-7.00")),  # t4 t5 t6: -1 -2 -4
        "10": (2, D("0.60")),  # t1 t2: -1 +1.6
        "12": (1, D("1.70")),  # t9
        "14": (1, D("0.80")),  # t3
        "23": (1, D("-2.00")),  # t7
        "0": (1, D("3.40")),  # t8
    }
    assert rows[9].label == "09:00" and rows[0].metrics.profit == D("3.40")
    assert rows[3].metrics == rows[4].metrics  # quiet hours are zeros, not missing


async def test_by_hour_follows_the_owners_clock(session_factory: Factory) -> None:
    # UTC-3 (offset -180): t1 07:05, t2 07:10, t3 11:30, t4 06:00, t5 06:05, t6 06:10,
    # t7 20:30, t8 (Tue 11-03 21:10), t9 09:00
    flt = ReportFilter(account_type=AccountType.DEMO, utc_offset_minutes=-180)
    rows = await run(session_factory, lambda s: queries.breakdown(s, flt, BreakdownKind.HOUR))
    seen = {r.key: r.metrics.trades for r in rows if r.metrics.trades}
    assert seen == {"6": 3, "7": 2, "9": 1, "11": 1, "20": 1, "21": 1}


async def test_by_weekday(session_factory: Factory) -> None:
    # Mon 11-02: t1 t2 t3  (2 wins 1 loss) +1.40      Tue 11-03: t4 t5 t6 t7  (4 losses) -9.00
    # Wed 11-04: t8 t9     (2 wins)        +5.10
    rows = await run(session_factory, lambda s: queries.breakdown(s, DEMO, BreakdownKind.WEEKDAY))
    assert [r.label for r in rows] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert [(r.metrics.trades, r.metrics.profit) for r in rows[:4]] == [
        (3, D("1.40")),
        (4, D("-9.00")),
        (2, D("5.10")),
        (0, D("0")),
    ]


async def test_the_weekday_follows_the_owners_clock_across_midnight(
    session_factory: Factory,
) -> None:
    # at UTC+3 (offset +180) t7 (Tue 23:30 UTC) is already Wed 02:30, and t4..t6 stay on Tuesday
    flt = ReportFilter(account_type=AccountType.DEMO, utc_offset_minutes=180)
    rows = await run(session_factory, lambda s: queries.breakdown(s, flt, BreakdownKind.WEEKDAY))
    assert [r.metrics.trades for r in rows[:3]] == [
        3,
        3,
        3,
    ]  # Mon t1 t2 t3; Tue t4 t5 t6; Wed t7 t8 t9


# --- the daily series ----------------------------------------------------------------------------


async def test_the_daily_series_and_its_running_total(session_factory: Factory) -> None:
    points = await run(session_factory, lambda s: queries.equity(s, DEMO))
    assert [(p.day, p.trades, p.profit, p.cumulative) for p in points] == [
        ("2026-11-02", 3, D("1.40"), D("1.40")),
        ("2026-11-03", 4, D("-9.00"), D("-7.60")),
        ("2026-11-04", 2, D("5.10"), D("-2.50")),
    ]


async def test_the_daily_series_uses_the_owners_day(session_factory: Factory) -> None:
    # at UTC-3 t7 (Tue 23:30 UTC) is Tue 20:30 and t8 (Wed 00:10 UTC) is Tue 21:10: both Tuesday
    flt = ReportFilter(account_type=AccountType.DEMO, utc_offset_minutes=-180)
    points = await run(session_factory, lambda s: queries.equity(s, flt))
    assert [(p.day, p.trades, p.profit) for p in points] == [
        ("2026-11-02", 3, D("1.40")),
        ("2026-11-03", 5, D("-5.60")),  # t4 t5 t6 t7 t8: -1 -2 -4 -2 +3.4
        ("2026-11-04", 1, D("1.70")),
    ]


# --- chain depth -------------------------------------------------------------------------
# Chains with a result: A (trades at steps 0,1), B (0), C (0,1,2), D (0,1), E (0) -> 5 chains,
# 4 completed, 1 exhausted. Whole-chain results: A +0.60, B +0.80, C -7.00, D +1.40, E +1.70
# add up to -2.50.


async def test_how_far_chains_go_and_what_it_costs(session_factory: Factory) -> None:
    report = await run(session_factory, lambda s: queries.depth(s, DEMO))
    assert (report.chains, report.completed, report.exhausted, report.other) == (5, 4, 1, 0)
    assert report.avg_chain_profit == D("-0.50")  # -2.50 / 5

    first, second, third = report.steps
    # trade 1: every chain; trades t1 t3 t4 t7 t9 (2 wins, 3 losses), stakes 1+1+1+2+2,
    # results -1 +0.8 -1 -2 +1.7
    assert (first.step, first.chains_reaching, first.share_of_chains) == (1, 5, 1.0)
    assert (first.trades, first.wins, first.losses) == (5, 2, 3)
    assert (first.staked, first.profit) == (D("7.00"), D("-1.50"))
    assert (first.chains_ending_here, first.chains_won_here) == (2, 2)  # B and E
    assert first.chain_profit_ending_here == D("2.50")  # +0.80 +1.70
    # trade 2: chains A, C, D got that far; trades t2 t5 t8 (2 wins, 1 loss), stakes 2+2+4
    assert (second.chains_reaching, second.share_of_chains) == (3, 0.6)
    assert (second.trades, second.wins, second.losses) == (3, 2, 1)
    assert (second.staked, second.profit) == (D("8.00"), D("3.00"))  # +1.6 -2 +3.4
    assert (second.chains_ending_here, second.chains_won_here) == (2, 2)  # A and D
    assert second.chain_profit_ending_here == D("2.00")  # +0.60 +1.40
    # trade 3: only chain C, which lost it and ended exhausted
    assert (third.chains_reaching, third.share_of_chains) == (1, 0.2)
    assert (third.trades, third.wins, third.losses) == (1, 0, 1)
    assert (third.staked, third.profit) == (D("4.00"), D("-4.00"))
    assert (third.chains_ending_here, third.chains_won_here) == (1, 0)
    assert third.chain_profit_ending_here == D("-7.00")


async def test_chains_that_are_still_open_or_have_no_result_are_not_in_the_depth(
    session_factory: Factory,
) -> None:
    report = await run(session_factory, lambda s: queries.depth(s, DEMO))
    assert report.chains == 5  # not F (failed trade), F2 (unknown), G (still open)


async def test_depth_of_one_group(session_factory: Factory) -> None:
    beta = ReportFilter(account_type=AccountType.DEMO, group_id=2)
    report = await run(session_factory, lambda s: queries.depth(s, beta))
    assert report.chains == 2 and [r.chains_reaching for r in report.steps] == [
        2,
        1,
    ]  # D (0,1), E (0)


# --- filters -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flt", "trades", "profit"),
    [
        (ReportFilter(AccountType.DEMO, group_id=1), 6, "-5.60"),
        (ReportFilter(AccountType.DEMO, group_id=2), 3, "3.10"),
        (ReportFilter(AccountType.DEMO, asset="EURUSD"), 4, "3.10"),
        (ReportFilter(AccountType.DEMO, strategy=Strategy.FLIP_EVERY_LOSS), 3, "3.10"),
        (ReportFilter(AccountType.DEMO, strategy=Strategy.MARTINGALE, asset="GBPUSD"), 3, "-7.00"),
        (ReportFilter(AccountType.DEMO, group_id=2, asset="EURUSD"), 1, "1.70"),
        (ReportFilter(AccountType.DEMO, group_id=9), 0, "0"),
        # time: [since, until) on the time of settling
        (ReportFilter(AccountType.DEMO, since=at(3, 0)), 6, "-3.90"),  # t4..t9: -9 + 3.4 + 1.7
        (ReportFilter(AccountType.DEMO, until=at(3, 0)), 3, "1.40"),
        (ReportFilter(AccountType.DEMO, since=at(2, 10, 10), until=at(2, 14, 30)), 1, "1.60"),
        (ReportFilter(AccountType.DEMO, since=at(2, 10, 10), until=at(2, 14, 31)), 2, "2.40"),
    ],
)
async def test_every_filter_narrows_the_totals_correctly(
    session_factory: Factory, flt: ReportFilter, trades: int, profit: str
) -> None:
    summary = await run(session_factory, lambda s: queries.summary(s, flt))
    assert summary.metrics.trades == trades
    assert summary.metrics.profit == D(profit)


async def test_the_range_is_inclusive_at_the_start_and_exclusive_at_the_end(
    session_factory: Factory,
) -> None:
    exactly = ReportFilter(AccountType.DEMO, since=at(2, 10, 5), until=at(2, 10, 6))
    assert (
        await run(session_factory, lambda s: queries.summary(s, exactly))
    ).metrics.trades == 1  # t1
    just_after = ReportFilter(AccountType.DEMO, since=at(2, 10, 6), until=at(2, 10, 10))
    assert (
        await run(session_factory, lambda s: queries.summary(s, just_after))
    ).metrics.trades == 0
    ends_on_t2 = ReportFilter(AccountType.DEMO, since=at(2, 10, 6), until=at(2, 10, 11))
    assert (
        await run(session_factory, lambda s: queries.summary(s, ends_on_t2))
    ).metrics.trades == 1


async def test_a_filter_that_matches_nothing_gives_zeros_not_errors(
    session_factory: Factory,
) -> None:
    nothing = ReportFilter(AccountType.DEMO, group_id=99)
    summary = await run(session_factory, lambda s: queries.summary(s, nothing))
    assert summary.metrics.trades == 0 and summary.metrics.profit == D("0")
    assert summary.metrics.win_rate is None and summary.metrics.roi is None
    assert summary.streaks.current == 0 and summary.drawdown.max_amount == D("0")
    assert summary.expectation.verdict == "not_enough_data"
    assert await run(session_factory, lambda s: queries.equity(s, nothing)) == []
    assert (await run(session_factory, lambda s: queries.depth(s, nothing))).chains == 0
    assert (
        await run(session_factory, lambda s: queries.breakdown(s, nothing, BreakdownKind.ASSET))
        == []
    )


def test_a_range_must_run_forwards() -> None:
    with pytest.raises(ValueError, match="before its end"):
        ReportFilter(AccountType.DEMO, since=at(3, 0), until=at(2, 0))
    with pytest.raises(ValueError, match="utc_offset_minutes"):
        ReportFilter(AccountType.DEMO, utc_offset_minutes=841)
