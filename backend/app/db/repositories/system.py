"""Risk events, balance snapshots and app settings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, BalanceSnapshot, RiskEvent
from app.db.repositories._mapping import page, to_record, to_values
from app.domain.enums import AccountType
from app.domain.records import (
    AppSettingRecord,
    BalanceSnapshotRecord,
    JsonScalar,
    RiskEventRecord,
)


class RiskEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: RiskEventRecord) -> None:
        await self._session.merge(RiskEvent(**to_values(event)))
        await self._session.flush()

    async def list_recent(self, *, limit: int = 100, offset: int = 0) -> list[RiskEventRecord]:
        limit, offset = page(limit, offset)
        stmt = select(RiskEvent).order_by(RiskEvent.occurred_at.desc(), RiskEvent.id)
        rows = await self._session.scalars(stmt.limit(limit).offset(offset))
        return [to_record(RiskEventRecord, row) for row in rows]


class BalanceSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, snapshot: BalanceSnapshotRecord) -> None:
        await self._session.merge(BalanceSnapshot(**to_values(snapshot)))
        await self._session.flush()

    async def latest(self, account_type: AccountType) -> BalanceSnapshotRecord | None:
        stmt = (
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_type == account_type)
            .order_by(BalanceSnapshot.taken_at.desc())
            .limit(1)
        )
        row = await self._session.scalar(stmt)
        return to_record(BalanceSnapshotRecord, row) if row else None

    async def list_recent(
        self, account_type: AccountType, *, limit: int = 100, offset: int = 0
    ) -> list[BalanceSnapshotRecord]:
        limit, offset = page(limit, offset)
        stmt = (
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_type == account_type)
            .order_by(BalanceSnapshot.taken_at.desc())
        )
        rows = await self._session.scalars(stmt.limit(limit).offset(offset))
        return [to_record(BalanceSnapshotRecord, row) for row in rows]


class AppSettingsRepository:
    """Small key/value store for global settings (account type, kill switch, limits)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set(self, key: str, value: JsonScalar, *, now: datetime) -> None:
        await self._session.merge(AppSetting(key=key, value=value, updated_at=now))
        await self._session.flush()

    async def get(self, key: str) -> AppSettingRecord | None:
        row = await self._session.get(AppSetting, key)
        return to_record(AppSettingRecord, row) if row else None

    async def all(self) -> list[AppSettingRecord]:
        rows = await self._session.scalars(select(AppSetting).order_by(AppSetting.key))
        return [to_record(AppSettingRecord, row) for row in rows]

    async def delete(self, key: str) -> bool:
        result = await self._session.execute(delete(AppSetting).where(AppSetting.key == key))
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]
