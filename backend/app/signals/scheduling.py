"""Deciding *when* a signal with an entry time ("ENTRY: 07:29") should be traded.

The old bot built a naive local time and rolled the day with `day + 1`, which breaks at month end
and ignores the signal's time zone. Here the entry time is a wall-clock time in a known zone and
we pick the occurrence of it that is *closest to now* among yesterday, today and tomorrow. Plain
date arithmetic makes month ends and midnight work, and `zoneinfo` makes daylight-saving changes
work.

Documented behaviour:
- Entry up to `max_late_s` in the past: trade now (the message simply took a moment to arrive).
- Entry further in the past: too late. It is never moved to tomorrow: a stale signal must not
  trade 23 hours later.
- Entry up to `max_ahead_s` in the future: scheduled for exactly that moment.
- Entry further ahead: refused, because a time that far away is more likely a mistake (or a list
  of signals for the whole day) than an instruction.
- A wall-clock time that does not exist (the hour skipped when clocks go forward) is refused.
- A wall-clock time that happens twice (clocks go back) uses whichever occurrence is closest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum


class EntryVerdict(StrEnum):
    NOW = "now"
    SCHEDULED = "scheduled"
    TOO_LATE = "too_late"
    TOO_FAR = "too_far"
    NONEXISTENT = "nonexistent"


@dataclass(slots=True, frozen=True)
class EntryDecision:
    verdict: EntryVerdict
    entry_at: datetime | None  # UTC; None only for NONEXISTENT
    seconds_from_now: float | None  # negative = in the past

    @property
    def describe(self) -> str:
        if self.seconds_from_now is None:
            return "that wall-clock time does not exist on that day (daylight-saving gap)"
        seconds = abs(self.seconds_from_now)
        direction = "ago" if self.seconds_from_now < 0 else "ahead"
        return f"{_human(seconds)} {direction}"


def _human(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _candidates(local_day: date, entry: time, tz: tzinfo) -> dict[datetime, bool]:
    """Each UTC instant at which `entry` shows (or would show) on the clock of `tz` around
    `local_day`, mapped to whether the clock really showed it. A time inside a daylight-saving
    gap never showed; it is kept so that the nearest occurrence can be reported as non-existent
    instead of silently being replaced by another day's."""
    found: dict[datetime, bool] = {}
    for offset_days in (-1, 0, 1):
        day = local_day + timedelta(days=offset_days)
        for fold in (0, 1):
            wall = datetime.combine(day, entry, tzinfo=tz).replace(fold=fold)
            instant = wall.astimezone(UTC)
            # Round trip: a time inside a gap comes back as a different wall time.
            found[instant] = instant.astimezone(tz).replace(tzinfo=None) == wall.replace(
                tzinfo=None
            )
    return found


def resolve_entry(
    entry: time,
    tz: tzinfo,
    now: datetime,
    *,
    max_late_s: float,
    max_ahead_s: float,
) -> EntryDecision:
    """Where `entry` (a time of day in `tz`) falls relative to `now` (timezone-aware)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(UTC)
    candidates = _candidates(now_utc.astimezone(tz).date(), entry, tz)
    entry_at = min(candidates, key=lambda c: abs((c - now_utc).total_seconds()))
    if not candidates[entry_at]:
        return EntryDecision(EntryVerdict.NONEXISTENT, None, None)
    delta = (entry_at - now_utc).total_seconds()
    if delta < -max_late_s:
        verdict = EntryVerdict.TOO_LATE
    elif delta <= 0:
        verdict = EntryVerdict.NOW
    elif delta > max_ahead_s:
        verdict = EntryVerdict.TOO_FAR
    else:
        verdict = EntryVerdict.SCHEDULED
    return EntryDecision(verdict, entry_at, delta)
