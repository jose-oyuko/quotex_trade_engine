"""Chains: history, detail, and the per-chain commands."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RunningEngineDep, SessionDep
from app.api.errors import ApiError
from app.api.schemas.common import DEFAULT_PAGE_SIZE, LimitParam, OffsetParam, Page
from app.api.schemas.records import ChainDetailOut, ChainOut, chain_out, signal_out, trade_out
from app.db.repositories import ChainRepository, SignalRepository, TradeRepository
from app.domain.enums import AccountType, ChainStatus
from app.engine.errors import UnknownChainError

router = APIRouter(prefix="/chains", tags=["chains"])


class ChainControlOut(BaseModel):
    chain: ChainOut
    stop_requested: bool


@router.get("", response_model=Page[ChainOut])
async def list_chains(
    session: SessionDep,
    group_id: int | None = None,
    status: ChainStatus | None = None,
    account_type: AccountType | None = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[ChainOut]:
    """Newest first. The database trails the engine by a moment; the WebSocket snapshot is the
    live picture of what is running right now."""
    repo = ChainRepository(session)
    rows = await repo.list(
        group_id=group_id, status=status, account_type=account_type, limit=limit, offset=offset
    )
    return Page(
        items=[chain_out(c) for c in rows],
        total=await repo.count(group_id=group_id, status=status, account_type=account_type),
        limit=limit,
        offset=offset,
    )


@router.get("/{chain_id}", response_model=ChainDetailOut)
async def get_chain(chain_id: UUID, session: SessionDep) -> ChainDetailOut:
    chain = await ChainRepository(session).get(chain_id)
    if chain is None:
        raise ApiError(404, "chain_not_found", f"no chain {chain_id}")
    trades = await TradeRepository(session).list_for_chain(chain_id)
    signal = (
        await SignalRepository(session).get(chain.signal_id)
        if chain.signal_id is not None
        else None
    )
    return ChainDetailOut(
        chain=chain_out(chain),
        trades=[trade_out(t) for t in trades],
        signal=signal_out(signal) if signal else None,
    )


@router.post("/{chain_id}/stop-after-current", response_model=ChainControlOut)
async def stop_after_current(
    chain_id: UUID, engine: RunningEngineDep, session: SessionDep
) -> ChainControlOut:
    """Let the open trade settle, then end the chain without a further step. Repeating it is
    harmless."""
    try:
        chain = engine.manager.running_chain(chain_id)
    except UnknownChainError:
        raise await _not_running(session, chain_id) from None
    engine.manager.stop_after_current(chain_id)
    return ChainControlOut(chain=chain_out(chain.to_record()), stop_requested=chain.stop_requested)


@router.post("/{chain_id}/end", response_model=ChainControlOut)
async def end_chain(
    chain_id: UUID, engine: RunningEngineDep, session: SessionDep
) -> ChainControlOut:
    """End the chain at once, so the group is free for new signals (the dashboard's "skip to
    base"). An open trade still settles and is recorded, but nothing follows it."""
    try:
        chain = engine.manager.running_chain(chain_id)
    except UnknownChainError:
        raise await _not_running(session, chain_id) from None
    engine.manager.end_chain(chain_id)
    return ChainControlOut(chain=chain_out(chain.to_record()), stop_requested=chain.stop_requested)


async def _not_running(session: AsyncSession, chain_id: UUID) -> ApiError:
    """404 if there never was such a chain, 409 if it exists but is not running any more."""
    stored = await ChainRepository(session).get(chain_id)
    if stored is None:
        return ApiError(404, "chain_not_found", f"no chain {chain_id}")
    return ApiError(
        409, "chain_not_running", f"the chain is not running: it ended as {stored.status.value}"
    )
