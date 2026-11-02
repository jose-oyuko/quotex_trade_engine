"""Value objects passed between the Telegram listener, the parsers and the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID

from app.domain.enums import Direction


@dataclass(slots=True, frozen=True)
class RawMessage:
    """One Telegram message as the listener saw it, before any interpretation.

    `received_at` / `received_ns` are taken the moment the listener got it (wall clock for storage,
    monotonic for latency). `sent_at` is Telegram's own timestamp, used only to spot stale messages.
    """

    chat_id: int
    message_id: int | None
    text: str
    received_at: datetime
    received_ns: int
    sent_at: datetime | None = None
    edited: bool = False


@dataclass(slots=True, frozen=True)
class ParsedSignal:
    """What a parser read from the text. Nothing here depends on the group's settings."""

    base_asset: str  # "EURUSD": no OTC suffix, that is decided per group
    direction: Direction
    duration_s: int
    entry_time: time | None  # wall-clock time of day as written; None = trade now
    utc_offset: timedelta | None  # zone the message itself states ("Time Zone: UTC -3")
    otc_mentioned: bool
    format_name: str
    duration_assumed: bool = False  # the message did not state an expiry
    extra_signals: int = 0  # further signals in the same message that were not used


@dataclass(slots=True, frozen=True)
class ParseOutcome:
    """Exactly one of `signal` / `reason` is set: a parsed signal, or why the text is not one."""

    signal: ParsedSignal | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (self.signal is None) == (self.reason is None):
            raise ValueError("a ParseOutcome has either a signal or a reason")


@dataclass(slots=True, frozen=True)
class Signal:
    """A validated trade instruction, handed to the engine (Phase 4).

    `id` is also the id of the inbox row, so a later stage can update that row (for example
    "ignored: chain active") by publishing the same id again.
    """

    id: UUID
    group_id: int
    asset: str  # the Quotex name: "EURUSD" or "EURUSD_otc"
    direction: Direction
    duration_s: int
    received_at: datetime
    entry_at: datetime | None  # UTC; None = place the order at once
    t_msg_received_ns: int
    t_parsed_ns: int
