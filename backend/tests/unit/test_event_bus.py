import asyncio

import pytest

from app.events.bus import EventBus, OverflowPolicy, SubscriptionClosedError
from app.events.types import ConnectionChanged, Event, RiskTripped
from tests.factories import NOW, make_risk_event


def connection_event(n: int = 0) -> ConnectionChanged:
    return ConnectionChanged(occurred_at=NOW, component="quotex", connected=True, detail=str(n))


def risk_event() -> RiskTripped:
    return RiskTripped(occurred_at=NOW, risk_event=make_risk_event())


async def test_event_reaches_every_interested_subscriber() -> None:
    bus = EventBus()
    first, second = bus.subscribe(name="a"), bus.subscribe(name="b")
    event = connection_event()
    bus.publish(event)
    assert await first.get() is event
    assert await second.get() is event


async def test_subscribers_only_get_the_types_they_asked_for() -> None:
    bus = EventBus()
    only_risk = bus.subscribe(RiskTripped)
    bus.publish(connection_event())
    bus.publish(risk_event())
    got = await only_risk.get()
    assert isinstance(got, RiskTripped)
    assert only_risk.get_nowait() is None


async def test_events_arrive_in_publish_order() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    for n in range(5):
        bus.publish(connection_event(n))
    details = [(await sub.get()).detail for _ in range(5)]  # type: ignore[attr-defined]
    assert details == ["0", "1", "2", "3", "4"]


async def test_get_waits_until_an_event_is_published() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    waiter = asyncio.create_task(sub.get())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    bus.publish(connection_event())
    assert (await asyncio.wait_for(waiter, 1)).name == "connection.changed"


async def test_publish_does_not_wait_for_a_full_subscriber() -> None:
    bus = EventBus()
    bus.subscribe(maxsize=1, policy=OverflowPolicy.DROP_NEWEST)
    for n in range(100):
        bus.publish(connection_event(n))  # sync call: if it blocked, this test would hang
    assert bus.published == 100


async def test_drop_newest_keeps_the_oldest_events() -> None:
    bus = EventBus()
    sub = bus.subscribe(maxsize=3, policy=OverflowPolicy.DROP_NEWEST)
    for n in range(10):
        bus.publish(connection_event(n))
    assert sub.dropped == 7
    kept: list[Event] = []
    while (event := sub.get_nowait()) is not None:
        kept.append(event)
    assert [e.detail for e in kept] == ["0", "1", "2"]  # type: ignore[attr-defined]


async def test_drop_oldest_keeps_the_newest_events() -> None:
    bus = EventBus()
    sub = bus.subscribe(maxsize=3, policy=OverflowPolicy.DROP_OLDEST)
    for n in range(10):
        bus.publish(connection_event(n))
    assert sub.dropped == 7
    kept: list[Event] = []
    while (event := sub.get_nowait()) is not None:
        kept.append(event)
    assert [e.detail for e in kept] == ["7", "8", "9"]  # type: ignore[attr-defined]


async def test_one_full_subscriber_does_not_affect_another() -> None:
    bus = EventBus()
    slow = bus.subscribe(maxsize=1, policy=OverflowPolicy.DROP_NEWEST)
    healthy = bus.subscribe(maxsize=100)
    for n in range(50):
        bus.publish(connection_event(n))
    assert slow.dropped == 49
    assert healthy.dropped == 0
    assert healthy.depth == 50


async def test_closed_subscription_drains_then_raises() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish(connection_event())
    bus.unsubscribe(sub)
    bus.publish(connection_event())  # after unsubscribe: not queued
    await sub.get()  # the event queued before closing is still delivered
    with pytest.raises(SubscriptionClosedError):
        await sub.get()


async def test_close_wakes_a_waiting_consumer() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    waiter = asyncio.create_task(sub.get())
    await asyncio.sleep(0.01)
    bus.unsubscribe(sub)
    with pytest.raises(SubscriptionClosedError):
        await asyncio.wait_for(waiter, 1)


def test_zero_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="maxsize"):
        EventBus().subscribe(maxsize=0)
