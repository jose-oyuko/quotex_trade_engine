"""SignalPipeline: raw Telegram message in, validated `Signal` (or a recorded reason) out.

For every message of a routed group the pipeline does the same steps, in memory, without waiting
for anything:

    route by chat -> stale? -> already seen? -> parse -> asset name -> known asset?
                  -> entry time -> duplicate? -> hand to the engine (now, or at the entry time)

Whatever happens, the message ends up in the signal inbox as exactly one `SignalReceived` event
(`parsed`, `not_parsed` or `ignored`, with a reason); the DB writer stores it off this path.
The hand-over (`on_signal`) happens *before* that event is published, so the order never waits for
bookkeeping. A signal with a future entry time is parked on a supervised timer and handed over at
that moment.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, tzinfo

import structlog

from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.domain.enums import AssetSuffixMode, SignalStatus
from app.domain.ids import new_id
from app.domain.records import GroupRecord, GroupSettingsRecord, SignalRecord
from app.events.bus import EventBus
from app.events.types import SignalReceived
from app.signals.assets import quotex_asset
from app.signals.models import ParsedSignal, RawMessage, Signal
from app.signals.parsers.registry import ParserRegistry
from app.signals.scheduling import EntryVerdict, resolve_entry
from app.signals.timezones import fixed_offset, parse_timezone

log = structlog.get_logger()

type SignalSink = Callable[[Signal], None]
type Sleeper = Callable[[float], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class GroupRoute:
    """What the pipeline needs to know about one Telegram group."""

    group_id: int
    chat_id: int
    title: str
    parser: str
    asset_suffix_mode: AssetSuffixMode
    timezone: tzinfo
    enabled: bool = True

    @classmethod
    def from_records(cls, group: GroupRecord, settings: GroupSettingsRecord) -> GroupRoute:
        """Raises `InvalidTimezoneError` if the group's time zone text is not valid."""
        if group.id is None:
            raise ValueError("the group has not been stored yet (no id)")
        return cls(
            group_id=group.id,
            chat_id=group.telegram_chat_id,
            title=group.title,
            parser=settings.parser,
            asset_suffix_mode=settings.asset_suffix_mode,
            timezone=parse_timezone(settings.timezone),
            enabled=group.enabled,
        )


@dataclass(slots=True, frozen=True)
class PipelineConfig:
    max_message_age_s: float = 120.0  # older than this when it reaches us: do not trade it
    max_entry_late_s: float = 30.0  # entry time this far in the past still trades at once
    max_entry_ahead_s: float = 3600.0  # entry time further ahead than this is refused
    duplicate_window_s: float = 300.0  # the same signal again within this time is a duplicate
    remembered_messages: int = 20_000


@dataclass(slots=True)
class PipelineStats:
    received: int = 0
    unrouted: int = 0
    parsed: int = 0
    not_parsed: int = 0
    ignored: int = 0
    handed_over: int = 0
    sink_errors: int = 0


