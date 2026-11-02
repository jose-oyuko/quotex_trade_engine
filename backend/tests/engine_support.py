"""A complete engine on fakes, for the Phase 4 tests: fake Telegram in, fake Quotex out, the real
pipeline, chain manager, executor and event bus in between."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.core.clock import Clock, SystemClock
from app.core.tasks import TaskSupervisor
from app.db.writer import DBWriter
from app.domain.enums import AssetSuffixMode, ChainStatus, Direction, Strategy, TradeStatus
from app.domain.ids import new_id
from app.domain.records import (
    ChainRecord,
    GroupRecord,
    GroupSettingsRecord,
    SignalRecord,
    TradeRecord,
)
from app.engine.engine import Engine
from app.events.bus import EventBus, Subscription
from app.events.types import (
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    Event,
    RiskTripped,
    SignalReceived,
    TradeOpened,
    TradeSettled,
)
from app.quotex.fake import FakeQuotexAdapter, PlacedOrder
from app.signals.models import Signal
from app.telegram import FakeTelegramSource
from tests.factories import make_group, make_settings
from tests.signal_support import ManualClock

D = Decimal


@dataclass
class GroupSpec:
    group_id: int
    chat_id: int
    strategy: Strategy
    base: str = "1.00"
    multipliers: tuple[str, ...] = ()


@dataclass
class EngineRig:
    clock: Clock
    bus: EventBus
    tasks: TaskSupervisor
    adapter: FakeQuotexAdapter
    source: FakeTelegramSource
    engine: Engine
    feed: Subscription
    events: list[Event] = field(default_factory=list)
    _message_id: int = 0

    # --- setup ---

    def add_group(self, spec: GroupSpec) -> None:
        group: GroupRecord = replace(
            make_group(telegram_chat_id=spec.chat_id, title=f"group {spec.group_id}"),
            id=spec.group_id,
        )
        settings: GroupSettingsRecord = make_settings(
            spec.group_id,
            strategy=spec.strategy,
            base_stake=D(spec.base),
            max_steps=len(spec.multipliers),
            multipliers=tuple(D(m) for m in spec.multipliers),
            asset_suffix_mode=AssetSuffixMode.NONE,
            timezone="UTC",
        )
        self.engine.set_group(group, settings)

    async def start(self) -> None:
        await self.adapter.connect()
        self.engine.listener.start()
        assert await self.engine.listener.wait_until_connected(2)

    async def stop(self, writer: DBWriter | None = None) -> None:
        """Shut down in the application's order: engine, then the DB writer (so it drains what
        the engine just published), then everything else."""
        await self.engine.stop()
        if writer is not None:
            await writer.stop()
        await self.tasks.shutdown()

    # --- driving ---

    def signal(self, chat_id: int, text: str) -> None:
        self._message_id += 1
        assert self.source.emit(chat_id, text, message_id=self._message_id)

    def collect(self) -> list[Event]:
        while (event := self.feed.get_nowait()) is not None:
            self.events.append(event)
        return self.events

    async def until(self, condition: Callable[[], bool], tries: int = 2000) -> None:
        for _ in range(tries):
            if condition():
                return
            await asyncio.sleep(0)
        raise AssertionError("condition not reached")

    async def idle(self) -> None:
        await self.engine.manager.wait_idle(5)

    # --- reading what happened ---

    def orders(self, asset: str) -> list[PlacedOrder]:
        return [o for o in self.adapter.orders if o.asset == asset]

    def settle_last(self, asset: str) -> None:
        self.adapter.settle(self.orders(asset)[-1].order_id)

    def chains(self) -> dict[str, ChainRecord]:
        """The latest record of every chain, by its asset (tests use one chain per asset)."""
        latest: dict[str, ChainRecord] = {}
        for event in self.collect():
            if isinstance(event, ChainStarted | ChainAdvanced | ChainEnded):
                latest[event.chain.asset] = event.chain
        return latest

    def trades(self, asset: str) -> list[TradeRecord]:
        """The final record of every trade on the asset, in step order."""
        latest: dict[object, TradeRecord] = {}
        for event in self.collect():
            if isinstance(event, TradeOpened | TradeSettled) and event.trade.asset == asset:
                latest[event.trade.id] = event.trade
        return sorted(latest.values(), key=lambda t: t.step)

    def inbox(self) -> list[SignalRecord]:
        return [e.signal for e in self.collect() if isinstance(e, SignalReceived)]

    def risk_events(self) -> list[RiskTripped]:
        return [e for e in self.collect() if isinstance(e, RiskTripped)]

    def statuses(self, asset: str) -> list[TradeStatus]:
        return [t.status for t in self.trades(asset)]


def make_rig(
    *, clock: Clock | None = None, hold_results: bool = False, result_margin_s: float = 60.0
) -> EngineRig:
    clock = clock or ManualClock()
    bus, tasks = EventBus(), TaskSupervisor()
    adapter = FakeQuotexAdapter(clock=clock, bus=bus, hold_results=hold_results)
    for asset in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD"):
        adapter.add_asset(asset, payout=80)
    source = FakeTelegramSource(clock)
    engine = Engine(
        adapter=adapter,
        source=source,
        bus=bus,
        clock=clock,
        tasks=tasks,
        result_margin_s=result_margin_s,
    )
    feed = bus.subscribe(name="test-feed", maxsize=1_000_000)
    return EngineRig(clock, bus, tasks, adapter, source, engine, feed)


def active_statuses() -> set[ChainStatus]:
    return {ChainStatus.PENDING, ChainStatus.OPEN}


class TimedAdapter(FakeQuotexAdapter):
    """Records when `place_order` is entered, to measure the engine's own overhead."""

    entered_ns: list[int]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.entered_ns = []

    async def place_order(  # type: ignore[no-untyped-def,override]
        self, asset, direction, duration_s, amount
    ):
        self.entered_ns.append(time.perf_counter_ns())
        return await super().place_order(asset, direction, duration_s, amount)


