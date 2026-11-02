"""A small, fully hand-computed trading history for the report tests.

Every expected number in `test_reports.py` was worked out by hand from this table (and is explained
there), so a report that is wrong cannot agree with it by accident.

 trade | group | chain | asset  | step | stake | result | profit | payout | settled (UTC)
 ------+-------+-------+--------+------+-------+--------+--------+--------+------------------
  t1   | 1     | A     | EURUSD | 0    | 1.00  | lost   | -1.00  | 80     | Mon 11-02 10:05
  t2   | 1     | A     | EURUSD | 1    | 2.00  | won    | +1.60  | 80     | Mon 11-02 10:10
  t3   | 1     | B     | EURUSD | 0    | 1.00  | won    | +0.80  | 80     | Mon 11-02 14:30
  t4   | 1     | C     | GBPUSD | 0    | 1.00  | lost   | -1.00  | 80     | Tue 11-03 09:00
  t5   | 1     | C     | GBPUSD | 1    | 2.00  | lost   | -2.00  | 80     | Tue 11-03 09:05
  t6   | 1     | C     | GBPUSD | 2    | 4.00  | lost   | -4.00  | 80     | Tue 11-03 09:10
  t7   | 2     | D     | GBPUSD | 0    | 2.00  | lost   | -2.00  | 85     | Tue 11-03 23:30
  t8   | 2     | D     | GBPUSD | 1    | 4.00  | won    | +3.40  | 85     | Wed 11-04 00:10
  t9   | 2     | E     | EURUSD | 0    | 2.00  | won    | +1.70  | 85     | Wed 11-04 12:00
  t10  | 1     | F     | EURUSD | 0    | 1.00  | failed | -      | -      | (never settled)
  t11  | 2     | F2    | GBPUSD | 0    | 2.00  | unknown| -      | -      | (never settled)
  t12  | 1     | G     | EURUSD | 0    | 1.00  | open   | -      | -      | (still open)
  t13  | 1     | H     | EURUSD | 0    | 1.00  | won    | +0.80  | 80     | Mon 11-02 11:00 (REAL)

Chains: A, B, D, E completed; C exhausted; F failed; F2 unknown; G open; H (real) completed.
Group 1 "Alpha" runs martingale, group 2 "Beta" runs flip_every_loss.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.enums import AccountType, ChainStatus, Direction, Strategy, TradeStatus
from app.domain.ids import new_id
from app.domain.records import TradeRecord
from tests.factories import make_chain, make_group, make_trade

D = Decimal
W, L = TradeStatus.WON, TradeStatus.LOST


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in November 2026 (UTC)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


# (name, group, chain, asset, step, stake, status, profit, payout, settled_at)
TRADES: list[
    tuple[str, int, str, str, int, str, TradeStatus, str | None, int | None, datetime | None]
] = [
    ("t1", 1, "A", "EURUSD", 0, "1.00", L, "-1.00", 80, at(2, 10, 5)),
    ("t2", 1, "A", "EURUSD", 1, "2.00", W, "1.60", 80, at(2, 10, 10)),
    ("t3", 1, "B", "EURUSD", 0, "1.00", W, "0.80", 80, at(2, 14, 30)),
    ("t4", 1, "C", "GBPUSD", 0, "1.00", L, "-1.00", 80, at(3, 9, 0)),
    ("t5", 1, "C", "GBPUSD", 1, "2.00", L, "-2.00", 80, at(3, 9, 5)),
    ("t6", 1, "C", "GBPUSD", 2, "4.00", L, "-4.00", 80, at(3, 9, 10)),
    ("t7", 2, "D", "GBPUSD", 0, "2.00", L, "-2.00", 85, at(3, 23, 30)),
    ("t8", 2, "D", "GBPUSD", 1, "4.00", W, "3.40", 85, at(4, 0, 10)),
    ("t9", 2, "E", "EURUSD", 0, "2.00", W, "1.70", 85, at(4, 12, 0)),
    ("t10", 1, "F", "EURUSD", 0, "1.00", TradeStatus.FAILED, None, None, None),
    ("t11", 2, "F2", "GBPUSD", 0, "2.00", TradeStatus.UNKNOWN, None, None, None),
    ("t12", 1, "G", "EURUSD", 0, "1.00", TradeStatus.OPEN, None, None, None),
]

CHAINS: dict[str, tuple[int, str, Strategy, ChainStatus, AccountType]] = {
    "A": (1, "EURUSD", Strategy.MARTINGALE, ChainStatus.COMPLETED, AccountType.DEMO),
    "B": (1, "EURUSD", Strategy.MARTINGALE, ChainStatus.COMPLETED, AccountType.DEMO),
    "C": (1, "GBPUSD", Strategy.MARTINGALE, ChainStatus.EXHAUSTED, AccountType.DEMO),
    "D": (2, "GBPUSD", Strategy.FLIP_EVERY_LOSS, ChainStatus.COMPLETED, AccountType.DEMO),
    "E": (2, "EURUSD", Strategy.FLIP_EVERY_LOSS, ChainStatus.COMPLETED, AccountType.DEMO),
    "F": (1, "EURUSD", Strategy.MARTINGALE, ChainStatus.FAILED, AccountType.DEMO),
    "F2": (2, "GBPUSD", Strategy.FLIP_EVERY_LOSS, ChainStatus.UNKNOWN, AccountType.DEMO),
    "G": (1, "EURUSD", Strategy.MARTINGALE, ChainStatus.OPEN, AccountType.DEMO),
    "H": (1, "EURUSD", Strategy.MARTINGALE, ChainStatus.COMPLETED, AccountType.REAL),
}


async def seed_hand_made_history(
    factory: async_sessionmaker[AsyncSession], titles: tuple[str, str] = ("Alpha", "Beta")
) -> None:
    async with factory.begin() as session:
        groups = GroupRepository(session)
        await groups.add(make_group(telegram_chat_id=-1001, title=titles[0]))
        await groups.add(make_group(telegram_chat_id=-1002, title=titles[1]))
        chain_ids = {name: new_id() for name in CHAINS}
        first_trade_at: dict[str, datetime] = {}
        for _, _, chain, *_rest, settled in TRADES:
            if settled is not None and chain not in first_trade_at:
                first_trade_at[chain] = settled
        for name, (group, asset, strategy, status, account) in CHAINS.items():
            created = first_trade_at.get(name, at(4, 13))
            await ChainRepository(session).upsert(
                make_chain(
                    group,
                    id=chain_ids[name],
                    asset=asset,
                    strategy=strategy,
                    status=status,
                    account_type=account,
                    created_at=created,
                    updated_at=created,
                )
            )
        trades = TradeRepository(session)
        for name, group, chain, asset, step, stake, status, profit, payout, settled in TRADES:
            await trades.upsert(
                _trade(
                    chain_ids[chain],
                    group,
                    asset,
                    step,
                    stake,
                    status,
                    profit,
                    payout,
                    settled,
                    name,
                )
            )
        await trades.upsert(
            _trade(
                chain_ids["H"],
                1,
                "EURUSD",
                0,
                "1.00",
                W,
                "0.80",
                80,
                at(2, 11, 0),
                "t13",
                AccountType.REAL,
            )
        )


def _trade(
    chain_id: object,
    group: int,
    asset: str,
    step: int,
    stake: str,
    status: TradeStatus,
    profit: str | None,
    payout: int | None,
    settled: datetime | None,
    name: str,
    account: AccountType = AccountType.DEMO,
) -> TradeRecord:
    created = settled if settled is not None else at(4, 13)
    return make_trade(
        chain_id,  # type: ignore[arg-type]
        group,
        asset=asset,
        step=step,
        direction=Direction.CALL,
        stake=D(stake),
        status=status,
        profit=None if profit is None else D(profit),
        payout_pct=payout,
        settled_at=settled,
        created_at=created,
        account_type=account,
        broker_order_id=name,
    )


# --- a large random history, for the differential and performance tests ------------------------

from random import Random  # noqa: E402

from sqlalchemy import insert  # noqa: E402

from app.db.models import Chain as ChainRow  # noqa: E402
from app.db.models import Trade as TradeRow  # noqa: E402
from app.db.repositories._mapping import to_values  # noqa: E402
from app.domain.records import ChainRecord  # noqa: E402

ASSETS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY_otc", "NZDUSD")
STRATEGIES = (Strategy.MARTINGALE, Strategy.FLIP_EVERY_LOSS, Strategy.NO_MARTINGALE)
START = at(1, 0)  # November 2026; the history runs for `days` days from here


def random_history(
    rng: Random, chains: int, *, groups: int = 4, days: int = 30
) -> tuple[list[ChainRecord], list[TradeRecord]]:
    """`chains` random chains and their trades. Settle times are unique, so "the order trades
    settled" is never ambiguous. Statuses, accounts, payouts and results are all mixed."""
    chain_records: list[ChainRecord] = []
    trade_records: list[TradeRecord] = []
    tick = 0  # microseconds, to keep every settle time distinct
    span = days * 24 * 3600
    for _ in range(chains):
        group = rng.randint(1, groups)
        strategy = STRATEGIES[group % len(STRATEGIES)]
        account = AccountType.REAL if rng.random() < 0.15 else AccountType.DEMO
        asset = rng.choice(ASSETS)
        payout = rng.choice((78, 80, 85, 90))
        base = D(rng.choice(("1.00", "2.00", "5.00")))
        created = START + timedelta(seconds=rng.randrange(span))
        chain_id = new_id()
        step = 0
        end_state = ChainStatus.COMPLETED
        while True:
            stake = base * (2**step)
            tick += 1
            settled = created + timedelta(seconds=70 * (step + 1), microseconds=tick)
            roll = rng.random()
            if roll < 0.01:
                result, profit, settled_at = TradeStatus.FAILED, None, None
                end_state = ChainStatus.FAILED
            elif roll < 0.02:
                result, profit, settled_at = TradeStatus.UNKNOWN, None, None
                end_state = ChainStatus.UNKNOWN
            elif roll < 0.03:
                result, profit, settled_at = TradeStatus.OPEN, None, None
                end_state = ChainStatus.OPEN
            else:
                settled_at = settled
                outcome = rng.random()
                if outcome < 0.02:
                    result, profit = TradeStatus.DRAW, D("0.00")
                elif outcome < 0.50:
                    result = TradeStatus.WON
                    profit = (stake * payout / 100).quantize(D("0.01"))
                else:
                    result, profit = TradeStatus.LOST, -stake
            trade_records.append(
                make_trade(
                    chain_id,
                    group,
                    asset=asset,
                    step=step,
                    stake=stake,
                    status=result,
                    profit=profit,
                    payout_pct=payout if profit is not None else None,
                    settled_at=settled_at,
                    created_at=settled,
                    account_type=account,
                )
            )
            if result is not TradeStatus.LOST:
                if result in (TradeStatus.WON, TradeStatus.DRAW):
                    end_state = ChainStatus.COMPLETED
                break
            step += 1
            if step > 3 or rng.random() < 0.1:
                end_state = ChainStatus.EXHAUSTED if step > 3 else ChainStatus.STOPPED
                break
        chain_records.append(
            make_chain(
                group,
                id=chain_id,
                asset=asset,
                strategy=strategy,
                status=end_state,
                account_type=account,
                created_at=created,
                updated_at=created,
            )
        )
    return chain_records, trade_records


async def insert_history(
    factory: async_sessionmaker[AsyncSession],
    groups: int,
    chains: list[ChainRecord],
    trades: list[TradeRecord],
) -> None:
    """Bulk-insert (fast: one statement per table) instead of one upsert per record."""
    async with factory.begin() as session:
        repo = GroupRepository(session)
        for number in range(1, groups + 1):
            await repo.add(make_group(telegram_chat_id=-2000 - number, title=f"Group {number}"))
        await session.execute(insert(ChainRow), [to_values(c) for c in chains])
        for start in range(0, len(trades), 20_000):
            await session.execute(
                insert(TradeRow), [to_values(t) for t in trades[start : start + 20_000]]
            )
