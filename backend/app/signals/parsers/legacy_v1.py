"""`legacy_v1`: the signal formats the old bot understood (docs/DOMAIN.md section 4), ported and
tightened.

Formats (case-insensitive, emojis and markdown ignored):
  1. labelled   `ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29`
  2. compact    `5 minutes expiry USD/BDT;15:00;PUT`, `USD/INR;03:30;PUT`, `GBP/CHF; 18:16; CALL`
  3. inline     `EUR/USD CALL 60s`, `EURUSD PUT 1m`

What changed from the old parser, each one a weakness listed in DOMAIN.md:
- The direction is never guessed. The old fallback defaulted to CALL, which turned any chatter that
  mentioned a pair into a buy. No direction means "not a signal".
- Words are matched whole (`PUT` inside `INPUT`, `UP` inside `UPDATE` no longer count) and units may
  be plural or hyphenated ("5 minutes", "5-minute").
- A pair must look like one: a slash pair, or six letters made of two known currency codes. A word
  such as `SIGNAL` after "expiry" is no longer taken for an asset.
- Whether to add the OTC suffix is not decided here; the parser only reports that the message said
  OTC and the group's setting decides (`app/signals/assets.py`).
- Entry times stay a plain time of day plus the zone the message states; turning them into an
  instant is `app/signals/scheduling.py`.
- Channel-side "gale" lines are dropped: our own strategy decides follow-ups.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import time

from app.domain.enums import Direction
from app.signals.models import ParsedSignal, ParseOutcome
from app.signals.timezones import InvalidTimezoneError, offset_from_parts

NAME = "legacy_v1"

MAX_CHARS = 4096  # Telegram's own limit for a message
DEFAULT_DURATION_S = 60  # the old bot's default when the message names no expiry
MIN_DURATION_S = 5
MAX_DURATION_S = 86_400

_DIRECTIONS = {
    "BUY": Direction.CALL,
    "UP": Direction.CALL,
    "CALL": Direction.CALL,
    "SELL": Direction.PUT,
    "DOWN": Direction.PUT,
    "PUT": Direction.PUT,
}

# Currency, metal and crypto codes accepted when a pair is written without a slash ("EURUSD").
_CODES = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "AUD",
        "CAD",
        "CHF",
        "NZD",
        "NOK",
        "SEK",
        "DKK",
        "SGD",
        "HKD",
        "MXN",
        "ZAR",
        "TRY",
        "PLN",
        "CZK",
        "HUF",
        "CNH",
        "CNY",
        "INR",
        "BRL",
        "ARS",
        "COP",
        "CLP",
        "PEN",
        "EGP",
        "NGN",
        "KES",
        "BDT",
        "PKR",
        "IDR",
        "LKR",
        "THB",
        "PHP",
        "VND",
        "ILS",
        "RUB",
        "XAU",
        "XAG",
        "XPT",
        "XPD",
        "BTC",
        "ETH",
        "LTC",
        "XRP",
        "BNB",
        "ADA",
        "SOL",
        "DOT",
        "UKO",
        "USO",
    }
)

# Words that can sit on either side of a slash without being an asset ("BUY/SELL", "WIN/LOSS").
_NOT_ASSET_WORDS = frozenset(
    {
        "BUY",
        "SELL",
        "CALL",
        "PUT",
        "UP",
        "DOWN",
        "AND",
        "OR",
        "WIN",
        "LOSS",
        "LOSE",
        "WON",
        "TP",
        "SL",
        "TIME",
        "ENTRY",
        "GALE",
        "OTC",
        "MIN",
        "MINS",
        "SEC",
        "SECS",
    }
)

_DIR = r"(?<![A-Z])(?P<dir>BUY|SELL|CALL|PUT|UP|DOWN)(?![A-Z])"
_PAIR = (
    r"(?<![A-Z0-9])(?:(?P<b1>[A-Z]{2,6})\s*/\s*(?P<q1>[A-Z]{2,6})|(?P<b2>[A-Z]{3})(?P<q2>[A-Z]{3}))"
    r"(?![A-Z0-9])"
)
_HHMM = r"(?<!\d)(?P<h>\d{1,2}):(?P<min>\d{2})(?::\d{2})?(?!\d)"
_UNIT = r"(?:SECONDS?|SECS?|MINUTES?|MINS?|HOURS?|[SMH])(?![A-Z])"

_PAIR_ONLY = re.compile(_PAIR)
_LABEL_ASSET = re.compile(rf"ASSET\s*:\s*{_PAIR}")
_LABEL_DIRECTION = re.compile(rf"DIRECTION\s*:[^A-Z]*{_DIR}")
_LABEL_ENTRY = re.compile(rf"ENTRY(?:\s*TIME)?\s*:\s*{_HHMM}")
_EXPIRY = re.compile(
    rf"EXPIR(?:Y|ATION|ES?)\s*(?:TIME)?\s*:?\s*"
    rf"(?:(?P<code>[MH])\s*(?P<n1>\d+)(?![A-Z0-9])|(?P<n2>\d+)\s*(?P<unit>{_UNIT}))"
)
_COMPACT = re.compile(rf"{_PAIR}\s*[;|,]\s*{_HHMM}\s*[;|,]\s*{_DIR}")
_INLINE = re.compile(rf"{_PAIR}\s+{_DIR}\s*[:\-]?\s*(?P<n>\d+)\s*(?P<unit>{_UNIT})")
_DURATION_WORDS = re.compile(
    r"(?<![A-Z0-9:])(?P<n>\d{1,3})\s*-?\s*(?P<unit>MINUTES?|MINS?|SECONDS?|SECS?|HOURS?)(?![A-Z])"
)
_DURATION_CODE = re.compile(r"(?<![A-Z0-9])M(?P<n>\d{1,2})(?![A-Z0-9])")
_ZONE_LABELLED = re.compile(
    r"(?:TIME\s*ZONE|TIMEZONE|TZ)\s*:?\s*(?:UTC|GMT)?\s*"
    r"(?P<sign>[+-])\s*(?P<h>\d{1,2})(?::?(?P<min>\d{2}))?"
)
_ZONE_BARE = re.compile(
    r"(?<![A-Z])(?:UTC|GMT)\s*(?P<sign>[+-])\s*(?P<h>\d{1,2})(?::?(?P<min>\d{2}))?"
)
_OTC = re.compile(r"(?<![A-Z])OTC(?![A-Z])|_OTC")
_GALE_MARKER = r"(?:GALE|GALES|MARTINGALE|PROTECTION)(?![A-Z])"
_GALE_ANYWHERE = re.compile(rf"(?<![A-Z]){_GALE_MARKER}")
_GALE_AT_START = re.compile(rf"^[^A-Z0-9]*(?:\d+(?:ST|ND|RD|TH)\s+)?{_GALE_MARKER}")

_UNIT_SECONDS = {"S": 1, "M": 60, "H": 3600}


# Look-alikes channels use: minus sign and en dash for "-", no-break space, zero-width space.
_LOOK_ALIKES = str.maketrans({0x2212: "-", 0x2013: "-", 0x00A0: " ", 0x200B: None})


def _clean(text: str) -> str:
    """Upper-case, and drop the decoration channels put around messages."""
    return text.upper().translate(_LOOK_ALIKES).replace("*", "").replace("`", "")


def _drop_gale_lines(text: str) -> tuple[str, bool]:
    kept: list[str] = []
    dropped = False
    for line in text.splitlines():
        is_gale = _GALE_AT_START.match(line) or (
            _GALE_ANYWHERE.search(line) and _first_asset(_PAIR_ONLY, line) is None
        )
        if is_gale:
            dropped = True
        else:
            kept.append(line)
    return "\n".join(kept), dropped


def _asset_from(match: re.Match[str]) -> str | None:
    base, quote = match["b1"], match["q1"]
    if base is None:  # written without a slash: both halves must be real codes
        base, quote = match["b2"], match["q2"]
        if base not in _CODES or quote not in _CODES:
            return None
    if base in _NOT_ASSET_WORDS or quote in _NOT_ASSET_WORDS:
        return None
    return f"{base}{quote}"


def _first_asset(pattern: re.Pattern[str], text: str) -> str | None:
    for match in pattern.finditer(text):
        asset = _asset_from(match)
        if asset is not None:
            return asset
    return None


def _seconds(amount: str, unit: str) -> int:
    return int(amount) * _UNIT_SECONDS[unit[0]]


def _expiry_seconds(match: re.Match[str]) -> int:
    if match["code"]:
        return _seconds(match["n1"], match["code"])
    return _seconds(match["n2"], match["unit"])


def _find_duration(text: str) -> int | None:
    """An expiry mentioned anywhere in the message, for formats that do not carry one."""
    if match := _EXPIRY.search(text):
        return _expiry_seconds(match)
    if match := _DURATION_WORDS.search(text):
        return _seconds(match["n"], match["unit"])
    if match := _DURATION_CODE.search(text):
        return int(match["n"]) * 60
    return None


def _entry_time(match: re.Match[str]) -> time | str:
    hour, minute = int(match["h"]), int(match["min"])
    if hour > 23 or minute > 59:
        return f"invalid entry time {match['h']}:{match['min']}"
    return time(hour, minute)


class LegacyV1Parser:
    name = NAME

    def parse(self, text: str) -> ParseOutcome:
        if not text.strip():
            return ParseOutcome(reason="empty message")
        body, had_gale = _drop_gale_lines(_clean(text[:MAX_CHARS]))
        if not body.strip():
            return ParseOutcome(reason="only a channel gale hint (our strategy decides follow-ups)")

        for read in (self._labelled, self._compact, self._inline):
            found = read(body)
            if found is not None:
                return self._finish(found, body)
        if had_gale:
            return ParseOutcome(reason="gale hint without a signal in the message")
        return ParseOutcome(reason="no known signal format found")

    # --- formats: each returns a signal, a reason, or None when the format is simply absent ---

    def _labelled(self, text: str) -> ParsedSignal | str | None:
        asset_match = _LABEL_ASSET.search(text)
        direction_match = _LABEL_DIRECTION.search(text)
        if asset_match is None or direction_match is None:
            return None
        asset = _asset_from(asset_match)
        if asset is None:
            return "the ASSET field does not hold a plausible pair"
        entry: time | None = None
        if entry_match := _LABEL_ENTRY.search(text):
            parsed_entry = _entry_time(entry_match)
            if isinstance(parsed_entry, str):
                return parsed_entry
            entry = parsed_entry
        expiry = _EXPIRY.search(text)
        duration = _expiry_seconds(expiry) if expiry else _find_duration(text)
        return self._signal("labelled", asset, direction_match["dir"], duration, entry)

    def _compact(self, text: str) -> ParsedSignal | str | None:
        matches = [m for m in _COMPACT.finditer(text) if _asset_from(m) is not None]
        if not matches:
            return None
        first = matches[0]
        entry = _entry_time(first)
        if isinstance(entry, str):
            return entry
        result = self._signal(
            "compact", _asset_from(first) or "", first["dir"], _find_duration(text), entry
        )
        if isinstance(result, ParsedSignal):
            # A message listing several signals: only the first is used, and the inbox says so.
            return replace(result, extra_signals=len(matches) - 1)
        return result

    def _inline(self, text: str) -> ParsedSignal | str | None:
        for match in _INLINE.finditer(text):
            asset = _asset_from(match)
            if asset is not None:
                duration = _seconds(match["n"], match["unit"])
                return self._signal("inline", asset, match["dir"], duration, None)
        return None

    # --- shared tail ---

    def _signal(
        self, format_name: str, asset: str, word: str, duration: int | None, entry: time | None
    ) -> ParsedSignal | str:
        assumed = duration is None
        seconds = DEFAULT_DURATION_S if duration is None else duration
        if not MIN_DURATION_S <= seconds <= MAX_DURATION_S:
            return f"expiry of {seconds} s is outside {MIN_DURATION_S}-{MAX_DURATION_S} s"
        return ParsedSignal(
            base_asset=asset,
            direction=_DIRECTIONS[word],
            duration_s=seconds,
            entry_time=entry,
            utc_offset=None,
            otc_mentioned=False,
            format_name=format_name,
            duration_assumed=assumed,
        )

    def _finish(self, found: ParsedSignal | str, text: str) -> ParseOutcome:
        if isinstance(found, str):
            return ParseOutcome(reason=found)
        offset = None
        if zone := _ZONE_LABELLED.search(text) or _ZONE_BARE.search(text):
            try:
                offset = offset_from_parts(zone["sign"], int(zone["h"]), int(zone["min"] or 0))
            except InvalidTimezoneError as exc:
                return ParseOutcome(reason=str(exc))
        return ParseOutcome(
            signal=replace(found, utc_offset=offset, otc_mentioned=bool(_OTC.search(text)))
        )
