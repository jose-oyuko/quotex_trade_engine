from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Signal
from app.db.repositories._mapping import page, to_record, to_values
from app.domain.enums import SignalStatus
from app.domain.records import SignalRecord


class SignalRepository:
    """The signal inbox. Rows are never deleted: the inbox is the audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, signal: SignalRecord) -> None:
        await self._session.merge(Signal(**to_values(signal)))
        await self._session.flush()

    async def get(self, signal_id: UUID) -> SignalRecord | None:
        row = await self._session.get(Signal, signal_id)
        return to_record(SignalRecord, row) if row else None

    async def list(
        self,
        *,
        group_id: int | None = None,
        status: SignalStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SignalRecord]:
        """Newest first."""
        limit, offset = page(limit, offset)
        stmt = select(Signal).order_by(Signal.received_at.desc(), Signal.id)
        if group_id is not None:
            stmt = stmt.where(Signal.group_id == group_id)
        if status is not None:
            stmt = stmt.where(Signal.status == status)
        rows = await self._session.scalars(stmt.limit(limit).offset(offset))
        return [to_record(SignalRecord, row) for row in rows]
