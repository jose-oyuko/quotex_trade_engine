"""Creating, editing and deleting trading sessions, and telling the running engine about it.

A session is saved with a hidden group of its own (decision D-71): the group carries the strategy
settings, so chains, trades, reports and limits work as they do for a Telegram group. The database
is written first; only when that has been committed is the engine told.

A session that is running cannot be edited or deleted: stop it first, so a run never changes under
the owner's feet. A session with runs on record cannot be deleted either (its history would lose
its owner): disable it instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.errors import DomainError
from app.db.repositories import GroupRepository, SessionRepository
from app.domain.enums import AssetSuffixMode, GroupSource, RepeatKind, Strategy
from app.domain.records import (
    GroupRecord,
    GroupSettingsRecord,
    SessionRecord,
    SessionRunRecord,
)
from app.engine.engine import Engine
from app.sessions.schedule import (
    SEARCH_DAYS,
    TRADE_LENGTHS_S,
    Window,
    is_on_boundary,
    next_window,
    sessions_overlap,
    windows_between,
)
from app.signals.timezones import InvalidTimezoneError, parse_timezone

log = structlog.get_logger()

_ASSET = re.compile(r"^[A-Z0-9]{3,12}(_otc)?$")
SESSION_PARSER = "session"  # the hidden group has no parser: this only fills the column


class SessionError(DomainError):
    """Base class of the errors the session service raises."""


class InvalidSessionError(SessionError):
    """The values are well-formed but not acceptable (an unknown trade length, a bad zone...)."""


class SessionNotFoundError(SessionError):
    pass


class SessionOverlapError(SessionError):
    """Another enabled session's window overlaps this one's: only one runs at a time."""


class SessionInUseError(SessionError):
    """The session is running, or has runs on record, so it cannot be edited or deleted."""


@dataclass(slots=True, frozen=True)
class SessionValues:
    """What the owner chooses for a session."""

    name: str
    enabled: bool
    asset: str
    duration_s: int
    start_time: time
    end_time: time
    timezone: str
    repeat: RepeatKind
    weekdays: tuple[int, ...]
    pause_s: int
    profit_target: Decimal | None
    loss_limit: Decimal | None
    max_pairs: int | None
    # the strategy part
    strategy: Strategy
    base_stake: Decimal
    max_steps: int
    multipliers: tuple[Decimal, ...]
    min_payout_pct: int


@dataclass(slots=True, frozen=True)
class SessionView:
    session: SessionRecord
    settings: GroupSettingsRecord | None
    next_window: Window | None  # the next time it will start by itself (None: finished or off)
    warnings: tuple[str, ...] = ()


type EngineProvider = Callable[[], Engine | None]


class SessionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        engine: EngineProvider,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._engine = engine

    # --- reading ---

    async def list_all(self) -> list[SessionView]:
        async with self._factory() as session:
            groups = GroupRepository(session)
            settings = {s.group_id: s for s in await groups.list_settings()}
            records = await SessionRepository(session).list_all()
        return [self._view(r, settings.get(r.group_id)) for r in records]

    async def get(self, session_id: int) -> SessionView:
        async with self._factory() as session:
            record = await SessionRepository(session).get(session_id)
            if record is None:
                raise SessionNotFoundError(f"no session {session_id}")
            settings = await GroupRepository(session).get_settings(record.group_id)
        return self._view(record, settings)

    async def runs(
        self, *, session_id: int | None = None, limit: int = 50, offset: int = 0
    ) -> list[SessionRunRecord]:
        async with self._factory() as session:
            if session_id is not None and await SessionRepository(session).get(session_id) is None:
                raise SessionNotFoundError(f"no session {session_id}")
            return await SessionRepository(session).list_runs(
                session_id=session_id, limit=limit, offset=offset
            )

    async def count_runs(self, *, session_id: int | None = None) -> int:
        async with self._factory() as session:
            return await SessionRepository(session).count_runs(session_id=session_id)

    # --- writing ---

    async def create(self, values: SessionValues) -> SessionView:
        now = self._clock.now()
        async with self._factory.begin() as session:
            others = await SessionRepository(session).list_all()
            record = self._record(None, 0, values, now, once_after=now, created_at=now)
            self._check_no_overlap(record, others, now)
            groups = GroupRepository(session)
            group = await groups.add(
                GroupRecord(
                    telegram_chat_id=None,
                    title=f"Session: {values.name.strip()}"[:255],
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                    source=GroupSource.SESSION,
                )
            )
            if group.id is None:
                raise RuntimeError("the database did not assign a group id")
            settings = self._settings(group.id, values, now)
            await groups.save_settings(settings)
            stored = await SessionRepository(session).add(replace(record, group_id=group.id))
        self._tell_engine(group, stored, settings)
        return self._view(stored, settings)

    async def update(self, session_id: int, values: SessionValues) -> SessionView:
        now = self._clock.now()
        self._refuse_while_running(session_id)
        async with self._factory.begin() as session:
            repo = SessionRepository(session)
            existing = await repo.get(session_id)
            if existing is None:
                raise SessionNotFoundError(f"no session {session_id}")
            others = [o for o in await repo.list_all() if o.id != session_id]
            # saving a ONCE session arms it again: it runs at its next start time
            record = self._record(
                session_id,
                existing.group_id,
                values,
                now,
                once_after=now,
                created_at=existing.created_at,
            )
            self._check_no_overlap(record, others, now)
            groups = GroupRepository(session)
            group = await groups.get(existing.group_id)
            if group is None:
                raise RuntimeError("the session's hidden group is missing")
            group = replace(group, title=f"Session: {values.name.strip()}"[:255], updated_at=now)
            settings = self._settings(existing.group_id, values, now)
            await groups.update(group)
            await groups.save_settings(settings)
            await repo.update(record)
        self._tell_engine(group, record, settings)
        return self._view(record, settings)

    async def delete(self, session_id: int) -> None:
        self._refuse_while_running(session_id)
        try:
            async with self._factory.begin() as session:
                repo = SessionRepository(session)
                existing = await repo.get(session_id)
                if existing is None:
                    raise SessionNotFoundError(f"no session {session_id}")
                if await repo.has_runs(session_id):
                    raise SessionInUseError(
                        "the session has runs on record and cannot be deleted: disable it instead"
                    )
                await repo.delete(session_id)
                groups = GroupRepository(session)
                await groups.delete(existing.group_id)
        except IntegrityError as exc:
            raise SessionInUseError(
                "the session has trades or signals on record and cannot be deleted: "
                "disable it instead"
            ) from exc
        engine = self._engine()
        if engine is not None:
            engine.remove_session(session_id)

    # --- internals ---

    def _refuse_while_running(self, session_id: int) -> None:
        engine = self._engine()
        if engine is not None and engine.scheduler.active_run_of(session_id) is not None:
            raise SessionInUseError(
                "the session is running: stop it (and let its chains finish) first"
            )

    def _view(self, record: SessionRecord, settings: GroupSettingsRecord | None) -> SessionView:
        now = self._clock.now()
        upcoming = next_window(record, now) if record.enabled else None
        warnings: list[str] = []
        if not _starts_on_a_candle(record, now):
            warnings.append(
                f"The start time is not on a {record.duration_s // 60}-minute candle boundary: "
                "the first trades start mid-candle, and Quotex may give them a different expiry "
                "than the trade length."
            )
        if record.profit_target is None and record.loss_limit is None:
            warnings.append(
                "No profit target and no loss limit: the session only stops at the end of its "
                "window."
            )
        return SessionView(record, settings, upcoming, tuple(warnings))

    def _record(
        self,
        session_id: int | None,
        group_id: int,
        values: SessionValues,
        now: datetime,
        *,
        once_after: datetime,
        created_at: datetime,
    ) -> SessionRecord:
        if not _ASSET.match(values.asset):
            raise InvalidSessionError(
                f"{values.asset!r} is not a Quotex asset name: use letters and digits, "
                "like EURUSD or EURUSD_otc"
            )
        if values.duration_s not in TRADE_LENGTHS_S:
            allowed = ", ".join(f"{s // 60} min" for s in TRADE_LENGTHS_S)
            raise InvalidSessionError(f"the trade length must be one of: {allowed}")
        try:
            parse_timezone(values.timezone)
            return SessionRecord(
                id=session_id,
                name=values.name.strip(),
                enabled=values.enabled,
                group_id=group_id,
                asset=values.asset,
                duration_s=values.duration_s,
                start_time=values.start_time,
                end_time=values.end_time,
                timezone=values.timezone,
                repeat=values.repeat,
                weekdays=tuple(sorted(set(values.weekdays))),
                pause_s=values.pause_s,
                profit_target=values.profit_target,
                loss_limit=values.loss_limit,
                max_pairs=values.max_pairs,
                once_after=once_after,
                created_at=created_at,
                updated_at=now,
            )
        except (InvalidTimezoneError, ValueError) as exc:
            raise InvalidSessionError(str(exc)) from exc

    def _settings(self, group_id: int, values: SessionValues, now: datetime) -> GroupSettingsRecord:
        try:
            return GroupSettingsRecord(
                group_id=group_id,
                parser=SESSION_PARSER,
                asset_suffix_mode=AssetSuffixMode.NONE,
                timezone="UTC",
                strategy=values.strategy,
                base_stake=values.base_stake,
                max_steps=values.max_steps,
                multipliers=values.multipliers,
                min_payout_pct=values.min_payout_pct,
                updated_at=now,
            )
        except ValueError as exc:
            raise InvalidSessionError(str(exc)) from exc

    def _check_no_overlap(
        self, record: SessionRecord, others: list[SessionRecord], now: datetime
    ) -> None:
        """Only one session runs at a time: the windows of the enabled sessions must not overlap
        (checked over the next two weeks, which covers every weekly pattern)."""
        if not record.enabled:
            return
        for other in others:
            if other.enabled and sessions_overlap(record, other, now):
                raise SessionOverlapError(
                    f"The window overlaps the one of the session {other.name!r}: only one session "
                    "runs at a time. Change a time or a day, or disable one of them."
                )

    def _tell_engine(
        self, group: GroupRecord, session: SessionRecord, settings: GroupSettingsRecord
    ) -> None:
        engine = self._engine()
        if engine is not None:
            engine.set_group(group, settings)
            engine.set_session(session, settings)


def _starts_on_a_candle(record: SessionRecord, now: datetime) -> bool:
    """True if the next few windows start on a candle boundary of the trade length (candles are
    counted from 00:00 UTC)."""
    windows = list(windows_between(record, now, now + timedelta(days=SEARCH_DAYS)))[:3]
    return all(is_on_boundary(w.start, record.duration_s) for w in windows)