class SignalPipeline:
    def __init__(
        self,
        *,
        bus: EventBus,
        clock: Clock,
        parsers: ParserRegistry,
        tasks: TaskSupervisor,
        on_signal: SignalSink,
        is_known_asset: Callable[[str], bool] | None = None,
        config: PipelineConfig | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._parsers = parsers
        self._tasks = tasks
        self._on_signal = on_signal
        self._is_known_asset = is_known_asset
        self._config = config or PipelineConfig()
        self._sleep = sleep
        self._routes: dict[int, GroupRoute] = {}
        self._seen: OrderedDict[tuple[int, int], SignalStatus] = OrderedDict()
        self._recent: OrderedDict[tuple[object, ...], datetime] = OrderedDict()
        self.stats = PipelineStats()

    # --- routes (one per Telegram chat; updated at runtime when groups change) ---

    def set_route(self, route: GroupRoute) -> None:
        self._parsers.get(route.parser)  # fail now, not on the first message
        self._routes[route.chat_id] = route

    def remove_route(self, chat_id: int) -> None:
        self._routes.pop(chat_id, None)

    @property
    def routes(self) -> list[GroupRoute]:
        return list(self._routes.values())

    # --- the path from message to signal ---

    def handle(self, raw: RawMessage) -> None:
        """Process one message. Synchronous and non-blocking; never raises for bad input."""
        self.stats.received += 1
        route = self._routes.get(raw.chat_id)
        if route is None:
            self.stats.unrouted += 1
            return

        if not route.enabled:
            self._record(route, raw, SignalStatus.IGNORED, "group is disabled")
            return
        if (age := self._age_s(raw)) is not None and age > self._config.max_message_age_s:
            self._record(
                route, raw, SignalStatus.IGNORED, f"stale: sent {age:.0f} s before it arrived"
            )
            return
        if self._already_handled(route, raw):
            self._record(route, raw, SignalStatus.IGNORED, "message already processed")
            return

        outcome = self._parsers.get(route.parser).parse(raw.text)
        t_parsed = self._clock.monotonic_ns()
        parsed = outcome.signal
        if parsed is None:
            self._record(route, raw, SignalStatus.NOT_PARSED, outcome.reason)
            return
        self._accept(route, raw, parsed, t_parsed)

    def _accept(
        self, route: GroupRoute, raw: RawMessage, parsed: ParsedSignal, t_parsed_ns: int
    ) -> None:
        asset = quotex_asset(
            parsed.base_asset, route.asset_suffix_mode, otc_mentioned=parsed.otc_mentioned
        )
        if self._is_known_asset is not None and not self._is_known_asset(asset):
            self._record(route, raw, SignalStatus.IGNORED, f"unknown asset {asset}", parsed, asset)
            return

        now = self._clock.now()
        entry_at: datetime | None = None
        if parsed.entry_time is not None:
            tz = (
                fixed_offset(parsed.utc_offset) if parsed.utc_offset is not None else route.timezone
            )
            decision = resolve_entry(
                parsed.entry_time,
                tz,
                now,
                max_late_s=self._config.max_entry_late_s,
                max_ahead_s=self._config.max_entry_ahead_s,
            )
            entry_at = decision.entry_at
            if decision.verdict in (EntryVerdict.TOO_LATE, EntryVerdict.TOO_FAR):
                what = "already passed" if decision.verdict is EntryVerdict.TOO_LATE else "too far"
                reason = f"entry time {parsed.entry_time:%H:%M} {what} ({decision.describe})"
                self._record(route, raw, SignalStatus.IGNORED, reason, parsed, asset)
                return
            if decision.verdict is EntryVerdict.NONEXISTENT:
                reason = f"entry time {parsed.entry_time:%H:%M}: {decision.describe}"
                self._record(route, raw, SignalStatus.IGNORED, reason, parsed, asset)
                return
            if decision.verdict is EntryVerdict.NOW:
                entry_at = None  # due already: trade at once

        if self._is_duplicate(route, asset, parsed, entry_at, now):
            self._record(route, raw, SignalStatus.IGNORED, "duplicate signal", parsed, asset)
            return

        signal = Signal(
            id=new_id(),
            group_id=route.group_id,
            asset=asset,
            direction=parsed.direction,
            duration_s=parsed.duration_s,
            received_at=raw.received_at,
            entry_at=entry_at,
            t_msg_received_ns=raw.received_ns,
            t_parsed_ns=t_parsed_ns,
        )
        notes = self._notes(parsed)
        if entry_at is None:
            self._hand_over(signal)  # first: the order must not wait for the bookkeeping below
            self._record(route, raw, SignalStatus.PARSED, notes or None, parsed, asset, signal)
            return
        notes = "; ".join(filter(None, [f"scheduled for {entry_at:%H:%M:%S} UTC", notes]))
        record = self._record(route, raw, SignalStatus.PARSED, notes, parsed, asset, signal)
        delay = max(0.0, (entry_at - now).total_seconds())
        self._tasks.spawn(self._deliver_at(signal, record, delay), name=f"signal-{signal.id}")

    # --- hand-over ---

    def _hand_over(self, signal: Signal) -> None:
        try:
            self._on_signal(signal)
        except Exception:
            # A bug in the engine must not stop the listener from recording and parsing messages.
            self.stats.sink_errors += 1
            log.exception("signal_sink_failed", signal_id=str(signal.id))
        else:
            self.stats.handed_over += 1

    async def _deliver_at(self, signal: Signal, record: SignalRecord, delay_s: float) -> None:
        await self._sleep(delay_s)
        route = next((r for r in self._routes.values() if r.group_id == signal.group_id), None)
        if route is None or not route.enabled:
            # Same id as the stored row, so this replaces it: only status and reason change.
            changed = replace(
                record, status=SignalStatus.IGNORED, reason="group disabled before entry time"
            )
            self.stats.ignored += 1
            self._bus.publish(SignalReceived(occurred_at=self._clock.now(), signal=changed))
            return
        self._hand_over(signal)

    # --- bookkeeping ---

    def _age_s(self, raw: RawMessage) -> float | None:
        if raw.sent_at is None:
            return None
        return (raw.received_at - raw.sent_at).total_seconds()

    def _already_handled(self, route: GroupRoute, raw: RawMessage) -> bool:
        """The same Telegram message again (an edit, or a re-delivery after a reconnect).

        Only a message that did *not* become a signal may be looked at again, and only if it was
        edited: a channel fixing its typo must be able to turn a non-signal into a signal.
        """
        if raw.message_id is None:
            return False
        key = (route.group_id, raw.message_id)
        previous = self._seen.get(key)
        if previous is None:
            return False
        return previous is SignalStatus.PARSED or not raw.edited

    def _is_duplicate(
        self,
        route: GroupRoute,
        asset: str,
        parsed: ParsedSignal,
        entry_at: datetime | None,
        now: datetime,
    ) -> bool:
        window = timedelta(seconds=self._config.duplicate_window_s)
        while self._recent and next(iter(self._recent.values())) < now - window:
            self._recent.popitem(last=False)
        key = (route.group_id, asset, parsed.direction, parsed.duration_s, entry_at)
        if key in self._recent:
            return True
        self._recent[key] = now
        return False

    def _remember(self, route: GroupRoute, raw: RawMessage, status: SignalStatus) -> None:
        if raw.message_id is None:
            return
        key = (route.group_id, raw.message_id)
        if self._seen.get(key) is not SignalStatus.PARSED:  # once a signal, always a signal
            self._seen[key] = status
        self._seen.move_to_end(key)
        while len(self._seen) > self._config.remembered_messages:
            self._seen.popitem(last=False)

    @staticmethod
    def _notes(parsed: ParsedSignal) -> str:
        notes = []
        if parsed.duration_assumed:
            notes.append(f"expiry not stated, assumed {parsed.duration_s} s")
        if parsed.extra_signals:
            notes.append(
                f"message holds {parsed.extra_signals + 1} signals, only the first is used"
            )
        return "; ".join(notes)

    def _record(
        self,
        route: GroupRoute,
        raw: RawMessage,
        status: SignalStatus,
        reason: str | None,
        parsed: ParsedSignal | None = None,
        asset: str | None = None,
        signal: Signal | None = None,
    ) -> SignalRecord:
        """Write the inbox row for this message (as an event) and update the counters."""
        record_id = signal.id if signal else new_id()
        self._remember(route, raw, status)
        match status:
            case SignalStatus.PARSED:
                self.stats.parsed += 1
            case SignalStatus.NOT_PARSED:
                self.stats.not_parsed += 1
            case SignalStatus.IGNORED:
                self.stats.ignored += 1
        record = SignalRecord(
            id=record_id,
            group_id=route.group_id,
            telegram_message_id=raw.message_id,
            received_at=raw.received_at.astimezone(UTC),
            raw_text=raw.text,
            status=status,
            reason=reason,
            asset=asset,
            direction=parsed.direction if parsed else None,
            duration_s=parsed.duration_s if parsed else None,
            entry_time=signal.entry_at if signal else None,
        )
        self._bus.publish(SignalReceived(occurred_at=self._clock.now(), signal=record))
        return record
