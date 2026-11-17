"""Deriv's message shapes, as pure functions (decisions D-74, D-77).

The field names follow Deriv's published JSON schemas (developers.deriv.com/schemas): a symbol is
`underlying_symbol`, its name `underlying_symbol_name`, a contract's trade lengths are
`min_contract_duration` / `max_contract_duration` on the `contracts_for` entries. Nothing here talks
to the network, so every rule can be tested on its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.brokers.errors import PayoutSanityError
from app.domain.enums import AccountType

CENT = Decimal("0.01")
_FOREX = re.compile(r"[A-Z]{6}")
_DURATION = re.compile(r"\s*(\d+)\s*([smhd])\s*")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
SETTLED = frozenset({"won", "lost", "sold", "cancelled"})


# ---- assets ----------------------------------------------------------------------------------


def deriv_symbol(asset: str) -> str | None:
    """Deriv's symbol for one of our asset names. A forex pair keeps its Quotex name (`EURUSD` →
    `frxEURUSD`); a synthetic index is named by Deriv's own symbol (`R_75`, `1HZ100V`) and passes
    unchanged. An `_otc` pair does not exist on Deriv: None."""
    name = asset.strip()
    if not name or name.lower().endswith("_otc"):
        return None
    if _FOREX.fullmatch(name):
        return f"frx{name}"
    return name


def asset_name(symbol: str) -> str:
    """Our name for a Deriv symbol: the reverse of `deriv_symbol`."""
    if symbol.startswith("frx") and _FOREX.fullmatch(symbol[3:]):
        return symbol[3:]
    return symbol


@dataclass(slots=True, frozen=True)
class DerivAsset:
    """One entry of `active_symbols`, under our name."""

    asset: str  # our name: EURUSD, R_75
    symbol: str  # Deriv's: frxEURUSD, R_75
    display_name: str  # "EUR/USD", "Volatility 75 Index"
    market: str  # forex, synthetic_index, ...
    is_open: bool


def parse_active_symbols(rows: object) -> dict[str, DerivAsset]:
    """The assets of an `active_symbols` answer, by Deriv symbol. Rows that do not have the
    documented shape are skipped (a broker adding a field must not stop trading)."""
    assets: dict[str, DerivAsset] = {}
    if not isinstance(rows, list):
        raise PayoutSanityError("Deriv's list of assets is not a list")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = row.get("underlying_symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        is_open = row.get("exchange_is_open") == 1 and row.get("is_trading_suspended") != 1
        assets[symbol] = DerivAsset(
            asset=asset_name(symbol),
            symbol=symbol,
            display_name=str(row.get("underlying_symbol_name") or symbol),
            market=str(row.get("market") or ""),
            is_open=is_open,
        )
    return assets


# ---- trade lengths ---------------------------------------------------------------------------


def duration_seconds(text: object) -> int | None:
    """`"15m"` → 900, `"1d"` → 86400. Ticks (`"5t"`) and anything without a unit → None: a length
    we cannot read is never guessed."""
    match = _DURATION.fullmatch(str(text))
    if match is None:
        return None
    return int(match.group(1)) * _SECONDS[match.group(2)]


@dataclass(slots=True, frozen=True)
class LengthRange:
    min_s: int
    max_s: int

    def allows(self, duration_s: int) -> bool:
        return self.min_s <= duration_s <= self.max_s


def is_rise_fall(entry: Mapping[str, Any]) -> bool:
    """A Rise/Fall entry of `contracts_for`: CALL or PUT in the `callput` category. Read from the
    live demo on 2026-11-17: Deriv marks these with `barriers: 1` (the entry price), and lists
    Higher/Lower under its own `higherlower` category, so the barrier count is not looked at.
    `callputequal` (CALLE/PUTE, where an equal exit wins) is a different contract and left out."""
    return entry.get("contract_category") == "callput" and entry.get("contract_type") in {
        "CALL",
        "PUT",
    }


def rise_fall_lengths(available: Iterable[Mapping[str, Any]]) -> list[LengthRange] | None:
    """The trade lengths Rise/Fall allows on a symbol (tick-counted trades left out). An empty list:
    Rise/Fall is not offered. None: the answer gives them in a form we cannot read, so the broker's
    own refusal of the order decides (it is refused before anything is placed)."""
    ranges: list[LengthRange] = []
    unreadable = False
    for entry in available:
        if not is_rise_fall(entry) or entry.get("expiry_type") == "tick":
            continue
        low = duration_seconds(entry.get("min_contract_duration"))
        high = duration_seconds(entry.get("max_contract_duration"))
        if low is None or high is None:
            unreadable = True
            continue
        ranges.append(LengthRange(low, high))
    if not ranges and unreadable:
        return None
    return _merged(ranges)


def _merged(ranges: list[LengthRange]) -> list[LengthRange]:
    """Ranges that touch or overlap joined: Deriv's intraday `15m`-`1d` and daily `1d`-`365d`
    become one `15m`-`365d`."""
    merged: list[LengthRange] = []
    for r in sorted(set(ranges), key=lambda r: (r.min_s, r.max_s)):
        if merged and r.min_s <= merged[-1].max_s:
            last = merged[-1]
            merged[-1] = LengthRange(last.min_s, max(last.max_s, r.max_s))
        else:
            merged.append(r)
    return merged


def allows(ranges: list[LengthRange] | None, duration_s: int) -> bool:
    return ranges is None or any(r.allows(duration_s) for r in ranges)


def describe_lengths(ranges: list[LengthRange]) -> str:
    """`"15 min to 365 days"` and the like, for the owner."""
    if not ranges:
        return "none (Rise/Fall is not offered on it)"
    return ", ".join(f"{_human(r.min_s)} to {_human(r.max_s)}" for r in ranges)


def _human(seconds: int) -> str:
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "min"), (1, "s")):
        if seconds % size == 0:
            count = seconds // size
            if unit in {"day", "hour"}:
                return f"{count} {unit}{'' if count == 1 else 's'}"
            return f"{count} {unit}"
    return f"{seconds} s"  # pragma: no cover (every whole number is a multiple of 1)


def duration_params(duration_s: int) -> tuple[int, str]:
    """`duration` and `duration_unit` for an order: whole minutes as minutes, else seconds."""
    if duration_s % 60 == 0:
        return duration_s // 60, "m"
    return duration_s, "s"


# ---- money -----------------------------------------------------------------------------------


def to_money(value: object) -> Decimal:
    """A Deriv amount (a number, or text in `proposal_open_contract`) as two-decimal money.
    Raises `PayoutSanityError` if it is not a finite number."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise PayoutSanityError(f"Deriv sent {value!r} where an amount was expected") from exc
    if not amount.is_finite():
        raise PayoutSanityError(f"Deriv sent {value!r} where an amount was expected")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def payout_percent(ask_price: object, payout: object) -> int:
    """The profit of a win as a whole percent of the stake, rounded down (a minimum-payout check
    must never pass on a rounded-up figure). From a `proposal`: (payout - price) / price."""
    price, total = to_money(ask_price), to_money(payout)
    if price <= 0:
        raise PayoutSanityError(f"Deriv priced a contract at {price}")
    percent = ((total - price) / price * 100).to_integral_value(rounding=ROUND_DOWN)
    if not 0 <= percent <= 100:
        raise PayoutSanityError(f"Deriv's payout works out at {percent}%, outside 0-100")
    return int(percent)


