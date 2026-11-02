"""Reading pyquotex's positional data safely.

The library hands over instrument rows as plain lists and reads payouts from fixed positions
(`i[-9]`, `i[-8]`). If Quotex changes the layout those numbers silently become wrong, so every
read here is validated and fails loudly (decision D-12). All layout assumptions live in this file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.domain.enums import AccountType
from app.quotex.errors import PayoutSanityError

# Positions inside one instrument row, as pyquotex 1.1.0 reads them (_api/assets.py).
SYMBOL = 1
OPEN_FLAG = 14
PAYOUT_1M = -9
PAYOUT_5M = -8
MIN_COLUMNS = 19  # the library also reads index 18; anything shorter is not the known layout

Row = Sequence[Any]


def find_instrument(rows: Sequence[Row], asset: str) -> Row | None:
    for row in rows:
        if len(row) > SYMBOL and row[SYMBOL] == asset:
            return row
    return None


def _check_layout(row: Row) -> None:
    if len(row) < MIN_COLUMNS:
        raise PayoutSanityError(
            f"unexpected instrument layout for {row[SYMBOL] if len(row) > SYMBOL else '?'}: "
            f"{len(row)} columns, expected at least {MIN_COLUMNS}"
        )


def instrument_is_open(row: Row) -> bool:
    _check_layout(row)
    return bool(row[OPEN_FLAG])


def instrument_payout(row: Row, minutes: int) -> int:
    """Payout percent for an expiry of `minutes`. Quotex publishes a 1-minute and a 5-minute
    figure; shorter than 5 minutes uses the first, 5 and longer the second."""
    _check_layout(row)
    raw = row[PAYOUT_1M] if minutes < 5 else row[PAYOUT_5M]
    asset = row[SYMBOL]
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise PayoutSanityError(f"payout for {asset} is not a number: {raw!r}")
    if not 0 <= raw <= 100:
        raise PayoutSanityError(f"payout for {asset} is outside 0-100: {raw!r}")
    return round(raw)


def balance_from_payload(
    payload: Mapping[str, Any] | None, account_type: AccountType
) -> Decimal | None:
    """Balance of the given account from Quotex's balance message, to the cent (truncated, like
    the library does); None if the message does not carry it."""
    if not payload:
        return None
    key = "demoBalance" if account_type is AccountType.DEMO else "liveBalance"
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except ArithmeticError:
        return None


def profit_from_number(raw: Any) -> Decimal:
    """A profit figure from a result message, as a two-decimal Decimal."""
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise PayoutSanityError(f"profit is not a number: {raw!r}")
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    except ArithmeticError as exc:
        raise PayoutSanityError(f"profit is not a number: {raw!r}") from exc
