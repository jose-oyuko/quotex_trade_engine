"""The WebSocket hub without sockets: sequence numbers, snapshots, heartbeats and slow clients."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.api.hub import ClientClosedError, Hub, HubClient
from app.api.schemas.ws import ServerMessage
from app.api.snapshot import SnapshotBuilder
from app.core.tasks import TaskSupervisor
from app.domain.enums import ChainStatus, TradeStatus
from app.domain.records import AppSettingRecord
from app.engine.risk import KEY_KILL_SWITCH
from app.events.bus import EventBus
from app.events.types import (
    ChainAdvanced,
    ChainStarted,
    ConnectionChanged,
    Event,
    SettingChanged,
    TradeSettled,
)
from tests.api_support import settings_for
from tests.factories import NOW, make_chain, make_trade
from tests.signal_support import ManualClock

SERVER_MESSAGE: TypeAdapter[Any] = TypeAdapter(ServerMessage)
D = Decimal


@dataclass
class HubRig:
    bus: EventBus
    hub: Hub
    tasks: TaskSupervisor

    def publish(self, *events: Event) -> None:
        for event in events:
            self.bus.publish(event)

    async def settle(self) -> None:
        """Let the hub task handle everything published so far."""
        for _ in range(20):
            await asyncio.sleep(0)

    async def next(self, client: HubClient, *, wait: float = 5.0) -> dict[str, Any]:
        text = await asyncio.wait_for(client.next_text(self.hub.heartbeat_s), wait)
        message: dict[str, Any] = SERVER_MESSAGE.validate_json(text).model_dump(mode="json")
        return message


@pytest.fixture
async def rig(tmp_path: Any) -> AsyncIterator[HubRig]:
    from app.services.live import LiveState

    bus, tasks, clock = EventBus(), TaskSupervisor(), ManualClock()
    live = LiveState()
    snapshots = SnapshotBuilder(
        settings=settings_for(tmp_path), version="test", live=live, engine=lambda: None
    )
    hub = Hub(
        bus=bus, live=live, snapshots=snapshots, clock=clock, tasks=tasks, client_queue=5,
        heartbeat_s=0.05,
    )  # fmt: skip
    hub.start()
    yield HubRig(bus, hub, tasks)
    await hub.stop()
    await tasks.shutdown()


CHAIN = make_chain(1)  # one chain whose step changes from event to event


def chain_event(n: int = 1, status: ChainStatus = ChainStatus.OPEN) -> ChainAdvanced:
    return ChainAdvanced(occurred_at=NOW, chain=replace(CHAIN, status=status, step=n))


async def test_a_new_client_gets_a_snapshot_first_with_what_is_open_right_now(rig: HubRig) -> None:
    chain = make_chain(1)
    rig.publish(
        ChainStarted(occurred_at=NOW, chain=chain),
        ConnectionChanged(occurred_at=NOW, component="quotex", connected=True, detail="up"),
    )
    await rig.settle()
    client = rig.hub.register()
    snapshot = await rig.next(client)
    assert snapshot["type"] == "snapshot" and snapshot["reason"] == "connect"
    assert snapshot["seq"] == 2
    assert [c["id"] for c in snapshot["data"]["open_chains"]] == [str(chain.id)]
    assert snapshot["data"]["connections"]["quotex"]["connected"] is True


async def test_events_after_the_snapshot_follow_with_consecutive_numbers(rig: HubRig) -> None:
    client = rig.hub.register()
    snapshot = await rig.next(client)
    assert snapshot["seq"] == 0
    rig.publish(chain_event(1), chain_event(2), chain_event(3))
    await rig.settle()
    got = [await rig.next(client) for _ in range(3)]
    assert [m["seq"] for m in got] == [1, 2, 3]
    assert {m["type"] for m in got} == {"chain.advanced"}
    assert [m["data"]["step"] for m in got] == [1, 2, 3]


async def test_a_client_joining_late_does_not_get_events_the_snapshot_already_shows(
    rig: HubRig,
) -> None:
    rig.publish(chain_event(1), chain_event(2), chain_event(3))
    await rig.settle()
    client = rig.hub.register()
    rig.publish(chain_event(4))  # published before the client reads its first frame
    await rig.settle()
    snapshot = await rig.next(client)
    assert snapshot["type"] == "snapshot"
    assert snapshot["seq"] == 4  # the snapshot is taken when it is sent: it already includes 4
    assert snapshot["data"]["open_chains"][0]["step"] == 4
    rig.publish(chain_event(5))
    await rig.settle()
    assert (await rig.next(client))["seq"] == 5  # and nothing is sent twice


async def test_every_client_sees_the_same_numbers(rig: HubRig) -> None:
    first, second = rig.hub.register(), rig.hub.register()
    await rig.next(first), await rig.next(second)
    rig.publish(chain_event(1), chain_event(2))
    await rig.settle()
    assert [(await rig.next(first))["seq"] for _ in range(2)] == [1, 2]
    assert [(await rig.next(second))["seq"] for _ in range(2)] == [1, 2]
    assert rig.hub.clients == 2
    rig.hub.unregister(second)
    assert rig.hub.clients == 1


async def test_an_event_nobody_needs_to_hear_does_not_use_up_a_number(rig: HubRig) -> None:
    client = rig.hub.register()
    await rig.next(client)
    stored_only = AppSettingRecord(key="ui.something", value=1, updated_at=NOW)
    rig.publish(
        chain_event(1),
        SettingChanged(occurred_at=NOW, setting=stored_only),
        chain_event(2),
    )
    await rig.settle()
    assert [(await rig.next(client))["seq"] for _ in range(2)] == [1, 2]  # no gap


async def test_a_change_of_controls_is_announced_with_the_new_controls(rig: HubRig) -> None:
    client = rig.hub.register()
    await rig.next(client)
    kill = AppSettingRecord(key=KEY_KILL_SWITCH, value=True, updated_at=NOW)
    rig.publish(SettingChanged(occurred_at=NOW, setting=kill))
    await rig.settle()
    message = await rig.next(client)
    assert message["type"] == "controls.changed" and message["data"]["kill_switch"] is True


async def test_trade_events_carry_the_record_and_its_latency(rig: HubRig) -> None:
    client = rig.hub.register()
    await rig.next(client)
    trade = make_trade(
        make_chain(1).id, 1, status=TradeStatus.WON, profit=D("0.85"),
        t_msg_received_ns=0, t_order_sent_ns=2_000_000,
    )  # fmt: skip
    rig.publish(TradeSettled(occurred_at=NOW, trade=trade))
    await rig.settle()
    message = await rig.next(client)
    assert message["type"] == "trade.settled"
    assert message["data"]["profit"] == "0.85" and message["data"]["stake"] == "1.00"
    assert message["data"]["latency"]["signal_to_order_ms"] == 2.0


async def test_a_client_that_falls_behind_gets_a_fresh_snapshot_instead_of_the_lost_events(
    rig: HubRig,
) -> None:
    slow, fast = rig.hub.register(), rig.hub.register()
    await rig.next(slow), await rig.next(fast)
    for n in range(1, 21):  # the queue holds 5; neither client reads while this happens
        rig.publish(chain_event(n))
    await rig.settle()
    assert slow.queued <= 5 and fast.queued <= 5  # bounded, whatever the producer does

    frame = await rig.next(slow)
    assert frame["type"] == "snapshot" and frame["reason"] == "slow_consumer"
    assert frame["seq"] == 20 and frame["data"]["open_chains"][0]["step"] == 20
    rig.publish(chain_event(21))
    await rig.settle()
    assert (await rig.next(slow))["seq"] == 21  # back in step: the next event, no gap
    assert rig.hub.stats.resyncs == 2  # both of them fell behind; neither slowed the hub


async def test_a_slow_client_costs_the_publisher_nothing(rig: HubRig) -> None:
    stuck = rig.hub.register()
    await rig.next(stuck)
    for n in range(5_000):
        rig.publish(chain_event(n % 10))
    await rig.settle()
    for _ in range(200):  # the hub task works through the queue
        if rig.hub.seq == 5_000:
            break
        await asyncio.sleep(0.005)
    assert rig.hub.seq == 5_000
    assert stuck.queued <= 5
    frame = await rig.next(stuck)
    assert frame["reason"] == "slow_consumer" and frame["seq"] == 5_000


async def test_a_client_can_ask_for_a_new_snapshot_and_queued_events_are_dropped(
    rig: HubRig,
) -> None:
    client = rig.hub.register()
    await rig.next(client)
    rig.publish(chain_event(1), chain_event(2))
    await rig.settle()
    client.request_snapshot("resync")
    frame = await rig.next(client)
    assert frame["type"] == "snapshot" and frame["reason"] == "resync" and frame["seq"] == 2
    rig.publish(chain_event(3))
    await rig.settle()
    assert (await rig.next(client))["seq"] == 3


async def test_a_quiet_connection_gets_heartbeats_that_carry_the_latest_number(
    rig: HubRig,
) -> None:
    client = rig.hub.register()
    await rig.next(client)
    beat = await rig.next(client)
    assert beat["type"] == "heartbeat" and beat["seq"] == 0
    rig.publish(chain_event(1))
    await rig.settle()
    assert (await rig.next(client))["seq"] == 1
    again = await rig.next(client)
    assert (
        again["type"] == "heartbeat" and again["seq"] == 1
    )  # a client at 0 would see it is behind


async def test_stopping_the_hub_lets_every_client_go(rig: HubRig) -> None:
    client = rig.hub.register()
    await rig.next(client)
    await rig.hub.stop()
    with pytest.raises(ClientClosedError):
        await client.next_text(1.0)


async def test_a_closed_client_stops_receiving(rig: HubRig) -> None:
    client = rig.hub.register()
    await rig.next(client)
    rig.hub.unregister(client)
    rig.publish(chain_event(1))
    await rig.settle()
    assert client.queued == 0
    with pytest.raises(ClientClosedError):
        await client.next_text(1.0)


async def test_one_bad_event_does_not_stop_the_feed(
    rig: HubRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.hub as hub_module

    real = hub_module.to_message
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(hub_module, "to_message", flaky)
    client = rig.hub.register()
    await rig.next(client)
    rig.publish(chain_event(1), chain_event(2))
    await rig.settle()
    message = await rig.next(client)
    assert message["seq"] == 1 and message["data"]["step"] == 2  # the first one was lost, not all


async def test_the_hub_keeps_the_live_state_even_with_nobody_connected(rig: HubRig) -> None:
    chain = make_chain(1)
    rig.publish(
        ChainStarted(occurred_at=NOW, chain=chain),
        ChainAdvanced(occurred_at=NOW, chain=replace(chain, status=ChainStatus.COMPLETED)),
    )
    await rig.settle()
    client = rig.hub.register()
    assert (await rig.next(client))["data"]["open_chains"] == []
