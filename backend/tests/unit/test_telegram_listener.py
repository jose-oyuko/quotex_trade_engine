from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.backoff import BackoffPolicy
from app.core.tasks import TaskSupervisor
from app.domain.enums import AssetSuffixMode, SignalStatus
from app.events.bus import EventBus, Subscription
from app.events.types import ConnectionChanged, SignalReceived
from app.signals.models import RawMessage, Signal
from app.signals.parsers import LegacyV1Parser, ParserRegistry
from app.signals.pipeline import GroupRoute, SignalPipeline
from app.telegram import FakeTelegramSource, ListenerState, TelegramListener
from tests.signal_support import FirstWordParser, ManualClock, RecordingSleeper

CHAT_A, CHAT_B = -1001, -1002


@dataclass
class Rig:
    source: FakeTelegramSource
    listener: TelegramListener
    bus: EventBus
    connection: Subscription
    sleeper: RecordingSleeper
    tasks: TaskSupervisor
    received: list[RawMessage] = field(default_factory=list)

    def states(self) -> list[tuple[bool, str | None]]:
        found: list[tuple[bool, str | None]] = []
        while (event := self.connection.get_nowait()) is not None:
            assert isinstance(event, ConnectionChanged)
            assert event.component == "telegram"
            found.append((event.connected, event.detail))
        return found


def make_rig(*, authorized: bool = True) -> Rig:
    clock, bus, tasks, sleeper = ManualClock(), EventBus(), TaskSupervisor(), RecordingSleeper()
    source = FakeTelegramSource(clock, authorized=authorized)
    received: list[RawMessage] = []
    listener = TelegramListener(
        source,
        handler=received.append,
        bus=bus,
        clock=clock,
        tasks=tasks,
        backoff=BackoffPolicy(base_s=1.0, cap_s=30.0, jitter=0.1),
        sleep=sleeper,
        rng=lambda: 0.5,  # exactly no jitter
    )
    return Rig(source, listener, bus, bus.subscribe(ConnectionChanged), sleeper, tasks, received)


async def until(condition: Callable[[], bool], tries: int = 500) -> None:
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


async def test_it_connects_announces_it_and_delivers_subscribed_chats() -> None:
    rig = make_rig()
    rig.listener.subscribe(CHAT_A)
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    assert rig.listener.state is ListenerState.CONNECTED
    assert rig.states() == [(True, "listening to 1 chat(s)")]

    assert rig.source.emit(CHAT_A, "hello", message_id=1) is True
    assert rig.source.emit(CHAT_B, "not subscribed", message_id=2) is False
    assert [m.text for m in rig.received] == ["hello"]
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_subscriptions_change_at_runtime_without_reconnecting() -> None:
    rig = make_rig()
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    assert rig.source.emit(CHAT_A, "x") is False

    rig.listener.subscribe(CHAT_A)
    rig.listener.subscribe(CHAT_B)
    assert rig.listener.subscribed == {CHAT_A, CHAT_B}
    assert rig.source.emit(CHAT_A, "a", message_id=1) and rig.source.emit(CHAT_B, "b", message_id=2)

    rig.listener.unsubscribe(CHAT_A)
    assert rig.source.emit(CHAT_A, "a again", message_id=3) is False
    assert [m.text for m in rig.received] == ["a", "b"]

    rig.listener.set_subscriptions([CHAT_A])
    assert rig.listener.subscribed == {CHAT_A} and rig.source.chats == {CHAT_A}
    assert rig.source.connect_calls == 1
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_a_lost_connection_is_restored_with_the_subscriptions() -> None:
    rig = make_rig()
    rig.listener.subscribe(CHAT_A)
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    rig.states()

    rig.source.lose_connection()
    await until(
        lambda: rig.source.connect_calls == 2 and rig.listener.state is ListenerState.CONNECTED
    )
    assert rig.states() == [(False, "connection lost"), (True, "listening to 1 chat(s)")]
    assert rig.sleeper.delays == [1.0]
    assert rig.source.emit(CHAT_A, "after reconnect") is True
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_failed_connection_attempts_back_off_and_then_succeed() -> None:
    rig = make_rig()
    rig.source.connect_failures = 3
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    assert rig.sleeper.delays == [1.0, 2.0, 4.0]
    states = rig.states()
    assert [connected for connected, _ in states] == [False, False, False, True]
    assert "cannot reach Telegram" in (states[0][1] or "")
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_the_backoff_starts_over_after_a_successful_connection() -> None:
    rig = make_rig()
    rig.source.connect_failures = 2
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    assert rig.sleeper.delays == [1.0, 2.0]

    rig.source.lose_connection()
    await until(lambda: rig.source.connect_calls == 4)
    assert rig.sleeper.delays == [1.0, 2.0, 1.0]
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_a_session_that_is_not_logged_in_stops_and_says_how_to_fix_it() -> None:
    rig = make_rig(authorized=False)
    rig.listener.start()
    await until(lambda: rig.listener.state is ListenerState.NEEDS_LOGIN)
    assert rig.states() == [(False, "not logged in: run `npm run telegram:login`")]
    assert rig.source.connect_calls == 1  # retrying cannot fix this
    assert rig.sleeper.delays == []
    assert await rig.listener.wait_until_connected(0.01) is False
    await rig.listener.stop()
    await rig.tasks.shutdown()


