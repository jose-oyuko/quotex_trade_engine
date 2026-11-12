"""When a trading session's window opens and closes, and where the candles start (decision D-73).

Pure functions of the saved session and a moment in time: nothing here reads a clock or waits, so
every rule is tested with plain datetimes. A window is `[start, end)`: the first pair may go out at
`start`, and no pair starts at or after `end`.

Wall-clock times are in the session's own zone (`UTC-3`, `Africa/Nairobi`, ...), so daylight saving
moves the window with the clock, as the owner expects. A start time that does not exist on a day
(the hour skipped when clocks go forward) means no window that day; a time that happens twice uses
the first occurrence. A window may cross midnight: it belongs to the day it starts on.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from math import ceil

from app.domain.enums import RepeatKind
from app.domain.records import SessionRecord
from app.signals.timezones import parse_timezone

# The trade lengths Quotex offers that are whole minutes (the adapter asks for the payout by the
# minute). A candle is as long as the trade.
TRADE_LENGTHS_S = (60, 120, 180, 300, 600, 900, 1800, 3600, 14400)

# How many days around a moment are searched. A window is never longer than a day, and a weekly
# pattern repeats within seven.
SEARCH_DAYS = 8
OVERLAP_HORIZON_DAYS = 15


@dataclass(slots=True, frozen=True)
class Window:
    start: datetime  # UTC
    end: datetime  # UTC

    @property
    def length(self) -> timedelta:
        return self.end - self.start


def window_length(start: time, end: time) -> timedelta:
    """How long the window is, by the wall clock (a window that ends 'before' it starts crosses
    midnight)."""
    seconds = _seconds(end) - _seconds(start)
    if seconds <= 0:
        seconds += 24 * 3600
    return timedelta(seconds=seconds)


def window_on(session: SessionRecord, day: date) -> Window | None:
    """The window that starts on the local date `day`, or None if its start time does not exist
    that day. The repeat rule is not applied here."""
    tz = parse_timezone(session.timezone)
    return _window_on(session, day, tz)


def _window_on(session: SessionRecord, day: date, tz: tzinfo) -> Window | None:
    start_local = datetime.combine(day, session.start_time, tzinfo=tz)
    start = start_local.astimezone(UTC)
    if start.astimezone(tz).replace(tzinfo=None) != start_local.replace(tzinfo=None):
        return None  # the wall-clock time falls in the hour that clocks skip
    end_day = day if session.end_time > session.start_time else day + timedelta(days=1)
    end = datetime.combine(end_day, session.end_time, tzinfo=tz).astimezone(UTC)
    if end <= start:  # a daylight-saving change inside a very short window
        return None
    return Window(start, end)


def windows_between(
    session: SessionRecord, since: datetime, until: datetime | None = None
) -> Iterator[Window]:
    """The windows of the session that start at or after `since` (and before `until`), in order.

    ONCE: at most one, the first window that starts at or after `once_after`, and only if it is
    still ahead of `since` (a window that has begun is never offered again, and nothing follows).
    """
    tz = parse_timezone(session.timezone)
    if session.repeat is RepeatKind.ONCE:
        first = _first_once_window(session, tz)
        if first is not None and first.start >= since and (until is None or first.start < until):
            yield first
        return
    first_day = since.astimezone(tz).date() - timedelta(days=1)
    last_day = (until or since + timedelta(days=SEARCH_DAYS)).astimezone(tz).date() + timedelta(
        days=1
    )
    day = first_day
    while day <= last_day:
        if day.weekday() in session.weekdays:
            window = _window_on(session, day, tz)
            if (
                window is not None
                and window.start >= since
                and (until is None or window.start < until)
            ):
                yield window
        day += timedelta(days=1)


def _first_once_window(session: SessionRecord, tz: tzinfo) -> Window | None:
    day = session.once_after.astimezone(tz).date() - timedelta(days=1)
    for _ in range(SEARCH_DAYS):
        window = _window_on(session, day, tz)
        if window is not None and window.start >= session.once_after:
            return window
        day += timedelta(days=1)
    return None


def next_window(session: SessionRecord, since: datetime) -> Window | None:
    """The first window that starts at or after `since`, or None (a finished ONCE session)."""
    return next(windows_between(session, since), None)


def is_window_of(session: SessionRecord, window: Window) -> bool:
    """True if `window` is one the saved session still produces (it was edited or disabled while a
    start was being waited for: then the start must not happen)."""
    return any(w == window for w in windows_between(session, window.start, window.end))


def sessions_overlap(a: SessionRecord, b: SessionRecord, now: datetime) -> bool:
    """True if a window of `a` and a window of `b` share any moment in the next fifteen days (a
    weekly pattern repeats within that, so this covers every case that can happen)."""
    horizon = now + timedelta(days=OVERLAP_HORIZON_DAYS)
    start = now - timedelta(days=1)
    windows_a = list(windows_between(a, start, horizon))
    windows_b = list(windows_between(b, start, horizon))
    return any(x.start < y.end and y.start < x.end for x in windows_a for y in windows_b)


def next_boundary(at: datetime, length_s: int, *, after: bool = False) -> datetime:
    """The start of the next candle: a multiple of the trade length counted from the Unix epoch
    (for M5: :00, :05, :10 ...). `at` itself if it is on one, unless `after` asks for a strictly
    later one."""
    if length_s <= 0:
        raise ValueError("the trade length must be greater than 0")
    seconds = (at - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()
    n = ceil(seconds / length_s)
    if after and n * length_s <= seconds:
        n += 1
    return datetime.fromtimestamp(n * length_s, UTC)


def is_on_boundary(at: datetime, length_s: int) -> bool:
    """True if `at` is exactly the start of a candle of that length."""
    return next_boundary(at, length_s) == at


def _seconds(value: time) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def local_date(moment: datetime, timezone: str) -> date:
    return moment.astimezone(parse_timezone(timezone)).date()
