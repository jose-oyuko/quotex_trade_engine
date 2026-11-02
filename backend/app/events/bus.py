"""In-memory publish/subscribe.

`publish` is synchronous and never waits: it appends the event to each interested subscriber's
bounded queue and returns. That is what keeps the execution path free of database and dashboard
work (docs/ARCHITECTURE.md section 4). A slow subscriber can only lose its *own* events.

Overflow policy (per subscription, chosen by the subscriber):
- `DROP_OLDEST`: keep the newest events (live views that can re-sync from a snapshot).
- `DROP_NEWEST`: keep what is already queued (the DB writer: preserves ordering, so a trade is never
  stored without the chain row before it). Either way the drop is counted and visible.
"""

from __future__ import annotations

import asyncio
from collections import deque
from enum import StrEnum

import structlog

from app.events.types import Event

log = structlog.get_logger()


class OverflowPolicy(StrEnum):
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


class SubscriptionClosedError(Exception):
    """Raised by `Subscription.get` once the subscription is closed and fully drained."""


class Subscription:
    """A bounded, single-consumer queue of events."""

    def __init__(
        self,
        event_types: tuple[type[Event], ...] | None,
        *,
        maxsize: int,
        policy: OverflowPolicy,
        name: str,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.name = name
        self.maxsize = maxsize
        self.policy = policy
        self.dropped = 0
        self._event_types = event_types
        self._items: deque[Event] = deque()
        self._wakeup = asyncio.Event()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def depth(self) -> int:
        return len(self._items)

    def wants(self, event: Event) -> bool:
        return self._event_types is None or isinstance(event, self._event_types)

    def offer(self, event: Event) -> bool:
        """Queue an event without waiting. Returns False if the event was not queued."""
        if self._closed:
            return False
        if len(self._items) >= self.maxsize:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                log.error("event_queue_overflow", subscriber=self.name, dropped=self.dropped)
            if self.policy is OverflowPolicy.DROP_NEWEST:
                return False
            self._items.popleft()
        self._items.append(event)
        self._wakeup.set()
        return True

    def get_nowait(self) -> Event | None:
        return self._items.popleft() if self._items else None

    async def get(self) -> Event:
        """Wait for the next event. Raises `SubscriptionClosedError` when closed and empty."""
        while not self._items:
            if self._closed:
                raise SubscriptionClosedError
            self._wakeup.clear()
            await self._wakeup.wait()
        return self._items.popleft()

    def close(self) -> None:
        """Stop accepting events. Already queued events can still be read."""
        self._closed = True
        self._wakeup.set()


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self.published = 0

    def subscribe(
        self,
        *event_types: type[Event],
        maxsize: int = 10_000,
        policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
        name: str = "subscriber",
    ) -> Subscription:
        """Subscribe to the given event types (all events if none are given)."""
        subscription = Subscription(event_types or None, maxsize=maxsize, policy=policy, name=name)
        self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscription.close()
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def publish(self, event: Event) -> None:
        """Hand the event to every interested subscriber. Never blocks, never raises for a full
        queue."""
        self.published += 1
        for subscription in self._subscriptions:
            if subscription.wants(event):
                subscription.offer(event)
