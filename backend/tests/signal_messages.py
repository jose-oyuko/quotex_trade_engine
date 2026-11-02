"""Example messages for the parser tests.

The first group is taken from the owner's own examples (docs/PHASES.md, docs/DOMAIN.md section 4).
The rest are variations built from the same formats, because real channel posts differ in
decoration and spacing. Replace or extend these with real messages as the owner collects them;
every row is one test case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta

from app.domain.enums import Direction


@dataclass(frozen=True)
class Expected:
    asset: str  # without the OTC suffix
    direction: Direction
    duration_s: int
    entry: time | None
    otc: bool = False
    utc_offset: timedelta | None = None
    duration_assumed: bool = False
    extra: int = 0


ENTRY_CONFIRMED = (
    "✅ **ENTRY CONFIRMED** ✅\n"
    "🌎 ASSET: USD/JPY (OTC)\n"
    "⏳ EXPIRATION: M1\n"
    "📊 DIRECTION: 🟢 BUY\n"
    "⏰ ENTRY: 07:29\n"
    "1ST GALE — TIME TO 07:30\n"
    "2ND GALE — TIME TO 07:31"
)

# (id, text, expected)
SIGNALS: list[tuple[str, str, Expected]] = [
    (
        "owner-example-labelled-one-line",
        "ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29",
        Expected("USDJPY", Direction.CALL, 60, time(7, 29), otc=True),
    ),
    (
        "owner-example-entry-confirmed-with-gale-lines",
        ENTRY_CONFIRMED,
        Expected("USDJPY", Direction.CALL, 60, time(7, 29), otc=True),
    ),
    (
        "owner-example-minutes-expiry",
        "💰5 minutes expiry USD/BDT;15:00;PUT 🟥",
        Expected("USDBDT", Direction.PUT, 300, time(15, 0)),
    ),
    (
        "minutes-expiry-with-time-zone-line",
        "💰5 minutes expiry USD/BDT;15:00;PUT 🟥\nTime Zone: UTC -3",
        Expected("USDBDT", Direction.PUT, 300, time(15, 0), utc_offset=timedelta(hours=-3)),
    ),
    (
        "pair-time-direction-expiry-elsewhere",
        "🔔 Signal\n5 MINUTES EXPIRY\nUSD/INR;03:30;PUT 🟥",
        Expected("USDINR", Direction.PUT, 300, time(3, 30)),
    ),
    (
        "pair-time-direction-no-expiry-assumes-60",
        "USD/INR;03:30;PUT 🟥",
        Expected("USDINR", Direction.PUT, 60, time(3, 30), duration_assumed=True),
    ),
    (
        "spaced-semicolons-and-glued-emoji",
        "GBP/CHF; 18:16; CALL🟩",
        Expected("GBPCHF", Direction.CALL, 60, time(18, 16), duration_assumed=True),
    ),
    (
        "inline-seconds",
        "EUR/USD CALL 60s",
        Expected("EURUSD", Direction.CALL, 60, None),
    ),
    (
        "inline-no-slash-minutes",
        "EURUSD PUT 1m",
        Expected("EURUSD", Direction.PUT, 60, None),
    ),
    (
        "inline-lower-case-and-plural-unit",
        "eurusd put 5 minutes",
        Expected("EURUSD", Direction.PUT, 300, None),
    ),
    (
        "labelled-sell-with-down-arrow-emoji",
        "ASSET: EUR/GBP\nEXPIRATION: M5\nDIRECTION: 🔴 SELL\nENTRY: 21:05",
        Expected("EURGBP", Direction.PUT, 300, time(21, 5)),
    ),
    (
        "labelled-without-entry-trades-now",
        "ASSET: AUD/CAD | EXPIRATION: M2 | DIRECTION: BUY",
        Expected("AUDCAD", Direction.CALL, 120, None),
    ),
    (
        "labelled-expiration-in-words",
        "ASSET: EUR/USD | EXPIRATION: 3 MINUTES | DIRECTION: SELL | ENTRY: 9:05",
        Expected("EURUSD", Direction.PUT, 180, time(9, 5)),
    ),
    (
        "labelled-with-gmt-offset-text",
        "ASSET: EUR/USD | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 12:00 | GMT+2",
        Expected("EURUSD", Direction.CALL, 60, time(12, 0), utc_offset=timedelta(hours=2)),
    ),
    (
        "markdown-bold-around-fields",
        "**ASSET:** USD/CAD (OTC)\n**EXPIRATION:** M1\n**DIRECTION:** SELL\n**ENTRY:** 14:45",
        Expected("USDCAD", Direction.PUT, 60, time(14, 45), otc=True),
    ),
    (
        "list-of-signals-uses-the-first",
        "USD/INR;03:30;PUT 🟥\nGBP/CHF;03:35;CALL 🟩\nEUR/USD;03:40;PUT 🟥",
        Expected("USDINR", Direction.PUT, 60, time(3, 30), duration_assumed=True, extra=2),
    ),
]

# (id, text): none of these may become a signal.
NON_SIGNALS: list[tuple[str, str]] = [
    ("empty", ""),
    ("only-spaces", "   \n  "),
    ("chatter", "Good morning everyone, big day today!"),
    ("result-win", "✅ WIN EUR/USD +85%"),
    ("result-loss", "❌ LOSS USD/JPY"),
    ("gale-hint-only", "1ST GALE — TIME TO 19:00"),
    ("gale-hint-with-emoji", "🔁 2ND GALE — TIME TO 19:05"),
    ("word-signal-after-expiry", "💰5 minutes expiry SIGNAL;15:00;PUT 🟥"),
    ("put-inside-input", "please check the input of EUR/USD tonight"),
    ("up-at-the-start-of-update", "EUR/USD;10:00;UPDATE"),
    (
        "buy-at-the-start-of-buyer",
        "ASSET: EUR/USD | EXPIRATION: M1 | DIRECTION: BUYER | ENTRY: 10:00",
    ),
    ("call-at-the-start-of-calling", "EURUSD CALLING 60s"),
    ("buy-sell-slash", "BUY/SELL signals coming soon"),
    ("pair-and-time-but-no-direction", "EUR/USD 12:00 get ready"),
    ("pair-only", "EUR/USD"),
    ("direction-only", "CALL 60s"),
    ("invalid-hour", "USD/INR;27:30;PUT 🟥"),
    ("invalid-minute", "ASSET: EUR/USD | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 12:75"),
    ("label-without-direction", "ASSET: EUR/USD | EXPIRATION: M1 | ENTRY: 12:00"),
    ("expiry-too-long", "ASSET: EUR/USD | EXPIRATION: H48 | DIRECTION: BUY | ENTRY: 12:00"),
]
