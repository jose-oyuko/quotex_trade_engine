"""DBWriter: turns events into database rows in the background (decision D-4).

It is a normal bus subscriber with its own bounded queue, so the code that publishes events never
waits for the database. Batching needs no timer: while one transaction commits, new events pile up
in the queue and become the next batch, so a quiet system writes each event at once and a busy one
commits in large batches.

Overflow policy: if the queue is full (the database stalled for a long time) new events are
dropped, counted in `stats.dropped`, and logged as errors. Dropping the *newest* keeps the stored
history in order (a trade is never stored without the chain row before it) and never blocks a
trade. The default capacity (100,000 events) is many minutes of heavy trading.

Failure policy: if a batch fails, it is rolled back and its events are retried one by one so a
single bad record cannot take the others with it; the bad one is logged and counted in
`stats.failed`.

Shutdown: `stop()` stops accepting events, writes everything still queued, then returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tasks import TaskSupervisor
from app.db.repositories import (
    AppSettingsRepository,
    BalanceSnapshotRepository,
    ChainRepository,
    RiskEventRepository,
    SignalRepository,
    TradeRepository,
)
from app.events.bus import EventBus, OverflowPolicy, Subscription, SubscriptionClosedError
from app.events.types import (
    PERSISTED_EVENTS,
    BalanceUpdated,
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    Event,
    RiskTripped,
    SettingChanged,
    SignalReceived,
    TradeOpened,
    TradeSettled,
)

log = structlog.get_logger()

DEFAULT_QUEUE_SIZE = 100_000
DEFAULT_BATCH_SIZE = 500


@dataclass(slots=True)
class WriterStats:
    written: int = 0
    failed: int = 0
    batches: int = 0


class DBWriter:
    def __init__(
        self,
        bus: EventBus,
        session_factory: async_sessionmaker[AsyncSession],
        tasks: TaskSupervisor,
        *,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._bus = bus
        self._session_factory = session_factory
        self._tasks = tasks
        self._queue_size = queue_size
        self._batch_size = batch_size
        self._subscription: Subscription | None = None
        self.stats = WriterStats()

    @property
    def queue_depth(self) -> int:
        return self._subscription.depth if self._subscription else 0

    @property
    def dropped(self) -> int:
        return self._subscription.dropped if self._subscription else 0

    def start(self) -> None:
        if self._subscription is not None:
            raise RuntimeError("DBWriter already started")
        self._subscription = self._bus.subscribe(
            *PERSISTED_EVENTS,
            maxsize=self._queue_size,
            policy=OverflowPolicy.DROP_NEWEST,
            name="db_writer",
        )
        self._task = self._tasks.spawn(self._run(self._subscription), name="db_writer")

    async def stop(self) -> None:
        """Stop accepting events and write everything already queued."""
        if self._subscription is None:
            return
        self._bus.unsubscribe(self._subscription)
        await self._task

    async def _run(self, subscription: Subscription) -> None:
        while True:
            try:
                batch = [await subscription.get()]
            except SubscriptionClosedError:
                return
            while len(batch) < self._batch_size:
                event = subscription.get_nowait()
                if event is None:
                    break
                batch.append(event)
            try:
                await self._write(batch)
            except Exception:
                # Last line of defence: whatever went wrong, the writer keeps running.
                self.stats.failed += len(batch)
                log.error("db_writer_unexpected_error", size=len(batch), exc_info=True)

    async def _write(self, batch: list[Event]) -> None:
        try:
            async with self._session_factory.begin() as session:
                for event in batch:
                    await _apply(session, event)
        except Exception:
            log.warning("db_batch_failed_retrying_individually", size=len(batch), exc_info=True)
            await self._write_individually(batch)
        else:
            self.stats.written += len(batch)
            self.stats.batches += 1

    async def _write_individually(self, batch: list[Event]) -> None:
        for event in batch:
            try:
                async with self._session_factory.begin() as session:
                    await _apply(session, event)
            except Exception:
                self.stats.failed += 1
                log.error("db_event_failed", event_name=event.name, exc_info=True)
            else:
                self.stats.written += 1


async def _apply(session: AsyncSession, event: Event) -> None:
    match event:
        case SignalReceived(signal=signal):
            await SignalRepository(session).upsert(signal)
        case ChainStarted(chain=chain) | ChainAdvanced(chain=chain) | ChainEnded(chain=chain):
            await ChainRepository(session).upsert(chain)
        case TradeOpened(trade=trade) | TradeSettled(trade=trade):
            await TradeRepository(session).upsert(trade)
        case RiskTripped(risk_event=risk_event):
            await RiskEventRepository(session).add(risk_event)
        case BalanceUpdated(snapshot=snapshot):
            await BalanceSnapshotRepository(session).add(snapshot)
        case SettingChanged(setting=setting):
            await AppSettingsRepository(session).set(
                setting.key, setting.value, now=setting.updated_at
            )
        case _:
            raise TypeError(f"DBWriter cannot persist {type(event).__name__}")
