from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chain
from app.db.repositories._mapping import page, to_record, to_values
from app.domain.enums import ACTIVE_CHAIN_STATUSES, AccountType, ChainStatus
from app.domain.records import ChainRecord


class ChainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chain: ChainRecord) -> None:
        await self._session.merge(Chain(**to_values(chain)))
        await self._session.flush()

    async def get(self, chain_id: UUID) -> ChainRecord | None:
        row = await self._session.get(Chain, chain_id)
        return to_record(ChainRecord, row) if row else None

    async def list_open(self) -> list[ChainRecord]:
        """Chains that still need the engine after a restart (pending or open)."""
        stmt = (
            select(Chain).where(Chain.status.in_(ACTIVE_CHAIN_STATUSES)).order_by(Chain.created_at)
        )
        return [to_record(ChainRecord, row) for row in await self._session.scalars(stmt)]

    async def list(
        self,
        *,
        group_id: int | None = None,
        status: ChainStatus | None = None,
        account_type: AccountType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChainRecord]:
        """Newest first."""
        limit, offset = page(limit, offset)
        stmt = _filtered(select(Chain), group_id, status, account_type)
        stmt = stmt.order_by(Chain.created_at.desc(), Chain.id).limit(limit).offset(offset)
        return [to_record(ChainRecord, row) for row in await self._session.scalars(stmt)]

    async def count(
        self,
        *,
        group_id: int | None = None,
        status: ChainStatus | None = None,
        account_type: AccountType | None = None,
    ) -> int:
        stmt = _filtered(select(func.count()).select_from(Chain), group_id, status, account_type)
        return await self._session.scalar(stmt) or 0


def _filtered[S: Select[Any]](
    stmt: S, group_id: int | None, status: ChainStatus | None, account_type: AccountType | None
) -> S:
    if group_id is not None:
        stmt = stmt.where(Chain.group_id == group_id)
    if status is not None:
        stmt = stmt.where(Chain.status == status)
    if account_type is not None:
        stmt = stmt.where(Chain.account_type == account_type)
    return stmt
