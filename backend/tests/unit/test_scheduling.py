"""Entry-time handling (Phase 3): month end, midnight, daylight saving, times already past."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import pytest

from app.signals.scheduling import EntryDecision, EntryVerdict, resolve_entry

LATE, AHEAD = 30.0, 3600.0
UTC_MINUS_3 = timezone(timedelta(hours=-3))
NEW_YORK = ZoneInfo("America/New_York")


def decide(entry: time, tz: tzinfo, now: datetime) -> EntryDecision:
    return resolve_entry(entry, tz, now, max_late_s=LATE, max_ahead_s=AHEAD)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_a_time_a_few_minutes_ahead_is_scheduled_for_exactly_then() -> None:
    result = decide(time(7, 29), UTC, utc(2026, 11, 1, 7, 24))
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == utc(2026, 11, 1, 7, 29)
    assert result.seconds_from_now == 300


def test_the_zone_of_the_entry_time_is_applied() -> None:
    """07:29 in UTC-3 is 10:29 UTC."""
    result = decide(time(7, 29), UTC_MINUS_3, utc(2026, 11, 1, 10, 20))
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == utc(2026, 11, 1, 10, 29)


def test_the_entry_minute_itself_trades_now() -> None:
    assert decide(time(7, 29), UTC, utc(2026, 11, 1, 7, 29, 0)).verdict is EntryVerdict.NOW


def test_a_slightly_late_message_still_trades_now() -> None:
    result = decide(time(7, 29), UTC, utc(2026, 11, 1, 7, 29, 20))
    assert result.verdict is EntryVerdict.NOW
    assert result.seconds_from_now == -20


def test_the_lateness_limit_is_exact() -> None:
    assert decide(time(7, 29), UTC, utc(2026, 11, 1, 7, 29, 30)).verdict is EntryVerdict.NOW
    assert decide(time(7, 29), UTC, utc(2026, 11, 1, 7, 29, 31)).verdict is EntryVerdict.TOO_LATE


def test_a_time_earlier_today_is_too_late_and_never_moved_to_tomorrow() -> None:
    result = decide(time(7, 29), UTC, utc(2026, 11, 1, 15, 0))
    assert result.verdict is EntryVerdict.TOO_LATE
    assert result.entry_at == utc(2026, 11, 1, 7, 29)  # today's, not tomorrow's
    assert "ago" in result.describe


def test_the_ahead_limit_is_exact() -> None:
    assert decide(time(11, 0), UTC, utc(2026, 11, 1, 10, 0)).verdict is EntryVerdict.SCHEDULED
    assert decide(time(11, 1), UTC, utc(2026, 11, 1, 10, 0)).verdict is EntryVerdict.TOO_FAR


# --- midnight and month end: the old bot's `day + 1` broke here ---


def test_just_before_midnight_an_early_morning_time_means_tomorrow() -> None:
    result = decide(time(0, 10), UTC, utc(2026, 11, 1, 23, 50))
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == utc(2026, 11, 2, 0, 10)


def test_just_after_midnight_a_late_evening_time_is_yesterday_and_too_late() -> None:
    result = decide(time(23, 55), UTC, utc(2026, 11, 2, 0, 5))
    assert result.verdict is EntryVerdict.TOO_LATE
    assert result.entry_at == utc(2026, 11, 1, 23, 55)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 11, 30, 23, 55), utc(2026, 12, 1, 0, 5)),  # 30-day month
        (utc(2026, 1, 31, 23, 55), utc(2026, 2, 1, 0, 5)),  # 31-day month
        (utc(2026, 2, 28, 23, 55), utc(2026, 3, 1, 0, 5)),  # February, not a leap year
        (utc(2028, 2, 28, 23, 55), utc(2028, 2, 29, 0, 5)),  # February, leap year
        (utc(2028, 2, 29, 23, 55), utc(2028, 3, 1, 0, 5)),
        (utc(2026, 12, 31, 23, 55), utc(2027, 1, 1, 0, 5)),  # year end
    ],
)
def test_month_and_year_ends_roll_over_correctly(now: datetime, expected: datetime) -> None:
    result = decide(time(0, 5), UTC, now)
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == expected


def test_local_midnight_differs_from_utc_midnight() -> None:
    """In UTC-3 it is still Oct 31 at 02:50 UTC on Nov 1, so 23:59 local is 9 minutes away."""
    result = decide(time(23, 59), UTC_MINUS_3, utc(2026, 11, 1, 2, 50))
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == utc(2026, 11, 1, 2, 59)


# --- daylight saving ---


def test_a_time_inside_the_spring_forward_gap_does_not_exist() -> None:
    """On 2026-03-08 New York jumped from 02:00 to 03:00: 02:30 never happened."""
    result = decide(time(2, 30), NEW_YORK, utc(2026, 3, 8, 6, 45))  # 01:45 local
    assert result.verdict is EntryVerdict.NONEXISTENT
    assert result.entry_at is None
    assert "does not exist" in result.describe


def test_a_time_after_the_gap_uses_the_new_offset() -> None:
    """03:10 local on that day is 07:10 UTC (EDT, UTC-4), not 08:10."""
    result = decide(time(3, 10), NEW_YORK, utc(2026, 3, 8, 6, 55))  # 01:55 EST
    assert result.verdict is EntryVerdict.SCHEDULED
    assert result.entry_at == utc(2026, 3, 8, 7, 10)
    assert result.seconds_from_now == 15 * 60


def test_a_time_before_the_gap_uses_the_old_offset() -> None:
    """01:50 local on that day is 06:50 UTC (EST, UTC-5)."""
    result = decide(time(1, 50), NEW_YORK, utc(2026, 3, 8, 6, 40))
    assert result.entry_at == utc(2026, 3, 8, 6, 50)


def test_a_repeated_time_in_the_fall_back_hour_picks_the_nearer_occurrence() -> None:
    """On 2026-11-01 New York repeated 01:30: 05:30 UTC (EDT) and 06:30 UTC (EST)."""
    early = decide(time(1, 30), NEW_YORK, utc(2026, 11, 1, 5, 25))
    assert early.verdict is EntryVerdict.SCHEDULED
    assert early.entry_at == utc(2026, 11, 1, 5, 30)
    second = decide(time(1, 30), NEW_YORK, utc(2026, 11, 1, 6, 25))
    assert second.verdict is EntryVerdict.SCHEDULED
    assert second.entry_at == utc(2026, 11, 1, 6, 30)


def test_a_fixed_offset_has_no_daylight_saving() -> None:
    result = decide(time(2, 30), UTC_MINUS_3, utc(2026, 3, 8, 5, 25))
    assert result.entry_at == utc(2026, 3, 8, 5, 30)


def test_now_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        decide(time(7, 0), UTC, datetime(2026, 11, 1, 7, 0))