async def test_stop_disconnects_and_leaves_nothing_running() -> None:
    rig = make_rig()
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    await rig.listener.stop()
    assert rig.listener.state is ListenerState.STOPPED
    assert rig.source.disconnect_calls >= 1
    assert rig.tasks.running == 0
    assert rig.source.emit(CHAT_A, "late") is False


async def test_starting_twice_does_not_start_two_loops() -> None:
    rig = make_rig()
    rig.listener.start()
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    assert rig.source.connect_calls == 1
    await rig.listener.stop()
    await rig.tasks.shutdown()


# --- acceptance: two groups at once, each with its own parser ---


async def test_two_groups_are_listened_to_at_once_with_different_parsers() -> None:
    clock, bus, tasks = ManualClock(), EventBus(), TaskSupervisor()
    inbox = bus.subscribe(SignalReceived)
    signals: list[Signal] = []
    pipeline = SignalPipeline(
        bus=bus,
        clock=clock,
        parsers=ParserRegistry([LegacyV1Parser(), FirstWordParser()]),
        tasks=tasks,
        on_signal=signals.append,
    )
    for group_id, chat_id, parser, mode in (
        (1, CHAT_A, "legacy_v1", AssetSuffixMode.NONE),
        (2, CHAT_B, "first_word", AssetSuffixMode.OTC),
    ):
        pipeline.set_route(
            GroupRoute(
                group_id=group_id,
                chat_id=chat_id,
                title=f"group {group_id}",
                parser=parser,
                asset_suffix_mode=mode,
                timezone=UTC,
            )
        )
    source = FakeTelegramSource(clock)
    listener = TelegramListener(
        source, handler=pipeline.handle, bus=bus, clock=clock, tasks=tasks, sleep=RecordingSleeper()
    )
    listener.set_subscriptions([CHAT_A, CHAT_B])
    listener.start()
    assert await listener.wait_until_connected(1)

    source.emit(CHAT_A, "EURUSD PUT 1m", message_id=1)  # group 1's format
    source.emit(CHAT_A, "BUY EURUSD", message_id=2)  # group 2's format, in group 1: not a signal
    source.emit(CHAT_B, "BUY GBPUSD", message_id=1)  # group 2's format
    source.emit(CHAT_B, "EURUSD PUT 1m", message_id=2)  # group 1's format, in group 2: not a signal

    assert [(s.group_id, s.asset, s.direction.value) for s in signals] == [
        (1, "EURUSD", "put"),
        (2, "GBPUSD_otc", "call"),
    ]
    statuses = []
    while (event := inbox.get_nowait()) is not None:
        assert isinstance(event, SignalReceived)
        statuses.append((event.signal.group_id, event.signal.status))
    assert statuses == [
        (1, SignalStatus.PARSED),
        (1, SignalStatus.NOT_PARSED),
        (2, SignalStatus.PARSED),
        (2, SignalStatus.NOT_PARSED),
    ]
    await listener.stop()
    await tasks.shutdown()


async def test_the_time_a_message_was_received_is_taken_by_the_source_not_the_pipeline() -> None:
    rig = make_rig()
    rig.listener.subscribe(CHAT_A)
    rig.listener.start()
    assert await rig.listener.wait_until_connected(1)
    sent = datetime(2026, 11, 1, 9, 59, 58, tzinfo=UTC)
    rig.source.emit(CHAT_A, "hi", sent_at=sent)
    [message] = rig.received
    assert message.sent_at == sent
    assert message.received_at - sent == timedelta(seconds=2)
    await rig.listener.stop()
    await rig.tasks.shutdown()
