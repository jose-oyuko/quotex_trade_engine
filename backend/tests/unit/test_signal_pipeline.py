from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.tasks import TaskSupervisor
from app.domain.enums import AssetSuffixMode, Direction, SignalStatus
from app.domain.records import SignalRecord
from app.events.bus import EventBus, Subscription
from app.events.types import SignalReceived
from app.signals.models import Signal
from app.signals.parsers import ParserRegistry, UnknownParserError
from app.signals.parsers.legacy_v1 import LegacyV1Parser
from app.signals.pipeline import GroupRoute, PipelineConfig, SignalPipeline, Sleeper
from app.signals.timezones import InvalidTimezoneError
from tests.factories import make_group, make_settings
from tests.signal_support import T0, FirstWordParser, ManualClock, RecordingSleeper, raw

CHAT = -1001
LABELLED = "ASSET: EUR/USD | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: {entry}"
INLINE = "EURUSD PUT 1m"


@dataclass
class Rig:
    clock: ManualClock
    bus: EventBus
    inbox: Subscription
    tasks: TaskSupervisor
    sleeper: RecordingSleeper
    pipeline: SignalPipeline
    signals: list[Signal] = field(default_factory=list)
    bus_count_at_hand_over: list[int] = field(default_factory=list)

    def rows(self) -> list[SignalRecord]:
        found: list[SignalRecord] = []
        while (event := self.inbox.get_nowait()) is not None:
            assert isinstance(event, SignalReceived)
            found.append(event.signal)
        return found

    def route(self, **changes: object) -> GroupRoute:
        route = replace(make_route(), **changes)
        self.pipeline.set_route(route)
        return route

    async def settle(self) -> None:
        """Let scheduled deliveries (which sleep through the recording sleeper) finish."""
        for _ in range(50):
            if self.tasks.running == 0:
                return
            await asyncio.sleep(0)


def make_route(**changes: object) -> GroupRoute:
    base = GroupRoute(
        group_id=1,
        chat_id=CHAT,
        title="Signals A",
        parser="legacy_v1",
        asset_suffix_mode=AssetSuffixMode.NONE,
        timezone=UTC,
    )
    return replace(base, **changes)


def make_rig(
    *,
    config: PipelineConfig | None = None,
    known: set[str] | None = None,
    route: bool = True,
    sleep: Sleeper | None = None,
) -> Rig:
    clock, bus, tasks, sleeper = ManualClock(), EventBus(), TaskSupervisor(), RecordingSleeper()
    rig_signals: list[Signal] = []
    counts: list[int] = []

    def sink(signal: Signal) -> None:
        counts.append(bus.published)
        rig_signals.append(signal)

    pipeline = SignalPipeline(
        bus=bus,
        clock=clock,
        parsers=ParserRegistry([LegacyV1Parser(), FirstWordParser()]),
        tasks=tasks,
        on_signal=sink,
        is_known_asset=(lambda asset: asset in known) if known is not None else None,
        config=config,
        sleep=sleep or sleeper,
    )
    rig = Rig(
        clock, bus, bus.subscribe(SignalReceived), tasks, sleeper, pipeline, rig_signals, counts
    )
    if route:
        rig.route()
    return rig


# --- routing and recording ---


def test_messages_from_unrouted_chats_are_dropped_not_recorded() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, chat_id=-999))
    assert rig.rows() == [] and rig.signals == []
    assert rig.pipeline.stats.unrouted == 1


def test_a_signal_is_handed_over_and_recorded_with_the_same_id() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, message_id=42))
    [signal] = rig.signals
    [row] = rig.rows()
    assert signal.id == row.id
    assert (signal.asset, signal.direction, signal.duration_s) == ("EURUSD", Direction.PUT, 60)
    assert signal.group_id == 1 and signal.entry_at is None
    assert row.status is SignalStatus.PARSED
    assert row.telegram_message_id == 42 and row.raw_text == INLINE
    assert (row.asset, row.direction, row.duration_s) == ("EURUSD", Direction.PUT, 60)


def test_the_engine_gets_the_signal_before_the_bookkeeping_is_published() -> None:
    """The order must never wait for the inbox row (docs/ARCHITECTURE.md section 4)."""
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE))
    assert rig.bus_count_at_hand_over == [0]
    assert rig.bus.published == 1


def test_latency_timestamps_travel_with_the_signal() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE))
    [signal] = rig.signals
    assert signal.t_parsed_ns > signal.t_msg_received_ns


