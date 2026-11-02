"""TelegramListener: keeps one Telegram connection alive and delivers messages of the subscribed
chats to the pipeline.

It never talks to the pipeline's internals: it is given a `MessageHandler` and a `TelegramSource`.
Subscriptions can change while it runs. If the connection is lost it reconnects with backoff
(1 s doubling to 30 s, like the Quotex adapter) and publishes `ConnectionChanged` events so the
dashboard can show the state. If the saved session is not logged in it stops and says so: retrying
cannot fix that, only `npm run telegram:login` can.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum

import structlog

from app.core.backoff import BackoffPolicy, backoff_delay
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.events.bus import EventBus
from app.events.types import ConnectionChanged
from app.telegram.source import MessageHandler, TelegramSource

log = structlog.get_logger()

COMPONENT = "telegram"

type Sleeper = Callable[[float], Awaitable[None]]


class ListenerState(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    NEEDS_LOGIN = "needs_login"


class TelegramListener:
    def __init__(
        self,
        source: TelegramSource,
        *,
        handler: MessageHandler,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
        backoff: BackoffPolicy | None = None,
        sleep: Sleeper = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._source = source
        self._bus = bus
        self._clock = clock
        self._tasks = tasks
        self._backoff = backoff or BackoffPolicy()
        self._sleep = sleep
        self._rng = rng
        self._chats: set[int] = set()
        self._state = ListenerState.STOPPED
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        source.set_handler(handler)

    @property
    def state(self) -> ListenerState:
        return self._state

    @property
    def subscribed(self) -> frozenset[int]:
        return frozenset(self._chats)

    # --- subscriptions (safe to change at any time) ---

    def subscribe(self, chat_id: int) -> None:
        self._chats.add(chat_id)
        self._apply_chats()

    def unsubscribe(self, chat_id: int) -> None:
        self._chats.discard(chat_id)
        self._apply_chats()

    def set_subscriptions(self, chat_ids: Iterable[int]) -> None:
        self._chats = set(chat_ids)
        self._apply_chats()

    def _apply_chats(self) -> None:
        self._source.set_chats(frozenset(self._chats))

    # --- lifecycle ---

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._apply_chats()
        self._state = ListenerState.CONNECTING
        self._task = self._tasks.spawn(self._run(), name="telegram-listener")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._source.disconnect()
        self._connected.clear()
        self._state = ListenerState.STOPPED

    async def wait_until_connected(self, timeout_s: float) -> bool:
        try:
            async with asyncio.timeout(timeout_s):
                await self._connected.wait()
        except TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                self._state = ListenerState.CONNECTING
                await self._source.connect()
                if not await self._source.is_authorized():
                    self._state = ListenerState.NEEDS_LOGIN
                    self._announce(False, "not logged in: run `npm run telegram:login`")
                    await self._source.disconnect()
                    return
                attempt = 0
                self._state = ListenerState.CONNECTED
                self._connected.set()
                self._announce(True, f"listening to {len(self._chats)} chat(s)")
                await self._source.wait_disconnected()
                self._announce(False, "connection lost")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The supervising loop must survive anything the library throws; it is logged and
                # reported, then we try again.
                log.warning("telegram_connection_failed", error=f"{type(exc).__name__}: {exc}")
                self._announce(False, f"{type(exc).__name__}: {exc}")
            self._connected.clear()
            self._state = ListenerState.CONNECTING
            delay = backoff_delay(attempt, self._backoff, self._rng)
            attempt += 1
            await self._sleep(delay)

    def _announce(self, connected: bool, detail: str) -> None:
        self._bus.publish(
            ConnectionChanged(
                occurred_at=self._clock.now(),
                component=COMPONENT,
                connected=connected,
                detail=detail,
            )
        )