async def measure_latency(count: int, *, through_parser: bool) -> list[int]:
    """Nanoseconds from handing a signal to the engine to the adapter's `place_order` being called.

    `through_parser=False` starts at `ChainManager.on_signal` (the engine proper); `True` starts at
    the fake Telegram source delivering the raw message text (parser, pipeline and engine).
    One signal at a time, so nothing queues behind another. Uses the real clock.
    """
    clock = SystemClock()
    bus, tasks = EventBus(), TaskSupervisor()
    adapter = TimedAdapter(clock=clock, bus=bus)
    adapter.add_asset("EURUSD", payout=80)
    source = FakeTelegramSource(clock)
    engine = Engine(adapter=adapter, source=source, bus=bus, clock=clock, tasks=tasks)
    rig = EngineRig(clock, bus, tasks, adapter, source, engine, bus.subscribe(maxsize=10))
    rig.add_group(GroupSpec(1, -1001, Strategy.NO_MARTINGALE, "1.00"))
    await rig.start()
    bus.unsubscribe(rig.feed)  # nobody reads it here; it would only fill up

    samples: list[int] = []
    for n in range(count):
        started = time.perf_counter_ns()
        if through_parser:
            # a different expiry each time keeps the pipeline's duplicate check out of the way
            rig.signal(-1001, f"EURUSD CALL {10 + n}s")
        else:
            engine.manager.on_signal(
                Signal(
                    id=new_id(),
                    group_id=1,
                    asset="EURUSD",
                    direction=Direction.CALL,
                    duration_s=60,
                    received_at=clock.now(),
                    entry_at=None,
                    t_msg_received_ns=started,
                    t_parsed_ns=started,
                )
            )
        await rig.until(lambda count=n + 1: len(adapter.entered_ns) == count, tries=100_000)
        samples.append(adapter.entered_ns[-1] - started)
        await rig.idle()
    await rig.stop()
    return samples