def test_every_message_of_a_routed_group_is_recorded() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw("hello", message_id=1))
    rig.pipeline.handle(raw(INLINE, message_id=2))
    rig.pipeline.handle(raw("", message_id=3))
    rig.pipeline.handle(raw("✅ WIN", message_id=4))
    rows = rig.rows()
    assert [r.status for r in rows] == [
        SignalStatus.NOT_PARSED,
        SignalStatus.PARSED,
        SignalStatus.NOT_PARSED,
        SignalStatus.NOT_PARSED,
    ]
    assert [r.raw_text for r in rows] == ["hello", INLINE, "", "✅ WIN"]
    assert all(r.reason for r in rows if r.status is SignalStatus.NOT_PARSED)
    assert rig.pipeline.stats.received == 4


def test_a_disabled_group_records_but_does_not_trade() -> None:
    rig = make_rig()
    rig.route(enabled=False)
    rig.pipeline.handle(raw(INLINE))
    [row] = rig.rows()
    assert (row.status, row.reason) == (SignalStatus.IGNORED, "group is disabled")
    assert rig.signals == []


def test_a_route_can_be_removed_at_runtime() -> None:
    rig = make_rig()
    rig.pipeline.remove_route(CHAT)
    rig.pipeline.handle(raw(INLINE))
    assert rig.signals == [] and rig.rows() == []


def test_an_unknown_parser_is_refused_when_the_route_is_set() -> None:
    rig = make_rig(route=False)
    with pytest.raises(UnknownParserError):
        rig.pipeline.set_route(make_route(parser="made_up"))


# --- asset naming ---


@pytest.mark.parametrize(
    ("mode", "text", "expected"),
    [
        (AssetSuffixMode.OTC, "EUR/USD CALL 60s", "EURUSD_otc"),
        (AssetSuffixMode.OTC, "ASSET: EUR/USD (OTC) | DIRECTION: BUY", "EURUSD_otc"),
        (AssetSuffixMode.NONE, "EUR/USD CALL 60s", "EURUSD"),
        (AssetSuffixMode.NONE, "ASSET: EUR/USD (OTC) | DIRECTION: BUY", "EURUSD"),
        (AssetSuffixMode.AUTO, "EUR/USD CALL 60s", "EURUSD"),
        (AssetSuffixMode.AUTO, "ASSET: EUR/USD (OTC) | DIRECTION: BUY", "EURUSD_otc"),
        (AssetSuffixMode.AUTO, "ASSET: EUR/USD | DIRECTION: BUY", "EURUSD"),
    ],
)
def test_the_group_decides_the_otc_suffix(mode: AssetSuffixMode, text: str, expected: str) -> None:
    rig = make_rig()
    rig.route(asset_suffix_mode=mode)
    rig.pipeline.handle(raw(text))
    assert [s.asset for s in rig.signals] == [expected]


def test_the_old_guess_from_the_letters_of_the_pair_is_gone() -> None:
    """The old bot appended _otc whenever the pair contained USD."""
    rig = make_rig()
    rig.pipeline.handle(raw("USD/JPY CALL 60s"))
    assert [s.asset for s in rig.signals] == ["USDJPY"]


def test_unknown_assets_are_ignored_using_the_quotex_name() -> None:
    rig = make_rig(known={"EURUSD_otc"})
    rig.route(asset_suffix_mode=AssetSuffixMode.OTC)
    rig.pipeline.handle(raw("EUR/USD CALL 60s", message_id=1))
    rig.pipeline.handle(raw("GBP/USD CALL 60s", message_id=2))
    assert [s.asset for s in rig.signals] == ["EURUSD_otc"]
    ignored = rig.rows()[1]
    assert ignored.status is SignalStatus.IGNORED and ignored.reason == "unknown asset GBPUSD_otc"


# --- stale messages, edits, duplicates ---


def test_a_message_that_arrives_long_after_it_was_sent_is_not_traded() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, sent_at=T0 - timedelta(minutes=10)))
    [row] = rig.rows()
    assert row.status is SignalStatus.IGNORED and row.reason is not None
    assert row.reason.startswith("stale")
    assert rig.signals == []


def test_normal_delivery_delay_and_a_clock_that_runs_slow_are_fine() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw("EURUSD PUT 1m", message_id=1, sent_at=T0 - timedelta(seconds=3)))
    rig.pipeline.handle(raw("EURUSD CALL 1m", message_id=2, sent_at=T0 + timedelta(seconds=5)))
    assert len(rig.signals) == 2


def test_an_edit_of_a_message_that_was_a_signal_is_not_traded_again() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, message_id=7))
    rig.pipeline.handle(raw(INLINE, message_id=7, edited=True))
    rig.pipeline.handle(raw(INLINE, message_id=7, edited=True))
    assert len(rig.signals) == 1
    rows = rig.rows()
    assert [r.status for r in rows] == [
        SignalStatus.PARSED,
        SignalStatus.IGNORED,
        SignalStatus.IGNORED,
    ]
    assert rows[1].reason == "message already processed"