def settled_profit(contract: Mapping[str, Any]) -> Decimal | None:
    """The profit of a finished contract from a `proposal_open_contract` update, or None while it
    is still open. A loss is negative; an exit equal to the entry is reported by Deriv as lost."""
    if contract.get("status") not in SETTLED and contract.get("is_sold") != 1:
        return None
    if contract.get("profit") is not None:
        return to_money(contract["profit"])
    if contract.get("sell_price") is not None and contract.get("buy_price") is not None:
        return to_money(contract["sell_price"]) - to_money(contract["buy_price"])
    raise PayoutSanityError("Deriv reported a finished contract without its profit")


# ---- replies and accounts --------------------------------------------------------------------


def error_of(reply: Mapping[str, Any]) -> tuple[str, str] | None:
    """`(code, message)` when Deriv answered with an error, else None."""
    error = reply.get("error")
    if error is None:
        return None
    if isinstance(error, Mapping):
        code = str(error.get("code") or "Error")
        return code, str(error.get("message") or code)
    return "Error", str(error)


DEMO_PREFIXES = ("VR", "DOT")
"""Demo account numbers: the old `VRTC1234` and the new Options API's `DOT90004580`."""
REAL_PREFIXES = ("CR", "MF", "MLT", "MX")
"""Real account numbers on Deriv's older API. The new API's real numbering is not documented, so
any other prefix is "unknown" and never decides on its own."""


def login_kind(loginid: str) -> AccountType | None:
    """Which kind of account a Deriv account number is, or None when the prefix is not known."""
    upper = loginid.strip().upper()
    if upper.startswith(DEMO_PREFIXES):
        return AccountType.DEMO
    if upper.startswith(REAL_PREFIXES):
        return AccountType.REAL
    return None


def is_demo_login(loginid: str) -> bool:
    """True only for a known demo account number (`VR...`, `DOT...`)."""
    return login_kind(loginid) is AccountType.DEMO


def is_demo_account(account: Mapping[str, Any]) -> bool:
    """An entry of the REST account list. Deriv's own `account_type` (or `group`) field decides;
    the account number is only read when that field is missing."""
    kind = str(account.get("account_type") or account.get("group") or "").lower()
    if kind in {"demo", "real"}:
        return kind == "demo"
    return is_demo_login(str(account.get("account_id") or ""))


def socket_kind(url: str) -> AccountType | None:
    """Which account a one-time WebSocket link opens: `.../ws/demo?otp=...` or `.../ws/real?...`."""
    path = url.split("?", 1)[0].rstrip("/")
    if path.endswith("/ws/demo"):
        return AccountType.DEMO
    if path.endswith("/ws/real"):
        return AccountType.REAL
    return None
