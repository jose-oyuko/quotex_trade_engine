"""Trades and the signal inbox: read-only history."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.schemas.common import DEFAULT_PAGE_SIZE, LimitParam, OffsetParam, Page
from app.api.schemas.records import SignalOut, TradeOut, signal_out, trade_out
from app.db.repositories import SignalRepository, TradeRepository
from app.domain.enums import AccountType, SignalStatus, TradeStatus

trades_router = APIRouter(prefix="/trades", tags=["trades"])
signals_router = APIRouter(prefix="/signals", tags=["signals"])


@trades_router.get("", response_model=Page[TradeOut])
async def list_trades(
    session: SessionDep,
    group_id: int | None = None,
    account_type: AccountType | None = None,
    status: TradeStatus | None = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[TradeOut]:
    """Newest first."""
    repo = TradeRepository(session)
    rows = await repo.list(
        group_id=group_id, account_type=account_type, status=status, limit=limit, offset=offset
    )
    return Page(
        items=[trade_out(t) for t in rows],
        total=await repo.count(group_id=group_id, account_type=account_type, status=status),
        limit=limit,
        offset=offset,
    )


@trades_router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(trade_id: UUID, session: SessionDep) -> TradeOut:
    trade = await TradeRepository(session).get(trade_id)
    if trade is None:
        raise ApiError(404, "trade_not_found", f"no trade {trade_id}")
    return trade_out(trade)


@signals_router.get("", response_model=Page[SignalOut])
async def list_signals(
    session: SessionDep,
    group_id: int | None = None,
    status: SignalStatus | None = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[SignalOut]:
    """Every message the groups sent, newest first, with what became of it and why."""
    repo = SignalRepository(session)
    rows = await repo.list(group_id=group_id, status=status, limit=limit, offset=offset)
    return Page(
        items=[signal_out(s) for s in rows],
        total=await repo.count(group_id=group_id, status=status),
        limit=limit,
        offset=offset,
    )


@signals_router.get("/{signal_id}", response_model=SignalOut)
async def get_signal(signal_id: UUID, session: SessionDep) -> SignalOut:
    signal = await SignalRepository(session).get(signal_id)
    if signal is None:
        raise ApiError(404, "signal_not_found", f"no signal {signal_id}")
    return signal_out(signal)