def test_an_edit_that_changes_the_signal_is_still_not_traded_again() -> None:
    """Edited twice, differently: no edit may ever become a second trade, however it reads."""
    rig = make_rig()
    rig.pipeline.handle(raw("EURUSD PUT 1m", message_id=7))
    rig.pipeline.handle(raw("EURUSD CALL 1m", message_id=7, edited=True))
    rig.pipeline.handle(raw("GBPUSD CALL 5m", message_id=7, edited=True))
    assert [s.direction for s in rig.signals] == [Direction.PUT]


def test_an_edit_can_turn_a_non_signal_into_a_signal() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw("EURUSD PUT", message_id=8))
    rig.pipeline.handle(raw("EURUSD PUT 1m", message_id=8, edited=True))
    assert len(rig.signals) == 1


def test_the_same_message_delivered_twice_is_processed_once() -> None:
    """After a reconnect Telegram can deliver a message again, not marked as edited."""
    rig = make_rig()
    rig.pipeline.handle(raw("hello", message_id=9))
    rig.pipeline.handle(raw("hello", message_id=9))
    rows = rig.rows()
    assert [r.status for r in rows] == [SignalStatus.NOT_PARSED, SignalStatus.IGNORED]


def test_messages_without_an_id_are_never_treated_as_repeats() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw("EURUSD PUT 1m", message_id=None))
    rig.clock.advance(600)
    rig.pipeline.handle(raw("EURUSD PUT 1m", message_id=None, at=rig.clock.now()))
    assert len(rig.signals) == 2


def test_the_same_signal_posted_again_is_a_duplicate_until_the_window_passes() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, message_id=1))
    rig.clock.advance(60)
    rig.pipeline.handle(raw(INLINE, message_id=2))  # a repost, or a forward from another channel
    assert len(rig.signals) == 1
    assert rig.rows()[1].reason == "duplicate signal"
    rig.clock.advance(300)
    rig.pipeline.handle(raw(INLINE, message_id=3))
    assert len(rig.signals) == 2


def test_a_different_direction_or_expiry_is_not_a_duplicate() -> None:
    rig = make_rig()
    for index, text in enumerate(["EURUSD PUT 1m", "EURUSD CALL 1m", "EURUSD PUT 5m"]):
        rig.pipeline.handle(raw(text, message_id=index))
    assert len(rig.signals) == 3


def test_old_messages_are_forgotten_so_memory_stays_bounded() -> None:
    rig = make_rig(config=PipelineConfig(remembered_messages=2))
    for message_id in (1, 2, 3):
        rig.pipeline.handle(raw("hello", message_id=message_id))
    rig.pipeline.handle(raw("hello", message_id=1))  # forgotten: processed like a new message
    rig.pipeline.handle(raw("hello", message_id=3))  # still remembered
    statuses = [r.status for r in rig.rows()]
    assert statuses[-2:] == [SignalStatus.NOT_PARSED, SignalStatus.IGNORED]


# --- notes ---


def test_assumed_expiry_and_extra_signals_are_noted_in_the_inbox() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw("USD/INR;10:00;PUT\nGBP/CHF;10:05;CALL"))
    [row] = rig.rows()
    assert row.status is SignalStatus.PARSED
    assert row.reason is not None
    assert "expiry not stated, assumed 60 s" in row.reason
    assert "holds 2 signals, only the first is used" in row.reason


# --- entry times ---


async def test_a_future_entry_time_is_parked_and_delivered_at_that_moment() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(LABELLED.format(entry="10:05")))
    assert rig.signals == []  # not yet
    [row] = rig.rows()
    assert row.status is SignalStatus.PARSED
    assert row.entry_time == datetime(2026, 11, 1, 10, 5, tzinfo=UTC)
    assert row.reason == "scheduled for 10:05:00 UTC"
    await rig.settle()
    assert rig.sleeper.delays == [300.0]
    [signal] = rig.signals
    assert signal.entry_at == datetime(2026, 11, 1, 10, 5, tzinfo=UTC) and signal.id == row.id


async def test_the_groups_time_zone_is_used_for_entry_times() -> None:
    rig = make_rig()
    rig.route(timezone=ZoneInfo("Africa/Nairobi"))  # UTC+3
    rig.pipeline.handle(raw(LABELLED.format(entry="13:05")))
    await rig.settle()
    assert rig.sleeper.delays == [300.0]


async def test_a_zone_stated_in_the_message_wins_over_the_groups() -> None:
    rig = make_rig()
    rig.route(timezone=ZoneInfo("Africa/Nairobi"))
    rig.pipeline.handle(raw(LABELLED.format(entry="07:05") + "\nTime Zone: UTC -3"))
    await rig.settle()
    assert rig.sleeper.delays == [300.0]


