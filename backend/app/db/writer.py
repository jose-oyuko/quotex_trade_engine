"""DBWriter: turns events into database rows in the background (decision D-4).

It is a normal bus subscriber with its own bounded queue, so the code that publishes events never
waits for the database. Batching needs no timer: while one transaction commits, new events pile up
in the queue and become the next batch, so a quiet system writes each event at once and a busy one
commits in large batches.

Overflow policy: if the queue is full (the database stalled for a long time) new events are
dropped, counted in `stats.dropped`, and logged as errors. Dropping the *newest* keeps the stored
history in order (a trade is never stored without the chain row before it) and never blocks a
trade. The default capacity (100,000 events) is many minutes of heavy trading.

Failure policy:
- A **transient** failure (the database is locked, unavailable, the disk is full, the connection
  dropped: `OperationalError` / `InterfaceError`) is retried with backoff for up to `max_outage_s`
  (ten minutes by default) while the queue keeps filling; nothing is lost unless the outage outlasts
  that or the queue overflows (both counted and logged loudly). `retrying` tells the health check.
- Any other failure (a record the database refuses) rolls the batch back and retries its events one
  by one so a single bad record cannot take the others with it; the bad one is logged and counted
  in `stats.failed`.

Shutdown: `stop()` stops accepting events, writes everything still queued, then returns. If the
database is down at that moment it gives up after a few attempts instead of holding the process.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.backoff import BackoffPolicy, backoff_delay
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
DEFAULT_MAX_OUTAGE_S = 600.0  # how long a down database is waited for before a batch is given up
SHUTDOWN_ATTEMPTS = 3  # attempts at the very end, when waiting would only hold up the process
TRANSIENT_ERRORS = (OperationalError, InterfaceError)

type Sleeper = Callable[[float], Awaitable[None]]


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
        backoff: BackoffPolicy | None = None,
        max_outage_s: float = DEFAULT_MAX_OUTAGE_S,
        sleep: Sleeper = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._session_factory = session_factory
        self._tasks = tasks
        self._queue_size = queue_size
        self._batch_size = batch_size
        self._subscription: Subscription | None = None
        self._backoff = backoff or BackoffPolicy(base_s=0.2, cap_s=5.0)
        self._max_outage_s = max_outage_s
        self._sleep = sleep
        self._rng = rng
        self._monotonic = monotonic
        self._stopping = False
        self.retrying = False  # True while waiting for a database that is down
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
        self._stopping = True
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
        error = await self._commit_with_retry(batch)
        if error is None:
            self.stats.written += len(batch)
            self.stats.batches += 1
        elif isinstance(error, TRANSIENT_ERRORS):
            self.stats.failed += len(batch)  # the outage outlasted the patience: counted, logged
        else:
            log.warning("db_batch_failed_retrying_individually", size=len(batch), exc_info=error)
            await self._write_individually(batch)

    async def _write_individually(self, batch: list[Event]) -> None:
        for event in batch:
            error = await self._commit_with_retry([event])
            if error is None:
                self.stats.written += 1
            else:
                self.stats.failed += 1
                log.error("db_event_failed", event_name=event.name, exc_info=error)

    async def _commit_with_retry(self, batch: list[Event]) -> Exception | None:
        """Commit the batch. A transient error is waited out (see the module docstring); returns
        None on success, or the error that was not transient / that outlasted the patience."""
        started = self._monotonic()
        attempt = 0
        while True:
            try:
                async with self._session_factory.begin() as session:
                    for event in batch:
                        await _apply(session, event)
            except TRANSIENT_ERRORS as exc:
                waited = self._monotonic() - started
                if waited >= self._max_outage_s or (
                    self._stopping and attempt >= SHUTDOWN_ATTEMPTS
                ):
                    self.retrying = False
                    log.error(
                        "db_outage_batch_dropped",
                        size=len(batch),
                        waited_s=round(waited, 1),
                        exc_info=exc,
                    )
                    return exc
                if attempt == 0:
                    log.warning("db_unavailable_retrying", size=len(batch), error=str(exc)[:200])
                self.retrying = True
                await self._sleep(backoff_delay(attempt, self._backoff, self._rng))
                attempt += 1
            except Exception as exc:
                self.retrying = False
                return exc
            else:
                if attempt:
                    log.info("db_recovered", attempts=attempt)
                self.retrying = False
                return None


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
