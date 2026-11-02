"""Test helpers for the signal pipeline and the Telegram listener."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.domain.enums import Direction
from app.signals.models import ParsedSignal, ParseOutcome, RawMessage

# A Sunday morning, so "now" is far from midnight and from any month end.
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


class ManualClock:
    """Time that only moves when the test says so."""

    def __init__(self, now: datetime = T0) -> None:
        self._now = now
        self._ns = 1_000_000_000

    def now(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        self._ns += 1_000  # every reading is a little later, like a real clock
        return self._ns

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, now: datetime) -> None:
        self._now = now


class RecordingSleeper:
    """Replaces `asyncio.sleep`: records the requested delays and returns at once."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(
            0
        )  # still a real suspension point, so loops built on it can be cancelled


class FirstWordParser:
    """A second parser, for tests of per-group parser choice: `BUY EURUSD` / `SELL EURUSD`."""

    name = "first_word"

    def parse(self, text: str) -> ParseOutcome:
        parts = text.upper().split()
        if len(parts) == 2 and parts[0] in {"BUY", "SELL"}:
            return ParseOutcome(
                signal=ParsedSignal(
                    base_asset=parts[1],
                    direction=Direction.CALL if parts[0] == "BUY" else Direction.PUT,
                    duration_s=60,
                    entry_time=None,
                    utc_offset=None,
                    otc_mentioned=False,
                    format_name="first_word",
                )
            )
        return ParseOutcome(reason="not BUY/SELL <asset>")


def raw(
    text: str,
    *,
    chat_id: int = -1001,
    message_id: int | None = 1,
    at: datetime = T0,
    edited: bool = False,
    sent_at: datetime | None = None,
) -> RawMessage:
    return RawMessage(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        received_at=at,
        received_ns=1,
        sent_at=sent_at,
        edited=edited,
    )
