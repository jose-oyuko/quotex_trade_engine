from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Trade
from app.db.repositories._mapping import page, to_record, to_values
from app.domain.enums import UNSETTLED_TRADE_STATUSES, AccountType, TradeStatus
from app.domain.records import TradeRecord


class TradeRepository:
    """Trades are never deleted: they are the financial record."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, trade: TradeRecord) -> None:
        await self._session.merge(Trade(**to_values(trade)))
        await self._session.flush()

    async def get(self, trade_id: UUID) -> TradeRecord | None:
        row = await self._session.get(Trade, trade_id)
        return to_record(TradeRecord, row) if row else None

    async def list_for_chain(self, chain_id: UUID) -> list[TradeRecord]:
        stmt = select(Trade).where(Trade.chain_id == chain_id).order_by(Trade.step)
        return [to_record(TradeRecord, row) for row in await self._session.scalars(stmt)]

    async def list_unsettled(self) -> list[TradeRecord]:
        """Trades whose result is not known yet (pending or open); checked after a restart."""
        stmt = (
            select(Trade)
            .where(Trade.status.in_(UNSETTLED_TRADE_STATUSES))
            .order_by(Trade.created_at)
        )
        return [to_record(TradeRecord, row) for row in await self._session.scalars(stmt)]

    async def list(
        self,
        *,
        group_id: int | None = None,
        account_type: AccountType | None = None,
        status: TradeStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeRecord]:
        """Newest first."""
        limit, offset = page(limit, offset)
        stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id)
        if group_id is not None:
            stmt = stmt.where(Trade.group_id == group_id)
        if account_type is not None:
            stmt = stmt.where(Trade.account_type == account_type)
        if status is not None:
            stmt = stmt.where(Trade.status == status)
        rows = await self._session.scalars(stmt.limit(limit).offset(offset))
        return [to_record(TradeRecord, row) for row in rows]
