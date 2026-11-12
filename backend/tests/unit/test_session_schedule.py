"""When a session's window opens, repeats and overlaps, and where the candles start (D-73)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from app.domain.enums import RepeatKind
from app.sessions.schedule import (
    Window,
    is_on_boundary,
    is_window_of,
    next_boundary,
    next_window,
    sessions_overlap,
    window_length,
    window_on,
    windows_between,
)
from tests.factories import make_session


def utc(day: int, hour: int = 0, minute: int = 0, second: int = 0, *, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, second, tzinfo=UTC)


# --- one window ---


def test_a_window_is_the_start_and_the_end_in_the_sessions_zone() -> None:
    session = make_session(timezone="UTC-3", start_time=time(8, 0), end_time=time(9, 30))
    window = window_on(session, date(2026, 11, 2))
    assert window == Window(utc(2, 11), utc(2, 12, 30))
    assert window is not None and window.length == timedelta(hours=1, minutes=30)


def test_a_window_may_cross_midnight_and_belongs_to_the_day_it_starts() -> None:
    session = make_session(start_time=time(23, 0), end_time=time(1, 0))
    assert window_on(session, date(2026, 11, 2)) == Window(utc(2, 23), utc(3, 1))
    assert window_length(time(23, 0), time(1, 0)) == timedelta(hours=2)
    assert window_length(time(11, 0), time(12, 0)) == timedelta(hours=1)


def test_a_start_time_that_does_not_exist_gives_no_window_that_day() -> None:
    """Clocks in London went forward on 29 March 2026: 01:30 never happened."""
    session = make_session(timezone="Europe/London", start_time=time(1, 30), end_time=time(2, 30))
    assert window_on(session, date(2026, 3, 29)) is None
    assert window_on(session, date(2026, 3, 30)) is not None


def test_the_window_follows_daylight_saving_with_the_wall_clock() -> None:
    session = make_session(timezone="Europe/London", start_time=time(9, 0), end_time=time(10, 0))
    winter = window_on(session, date(2026, 1, 15))
    summer = window_on(session, date(2026, 7, 15))
    assert winter is not None and summer is not None
    assert winter.start.hour == 9 and summer.start.hour == 8  # 09:00 BST is 08:00 UTC


# --- repeating ---


def test_a_weekday_session_has_windows_on_its_days_only() -> None:
    session = make_session(weekdays=(0, 2))  # Monday and Wednesday
    found = list(windows_between(session, utc(1), utc(8)))  # Sunday 1 Nov to the next Sunday
    assert [w.start for w in found] == [utc(2, 11), utc(4, 11)]


def test_the_next_window_is_the_first_that_starts_at_or_after_the_moment() -> None:
    session = make_session()
    assert next_window(session, utc(1, 10)) == Window(utc(1, 11), utc(1, 12))
    assert next_window(session, utc(1, 11)) == Window(utc(1, 11), utc(1, 12))  # at the start
    assert next_window(session, utc(1, 11, 0, 1)) == Window(utc(2, 11), utc(2, 12))  # just after


def test_a_once_session_has_exactly_one_window_the_first_after_it_was_saved() -> None:
    session = make_session(repeat=RepeatKind.ONCE, weekdays=(), once_after=utc(1, 10, 30))
    assert next_window(session, utc(1, 10, 30)) == Window(utc(1, 11), utc(1, 12))
    assert next_window(session, utc(1, 11, 30)) is None  # it has begun: never again
    assert list(windows_between(session, utc(1), utc(20))) == [Window(utc(1, 11), utc(1, 12))]


def test_a_once_session_saved_after_todays_start_waits_for_tomorrow() -> None:
    session = make_session(repeat=RepeatKind.ONCE, weekdays=(), once_after=utc(1, 11, 30))
    assert next_window(session, utc(1, 11, 30)) == Window(utc(2, 11), utc(2, 12))


def test_a_window_the_session_still_produces_is_recognised() -> None:
    session = make_session(weekdays=(0, 1, 2, 3, 4))
    assert is_window_of(session, Window(utc(2, 11), utc(2, 12)))  # a Monday
    assert not is_window_of(session, Window(utc(1, 11), utc(1, 12)))  # a Sunday
    assert not is_window_of(session, Window(utc(2, 11), utc(2, 13)))  # edited since
    assert not is_window_of(
        make_session(enabled=True, end_time=time(13, 0)), Window(utc(2, 11), utc(2, 12))
    )


# --- two sessions at once ---


def test_windows_that_share_a_moment_overlap() -> None:
    now = utc(1, 9)
    a = make_session(start_time=time(11, 0), end_time=time(12, 0))
    assert sessions_overlap(a, make_session(start_time=time(11, 30), end_time=time(12, 30)), now)
    assert sessions_overlap(a, make_session(start_time=time(10, 0), end_time=time(11, 1)), now)


def test_windows_that_only_touch_do_not_overlap() -> None:
    now = utc(1, 9)
    a = make_session(start_time=time(11, 0), end_time=time(12, 0))
    assert not sessions_overlap(a, make_session(start_time=time(12, 0), end_time=time(13, 0)), now)
    assert not sessions_overlap(a, make_session(start_time=time(10, 0), end_time=time(11, 0)), now)


def test_overlap_is_found_across_midnight() -> None:
    now = utc(1, 9)
    late = make_session(start_time=time(23, 0), end_time=time(1, 0))
    early = make_session(start_time=time(0, 30), end_time=time(2, 0))
    assert sessions_overlap(late, early, now)  # 23:00-01:00 and 00:30-02:00 share 00:30-01:00
    assert not sessions_overlap(late, make_session(start_time=time(1, 0), end_time=time(2, 0)), now)


def test_overlap_depends_on_the_days_and_the_zones() -> None:
    now = utc(1, 9)
    monday = make_session(weekdays=(0,))
    tuesday = make_session(weekdays=(1,))
    assert not sessions_overlap(monday, tuesday, now)  # same hours, different days
    # 11:00-12:00 UTC against 08:00-09:00 in UTC-3 (the same hour of the day, seen from elsewhere)
    elsewhere = make_session(timezone="UTC-3", start_time=time(8, 0), end_time=time(9, 0))
    assert sessions_overlap(make_session(), elsewhere, now)
    apart = make_session(timezone="UTC-3", start_time=time(11, 0), end_time=time(12, 0))
    assert not sessions_overlap(make_session(), apart, now)  # 11:00 UTC-3 is 14:00 UTC


def test_a_once_session_that_has_passed_overlaps_nothing() -> None:
    now = utc(5, 9)
    finished = make_session(repeat=RepeatKind.ONCE, weekdays=(), once_after=utc(1, 10))
    assert not sessions_overlap(finished, make_session(), now)


# --- candles ---


def test_candles_start_at_multiples_of_the_trade_length() -> None:
    assert next_boundary(utc(1, 11, 2, 13), 300) == utc(1, 11, 5)
    assert next_boundary(utc(1, 11, 5), 300) == utc(1, 11, 5)  # already on one
    assert next_boundary(utc(1, 11, 5), 300, after=True) == utc(1, 11, 10)  # strictly later
    assert next_boundary(utc(1, 11, 0, 0), 60, after=True) == utc(1, 11, 1)
    assert next_boundary(utc(1, 23, 59, 30), 300) == utc(2, 0, 0)  # across midnight


def test_a_fraction_of_a_second_past_a_boundary_is_not_on_it() -> None:
    assert is_on_boundary(utc(1, 11, 5), 300)
    assert not is_on_boundary(utc(1, 11, 5) + timedelta(milliseconds=1), 300)
    assert not is_on_boundary(utc(1, 11, 7), 300)
