"""Time zones as the owner writes them: `UTC-3`, `UTC+5:30`, or an IANA name (`Africa/Nairobi`)."""

from __future__ import annotations

import re
from datetime import UTC, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_OFFSET_HOURS = 14

_OFFSET = re.compile(
    r"^(?:UTC|GMT)?\s*(?P<sign>[+-])\s*(?P<hours>\d{1,2})(?::?(?P<minutes>\d{2}))?$",
    re.IGNORECASE,
)


class InvalidTimezoneError(ValueError):
    """The text is neither a UTC offset nor a known IANA zone name."""


def offset_from_parts(sign: str, hours: int, minutes: int) -> timedelta:
    """A UTC offset, or `InvalidTimezoneError` if it is outside what exists (-14:00 to +14:00)."""
    if minutes > 59 or hours * 60 + minutes > MAX_OFFSET_HOURS * 60:
        raise InvalidTimezoneError(f"UTC offset {sign}{hours}:{minutes:02d} is out of range")
    offset = timedelta(hours=hours, minutes=minutes)
    return -offset if sign == "-" else offset


def fixed_offset(offset: timedelta) -> tzinfo:
    return timezone(offset)


def parse_timezone(text: str) -> tzinfo:
    """`UTC`, `UTC-3`, `GMT+2`, `+05:30` or an IANA name. Raises `InvalidTimezoneError`."""
    value = text.strip()
    if value.upper() in {"UTC", "GMT", "Z"}:
        return UTC
    match = _OFFSET.match(value)
    if match:
        offset = offset_from_parts(match["sign"], int(match["hours"]), int(match["minutes"] or 0))
        return fixed_offset(offset)
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise InvalidTimezoneError(
            f"{text!r} is not a UTC offset like 'UTC-3' or a zone name like 'Africa/Nairobi'"
        ) from exc
