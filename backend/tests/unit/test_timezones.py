from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.signals.timezones import InvalidTimezoneError, offset_from_parts, parse_timezone

NOON = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "hours"),
    [
        ("UTC", 0),
        ("utc", 0),
        ("GMT", 0),
        ("Z", 0),
        ("UTC-3", -3),
        ("UTC -3", -3),
        ("utc+3", 3),
        ("GMT+2", 2),
        ("+05:30", 5.5),
        ("UTC+5:30", 5.5),
        ("-0330", -3.5),
        ("UTC+14", 14),
        ("UTC-12", -12),
    ],
)
def test_utc_offsets_are_understood(text: str, hours: float) -> None:
    assert parse_timezone(text).utcoffset(NOON) == timedelta(hours=hours)


def test_iana_names_are_understood() -> None:
    assert parse_timezone("Africa/Nairobi").utcoffset(NOON) == timedelta(hours=3)
    assert parse_timezone("America/New_York").utcoffset(NOON) == timedelta(hours=-4)  # summer


@pytest.mark.parametrize("text", ["", "UTC+15", "UTC-3:75", "Mars/Olympus", "../etc", "3", "UTC+"])
def test_nonsense_is_refused(text: str) -> None:
    with pytest.raises(InvalidTimezoneError):
        parse_timezone(text)


def test_offset_limits() -> None:
    assert offset_from_parts("-", 3, 30) == timedelta(hours=-3, minutes=-30)
    with pytest.raises(InvalidTimezoneError):
        offset_from_parts("+", 14, 1)