def test_an_entry_time_that_is_due_now_trades_at_once() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(LABELLED.format(entry="10:00")))
    [signal] = rig.signals
    assert signal.entry_at is None


def test_a_slightly_late_entry_time_trades_at_once() -> None:
    rig = make_rig()
    rig.clock.advance(20)
    rig.pipeline.handle(raw(LABELLED.format(entry="10:00"), at=rig.clock.now()))
    assert len(rig.signals) == 1


@pytest.mark.parametrize(
    ("entry", "expected"),
    [("09:30", "already passed"), ("14:00", "too far")],
)
def test_entry_times_in_the_past_or_far_ahead_are_ignored(entry: str, expected: str) -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(LABELLED.format(entry=entry)))
    [row] = rig.rows()
    assert row.status is SignalStatus.IGNORED
    assert row.reason is not None and expected in row.reason
    assert rig.signals == []


def test_an_entry_time_in_the_daylight_saving_gap_is_ignored() -> None:
    rig = make_rig()
    rig.route(timezone=ZoneInfo("America/New_York"))
    rig.clock.set(datetime(2026, 3, 8, 6, 45, tzinfo=UTC))  # 01:45 in New York
    rig.pipeline.handle(raw(LABELLED.format(entry="02:30"), at=rig.clock.now()))
    [row] = rig.rows()
    assert row.status is SignalStatus.IGNORED
    assert row.reason is not None and "does not exist" in row.reason


async def test_a_group_disabled_before_the_entry_time_does_not_trade_and_the_row_says_so() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(LABELLED.format(entry="10:05"), message_id=5))
    [stored] = rig.rows()
    rig.route(enabled=False)
    await rig.settle()
    assert rig.signals == []
    [update] = rig.rows()
    assert update.id == stored.id  # replaces the row, does not add one
    assert update.status is SignalStatus.IGNORED
    assert update.reason == "group disabled before entry time"
    assert update.raw_text == stored.raw_text and update.telegram_message_id == 5


async def test_scheduled_deliveries_are_cancelled_cleanly_at_shutdown() -> None:
    async def forever(_: float) -> None:
        await asyncio.Event().wait()

    rig = make_rig(sleep=forever)
    rig.pipeline.handle(raw(LABELLED.format(entry="10:05")))
    await asyncio.sleep(0)
    assert rig.tasks.running == 1
    await rig.tasks.shutdown()
    assert rig.tasks.running == 0 and rig.signals == []


# --- robustness ---


def test_a_failing_engine_cannot_stop_the_pipeline() -> None:
    clock, bus = ManualClock(), EventBus()
    inbox = bus.subscribe(SignalReceived)

    def broken(_: Signal) -> None:
        raise RuntimeError("engine bug")

    pipeline = SignalPipeline(
        bus=bus,
        clock=clock,
        parsers=ParserRegistry(),
        tasks=TaskSupervisor(),
        on_signal=broken,
    )
    pipeline.set_route(make_route())
    pipeline.handle(raw(INLINE, message_id=1))
    pipeline.handle(raw("hello", message_id=2))
    assert pipeline.stats.sink_errors == 1 and pipeline.stats.received == 2
    assert inbox.depth == 2


def test_counters_add_up() -> None:
    rig = make_rig()
    rig.pipeline.handle(raw(INLINE, message_id=1))
    rig.pipeline.handle(raw("hello", message_id=2))
    rig.pipeline.handle(raw(INLINE, message_id=3))  # duplicate
    stats = rig.pipeline.stats
    assert (stats.received, stats.parsed, stats.not_parsed, stats.ignored) == (3, 1, 1, 1)
    assert stats.handed_over == 1


# --- routes from stored records ---


def test_a_route_is_built_from_the_stored_group_and_its_settings() -> None:
    group = replace(make_group(telegram_chat_id=-1005, title="Alpha"), id=3)
    route = GroupRoute.from_records(group, make_settings(3, timezone="UTC-3"))
    assert (route.group_id, route.chat_id, route.title, route.parser) == (
        3,
        -1005,
        "Alpha",
        "legacy_v1",
    )
    assert route.timezone.utcoffset(None) == timedelta(hours=-3)
    assert route.enabled is True


def test_a_route_needs_a_stored_group_and_a_valid_time_zone() -> None:
    with pytest.raises(ValueError, match="no id"):
        GroupRoute.from_records(make_group(), make_settings(1))
    with pytest.raises(InvalidTimezoneError):
        GroupRoute.from_records(replace(make_group(), id=1), make_settings(1, timezone="Mars/Base"))
