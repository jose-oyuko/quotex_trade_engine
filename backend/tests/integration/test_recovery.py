from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.recovery import load_recovery_state
from app.db.repositories import ChainRepository, GroupRepository, TradeRepository
from app.domain.enums import ChainStatus, TradeStatus
from tests.factories import make_chain, make_group, make_settings, make_trade

Factory = async_sessionmaker[AsyncSession]


async def test_empty_database_gives_empty_state(session_factory: Factory) -> None:
    state = await load_recovery_state(session_factory)
    assert (state.groups, state.group_settings) == ([], [])
    assert (state.open_chains, state.unsettled_trades) == ([], [])


async def test_recovery_returns_groups_and_only_work_in_flight(session_factory: Factory) -> None:
    async with session_factory.begin() as session:
        group = await GroupRepository(session).add(make_group())
        assert group.id is not None
        await GroupRepository(session).save_settings(make_settings(group.id))

        open_chain = make_chain(group.id, status=ChainStatus.OPEN, asset="EURUSD")
        pending_chain = make_chain(group.id, status=ChainStatus.PENDING, asset="GBPUSD")
        done_chain = make_chain(group.id, status=ChainStatus.COMPLETED, asset="AUDUSD")
        for chain in (open_chain, pending_chain, done_chain):
            await ChainRepository(session).upsert(chain)

        in_flight = make_trade(open_chain.id, group.id, status=TradeStatus.OPEN)
        lost = make_trade(done_chain.id, group.id, status=TradeStatus.LOST)
        for trade in (in_flight, lost):
            await TradeRepository(session).upsert(trade)

    state = await load_recovery_state(session_factory)

    assert [g.id for g in state.groups] == [group.id]
    assert [s.group_id for s in state.group_settings] == [group.id]
    assert {c.id for c in state.open_chains} == {open_chain.id, pending_chain.id}
    assert [t.id for t in state.unsettled_trades] == [in_flight.id]
