"""Deriv's message rules (app/deriv/protocol.py): pure, no network."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers.errors import PayoutSanityError
from app.deriv.protocol import (
    ContractTerms,
    LengthRange,
    allows,
    asset_name,
    deriv_symbol,
    describe_lengths,
    duration_params,
    duration_seconds,
    early_profit,
    error_of,
    exit_quote,
    is_demo_account,
    is_demo_login,
    login_kind,
    parse_active_symbols,
    payout_percent,
    rise_fall_lengths,
    settled_profit,
    socket_kind,
    tick_of,
    to_money,
)
from app.domain.enums import AccountType

D = Decimal


@pytest.mark.parametrize(
    ("asset", "symbol"),
    [
        ("EURUSD", "frxEURUSD"),
        ("R_75", "R_75"),
        ("1HZ100V", "1HZ100V"),
        ("frxGBPUSD", "frxGBPUSD"),
        ("EURUSD_otc", None),
        ("eurusd_OTC", None),
        ("", None),
    ],
)
def test_our_asset_names_map_to_deriv_symbols(asset: str, symbol: str | None) -> None:
    assert deriv_symbol(asset) == symbol


def test_deriv_symbols_map_back_to_our_names() -> None:
    assert asset_name("frxEURUSD") == "EURUSD"
    assert asset_name("R_75") == "R_75"
    assert asset_name("frxXAU") == "frxXAU"  # not a six-letter pair: kept as it is


def test_active_symbols_are_read_by_their_documented_names() -> None:
    assets = parse_active_symbols(
        [
            {
                "underlying_symbol": "frxEURUSD",
                "underlying_symbol_name": "EUR/USD",
                "market": "forex",
                "exchange_is_open": 1,
                "is_trading_suspended": 0,
            },
            {
                "underlying_symbol": "R_75",
                "underlying_symbol_name": "Volatility 75 Index",
                "market": "synthetic_index",
                "exchange_is_open": 1,
                "is_trading_suspended": 1,
            },
            {"underlying_symbol": "frxAUDUSD", "exchange_is_open": 0},
            {"symbol": "OLD", "exchange_is_open": 1},  # an old-style row: skipped
            "not a row",
        ]
    )
    assert set(assets) == {"frxEURUSD", "R_75", "frxAUDUSD"}
    eur = assets["frxEURUSD"]
    assert (eur.asset, eur.display_name, eur.market, eur.is_open) == (
        "EURUSD",
        "EUR/USD",
        "forex",
        True,
    )
    assert assets["R_75"].is_open is False  # suspended
    assert assets["frxAUDUSD"].is_open is False
    assert assets["frxAUDUSD"].display_name == "frxAUDUSD"
    with pytest.raises(PayoutSanityError):
        parse_active_symbols({"not": "a list"})


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("15s", 15),
        ("1m", 60),
        ("15m", 900),
        ("2h", 7200),
        ("365d", 365 * 86400),
        ("5t", None),
        ("5", None),
        ("", None),
        (None, None),
        ("1 m", 60),
    ],
)
def test_trade_lengths_are_read_only_with_a_unit(text: object, seconds: int | None) -> None:
    assert duration_seconds(text) == seconds


def rf(low: str, high: str, **extra: object) -> dict[str, object]:
    return {
        "contract_category": "callput",
        "contract_type": "CALL",
        "barriers": 0,
        "expiry_type": "intraday",
        "min_contract_duration": low,
        "max_contract_duration": high,
        **extra,
    }


def test_rise_fall_lengths_leave_out_ticks_and_other_contracts() -> None:
    lengths = rise_fall_lengths(
        [
            rf("1t", "10t", expiry_type="tick"),
            rf("15s", "1d"),
            rf("15s", "1d", contract_type="PUT"),  # the same range for the other direction
            rf("1m", "1d", contract_category="higherlower", contract_type="HIGHER"),
            rf("1m", "1d", contract_category="callputequal", contract_type="CALLE"),
            rf("1m", "1d", contract_category="digits"),
        ]
    )
    assert lengths == [LengthRange(15, 86400)]
    higher_lower = rf("1d", "365d", contract_category="higherlower", contract_type="LOWER")
    assert rise_fall_lengths([higher_lower]) == []  # no Rise/Fall at all


def test_the_live_eurusd_offer_reads_as_15_minutes_to_365_days() -> None:
    """The entries the live demo sent for EURUSD on 2026-11-17 (barriers: 1 on Rise/Fall)."""
    lengths = rise_fall_lengths(
        [
            rf("1d", "365d", expiry_type="daily", barrier="1.10117"),
            rf("1d", "365d", expiry_type="daily", contract_type="PUT"),
            rf("15m", "1d"),
            rf("15m", "1d", contract_type="PUT"),
            rf("15m", "1d", contract_category="callputequal", contract_type="CALLE"),
        ]
    )
    assert lengths == [LengthRange(900, 365 * 86400)]
    assert describe_lengths(lengths) == "15 min to 365 days"
    gap = rise_fall_lengths([rf("15s", "1m"), rf("5m", "1d")])
    assert gap == [LengthRange(15, 60), LengthRange(300, 86400)]  # a real gap stays a gap


def test_lengths_written_without_units_are_not_guessed() -> None:
    assert rise_fall_lengths([rf("5", "10")]) is None
    assert allows(None, 60) is True  # Deriv's own refusal decides
    assert rise_fall_lengths([rf("5", "10"), rf("15m", "1d")]) == [LengthRange(900, 86400)]


def test_allows_and_describes_lengths() -> None:
    forex = [LengthRange(900, 365 * 86400)]
    assert not allows(forex, 60) and not allows(forex, 300) and allows(forex, 900)
    assert describe_lengths(forex) == "15 min to 365 days"
    assert describe_lengths([LengthRange(15, 86400)]) == "15 s to 1 day"
    assert describe_lengths([]) == "none (Rise/Fall is not offered on it)"


@pytest.mark.parametrize(("seconds", "params"), [(60, (1, "m")), (900, (15, "m")), (45, (45, "s"))])
def test_order_lengths_are_sent_in_minutes_when_whole(
    seconds: int, params: tuple[int, str]
) -> None:
    assert duration_params(seconds) == params


def test_money_is_two_decimals_from_numbers_or_text() -> None:
    assert to_money(10) == D("10.00")
    assert to_money("9.505") == D("9.51")
    assert to_money(0.1 + 0.2) == D("0.30")
    for bad in ("abc", "NaN", None):
        with pytest.raises(PayoutSanityError):
            to_money(bad)


def test_the_payout_percent_is_rounded_down_and_checked() -> None:
    assert payout_percent(10, 19.5) == 95
    assert payout_percent(10, 18.79) == 87  # 87.9 is never shown as 88
    assert payout_percent("1.00", "1.00") == 0
    with pytest.raises(PayoutSanityError):
        payout_percent(0, 1)
    with pytest.raises(PayoutSanityError):
        payout_percent(10, 25)  # 150 %
    with pytest.raises(PayoutSanityError):
        payout_percent(10, 5)  # a negative payout


def test_a_contract_is_settled_by_status_or_by_being_sold() -> None:
    assert settled_profit({"status": "open", "is_sold": 0, "profit": "0.40"}) is None
    assert settled_profit({"status": "won", "profit": "0.95"}) == D("0.95")
    assert settled_profit({"status": "lost", "profit": "-1.00"}) == D("-1.00")
    assert settled_profit({"is_sold": 1, "profit": "-2.5"}) == D("-2.50")
    assert settled_profit({"status": "sold", "sell_price": "1.20", "buy_price": "1.00"}) == D(
        "0.20"
    )
    with pytest.raises(PayoutSanityError):
        settled_profit({"status": "won"})


def test_errors_are_read_from_the_error_field() -> None:
    assert error_of({"msg_type": "buy", "buy": {}}) is None
    assert error_of({"error": {"code": "InsufficientBalance", "message": "No money."}}) == (
        "InsufficientBalance",
        "No money.",
    )
    assert error_of({"error": {"code": "X"}}) == ("X", "X")
    assert error_of({"error": "plain text"}) == ("Error", "plain text")


def test_demo_and_real_accounts_are_told_apart() -> None:
    assert is_demo_login("VRTC1234") and is_demo_login("vrw99")
    assert not is_demo_login("CR1234") and not is_demo_login("")
    assert is_demo_login("DOT90004580")  # the new Options API's demo numbering
    assert login_kind("DOT90004580") is AccountType.DEMO
    assert login_kind("CR1234") is AccountType.REAL
    assert login_kind("ROT123") is None and login_kind("") is None  # unknown: never guessed
    assert is_demo_account({"account_id": "DOT1"})
    assert is_demo_account({"account_id": "CR1", "account_type": "demo"})  # the field decides
    assert is_demo_account({"account_id": "VRTC1"})
    assert not is_demo_account({"account_id": "CR1"})
    assert is_demo_account({"account_id": "X1", "account_type": "demo"})
    assert not is_demo_account({"account_id": "VRTC1", "account_type": "real"})
    assert is_demo_account({"account_id": "X1", "group": "demo"})


def test_the_socket_link_says_which_account_it_opens() -> None:
    assert (
        socket_kind("wss://api.derivws.com/trading/v1/options/ws/demo?otp=abc") is AccountType.DEMO
    )
    assert (
        socket_kind("wss://api.derivws.com/trading/v1/options/ws/real?otp=abc") is AccountType.REAL
    )
    assert socket_kind("wss://example.com/ws/other?otp=abc") is None


# ---- the early result (decision D-82) --------------------------------------------------------


def _terms(contract_type: str = "CALL", entry: str = "100.00") -> ContractTerms:
    terms = ContractTerms()
    terms.update(
        {
            "contract_type": contract_type,
            "entry_tick": float(entry),
            "date_expiry": 1000,
            "payout": "1.95",
            "buy_price": "1.00",
        }
    )
    return terms


def test_the_terms_are_gathered_from_updates_that_leave_things_out() -> None:
    terms = ContractTerms()
    terms.update({"contract_type": "CALL", "buy_price": 1, "payout": 1.95})
    assert not terms.complete  # no entry tick yet (it comes after the first tick)
    terms.update({"entry_tick": 100.5, "date_expiry": 1000})
    terms.update({"status": "open"})  # an update without them keeps what was known
    assert terms.complete and terms.entry == Decimal("100.5") and terms.expiry == 1000


def test_the_exit_is_the_latest_tick_at_or_before_the_end_once_a_later_one_is_seen() -> None:
    ticks = [(998, Decimal("1")), (999, Decimal("2"))]
    assert exit_quote(ticks, 1000) is None  # a tick at 1000 could still come
    assert exit_quote([*ticks, (1001, Decimal("3"))], 1000) == Decimal("2")
    assert exit_quote([*ticks, (1000, Decimal("4"))], 1000) == Decimal("4")  # exactly at the end
    assert exit_quote([(1001, Decimal("3"))], 1000) is None  # the ticks before were not seen
    assert exit_quote([(1001, Decimal("3")), (999, Decimal("2"))], 1000) == Decimal("2")


def test_rise_and_fall_are_decided_strictly_and_an_equal_exit_loses() -> None:
    assert early_profit(_terms("CALL"), Decimal("100.01")) == Decimal("0.95")
    assert early_profit(_terms("CALL"), Decimal("100.00")) == Decimal("-1.00")
    assert early_profit(_terms("PUT"), Decimal("99.99")) == Decimal("0.95")
    assert early_profit(_terms("PUT"), Decimal("100.00")) == Decimal("-1.00")
    assert early_profit(ContractTerms(), Decimal("1")) is None  # nothing known: no guess


def test_a_tick_message_is_read_or_ignored() -> None:
    assert tick_of({"tick": {"epoch": 5, "quote": 101.25}}) == (5, Decimal("101.25"))
    assert tick_of({"tick": {"epoch": "5", "quote": 1}}) is None
    assert tick_of({"msg_type": "tick"}) is None
