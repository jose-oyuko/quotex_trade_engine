"""The WebSocket hub: one place that turns the event bus into numbered messages for the dashboards.

The hub is a normal bus subscriber with its own task, so the engine never waits for it. For every
event it (1) updates the `LiveState`, (2) turns the event into a message with the next sequence
number, and (3) drops that message into each connected client's own bounded queue. All three steps
are synchronous, so "the state as of event N" is a well-defined thing a snapshot can show, and a
client that gets a snapshot at N followed by N+1, N+2... has missed nothing.

A slow client can only hurt itself (docs/ARCHITECTURE.md section 4/7): when its queue is full it is
not blocked on and nothing else waits for it; its queue is thrown away and it is sent a fresh
snapshot instead of the events it could not take. That is also how a client recovers from a gap.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Literal

import structlog

from app.api.events import to_message
from app.api.schemas.ws import HeartbeatMessage, SnapshotMessage
from app.api.snapshot import SnapshotBuilder
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.events.bus import EventBus, OverflowPolicy, Subscription, SubscriptionClosedError
from app.events.types import Event
from app.services.live import LiveState

log = structlog.get_logger()

DEFAULT_CLIENT_QUEUE = 1000
DEFAULT_HEARTBEAT_S = 15.0
# The hub's own queue from the bus: it only does in-memory work, so it should never fill up.
HUB_QUEUE_SIZE = 50_000

type SnapshotReason = Literal["connect", "resync", "slow_consumer"]


class ClientClosedError(Exception):
    """The client was closed (it disconnected or the hub is stopping)."""


@dataclass(slots=True)
class HubStats:
    messages: int = 0
    resyncs: int = 0  # clients that fell behind or asked and got a new snapshot
    slow_disconnects: int = 0  # clients that could not even take a message and were dropped


class HubClient:
    """One connected dashboard: a bounded queue of already-encoded messages."""

    def __init__(self, hub: Hub, max_queue: int) -> None:
        self._hub = hub
        self._max = max_queue
        self._items: deque[str] = deque()
        self._wakeup = asyncio.Event()
        self._snapshot_reason: SnapshotReason | None = "connect"
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self._wakeup.set()

    @property
    def queued(self) -> int:
        return len(self._items)

    def request_snapshot(self, reason: SnapshotReason = "resync") -> None:
        """Replace whatever is queued with a fresh snapshot, sent next."""
        if self._snapshot_reason is None:
            self._hub.stats.resyncs += 1
        self._snapshot_reason = self._snapshot_reason or reason
        self._items.clear()
        self._wakeup.set()

    def offer(self, text: str) -> None:
        """Called by the hub for every message. Never waits."""
        if self.closed or self._snapshot_reason is not None:
            return  # a snapshot is coming that already includes this event
        if len(self._items) >= self._max:
            self.request_snapshot("slow_consumer")
            return
        self._items.append(text)
        self._wakeup.set()

    async def next_text(self, heartbeat_s: float) -> str:
        """The next frame to send: a snapshot if one is due, else the next event, else (after
        `heartbeat_s` of quiet) a heartbeat."""
        while True:
            if self.closed:
                raise ClientClosedError
            if (reason := self._snapshot_reason) is not None:
                self._snapshot_reason = None
                self._items.clear()
                return self._hub.snapshot_text(reason)
            if self._items:
                return self._items.popleft()
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), heartbeat_s)
            except TimeoutError:
                if not self._items and self._snapshot_reason is None:
                    return self._hub.heartbeat_text()


class Hub:
    def __init__(
        self,
        *,
        bus: EventBus,
        live: LiveState,
        snapshots: SnapshotBuilder,
        clock: Clock,
        tasks: TaskSupervisor,
        client_queue: int = DEFAULT_CLIENT_QUEUE,
        heartbeat_s: float = DEFAULT_HEARTBEAT_S,
    ) -> None:
        self._bus = bus
        self._live = live
        self._snapshots = snapshots
        self._clock = clock
        self._tasks = tasks
        self._client_queue = client_queue
        self.heartbeat_s = heartbeat_s
        self._clients: set[HubClient] = set()
        self._subscription: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._seq = 0
        self.stats = HubStats()

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def clients(self) -> int:
        return len(self._clients)

    def start(self) -> None:
        if self._subscription is not None:
            raise RuntimeError("Hub already started")
        self._subscription = self._bus.subscribe(
            maxsize=HUB_QUEUE_SIZE, policy=OverflowPolicy.DROP_OLDEST, name="ws_hub"
        )
        self._task = self._tasks.spawn(self._run(self._subscription), name="ws_hub")

    async def stop(self) -> None:
        """Stop reading events (everything already queued is still handled) and let clients go."""
        if self._subscription is None:
            return
        self._bus.unsubscribe(self._subscription)
        if self._task is not None:
            await self._task
        for client in list(self._clients):
            client.close()

    def register(self) -> HubClient:
        client = HubClient(self, self._client_queue)
        self._clients.add(client)
        return client

    def unregister(self, client: HubClient) -> None:
        client.close()
        self._clients.discard(client)

    # --- the encoded frames ---

    def snapshot_text(self, reason: SnapshotReason) -> str:
        """The whole picture as of now (it includes every event up to the current number)."""
        message = SnapshotMessage(
            seq=self._seq, at=self._clock.now(), reason=reason, data=self._snapshots.build()
        )
        return message.model_dump_json()

    def heartbeat_text(self) -> str:
        return HeartbeatMessage(seq=self._seq, at=self._clock.now()).model_dump_json()

    # --- the loop ---

    async def _run(self, subscription: Subscription) -> None:
        while True:
            try:
                event = await subscription.get()
            except SubscriptionClosedError:
                return
            try:
                self._process(event)
            except Exception:
                # One bad event must not stop the dashboard feed.
                log.error("ws_hub_event_failed", event_name=event.name, exc_info=True)

    def _process(self, event: Event) -> None:
        self._live.apply(event)
        message = to_message(event, self._seq + 1, self._snapshots)
        if message is None:
            return
        self._seq += 1
        self.stats.messages += 1
        text = message.model_dump_json()
        for client in tuple(self._clients):
            client.offer(text)
