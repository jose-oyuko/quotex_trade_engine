from decimal import Decimal
from typing import ClassVar

import pytest

from app.domain.enums import AccountType
from app.quotex.backoff import BackoffPolicy, backoff_delay
from app.quotex.errors import PayoutSanityError
from app.quotex.parsing import (
    balance_from_payload,
    find_instrument,
    instrument_is_open,
    instrument_payout,
    profit_from_number,
)
from tests.quotex_support import make_row


class TestInstrumentPayout:
    def test_one_minute_and_five_minute_figures(self) -> None:
        row = make_row("EURUSD", payout_1m=86, payout_5m=82)
        assert instrument_payout(row, 1) == 86
        assert instrument_payout(row, 4) == 86
        assert instrument_payout(row, 5) == 82
        assert instrument_payout(row, 15) == 82

    @pytest.mark.parametrize("value", [0, 100, 87.4, 87.6])
    def test_values_inside_the_range_are_accepted_and_rounded(self, value: float) -> None:
        assert instrument_payout(make_row("X", payout_1m=value), 1) == round(value)

    @pytest.mark.parametrize("value", [-1, 100.5, 101, 8700, None, "85", True, float("nan")])
    def test_values_outside_the_range_or_not_numbers_fail_loudly(self, value: object) -> None:
        with pytest.raises(PayoutSanityError):
            instrument_payout(make_row("X", payout_1m=value), 1)

    def test_a_row_with_the_wrong_layout_fails_loudly(self) -> None:
        with pytest.raises(PayoutSanityError, match="layout"):
            instrument_payout(["id", "EURUSD", "EUR/USD", 1, 2], 1)


class TestInstrumentLookup:
    def test_find_and_open_flag(self) -> None:
        rows = [make_row("EURUSD"), make_row("AUDUSD", is_open=False)]
        found = find_instrument(rows, "AUDUSD")
        assert found is not None
        assert instrument_is_open(found) is False
        assert find_instrument(rows, "NOPE") is None

    def test_short_rows_are_skipped_not_crashed_on_lookup(self) -> None:
        assert find_instrument([[1], []], "EURUSD") is None


class TestBalance:
    PAYLOAD: ClassVar[dict[str, object]] = {"demoBalance": 10000.559, "liveBalance": "25.5"}

    def test_demo_and_real_keys(self) -> None:
        assert balance_from_payload(self.PAYLOAD, AccountType.DEMO) == Decimal("10000.55")
        assert balance_from_payload(self.PAYLOAD, AccountType.REAL) == Decimal("25.50")

    @pytest.mark.parametrize("payload", [None, {}, {"demoBalance": None}, {"demoBalance": True}])
    def test_missing_or_garbage_gives_none(self, payload: dict | None) -> None:  # type: ignore[type-arg]
        assert balance_from_payload(payload, AccountType.DEMO) is None


class TestProfit:
    def test_numbers_become_two_decimal_decimals(self) -> None:
        assert profit_from_number(0.85) == Decimal("0.85")
        assert profit_from_number(-1) == Decimal("-1.00")
        assert profit_from_number("2.5") == Decimal("2.50")

    @pytest.mark.parametrize("value", [None, True, [], "abc"])
    def test_non_numbers_fail_loudly(self, value: object) -> None:
        with pytest.raises(PayoutSanityError):
            profit_from_number(value)


class TestBackoff:
    POLICY = BackoffPolicy(base_s=1.0, cap_s=30.0, jitter=0.1)

    def test_delay_doubles_until_the_cap(self) -> None:
        delays = [backoff_delay(n, self.POLICY, lambda: 0.5) for n in range(8)]
        assert delays == [1, 2, 4, 8, 16, 30, 30, 30]

    def test_jitter_stays_within_ten_percent(self) -> None:
        low = backoff_delay(2, self.POLICY, lambda: 0.0)
        high = backoff_delay(2, self.POLICY, lambda: 0.999999)
        assert low == pytest.approx(3.6)
        assert high == pytest.approx(4.4, abs=1e-3)

    @pytest.mark.parametrize(
        "kwargs", [{"base_s": 0}, {"base_s": 5, "cap_s": 1}, {"jitter": 1.0}, {"jitter": -0.1}]
    )
    def test_invalid_policies_are_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="invalid backoff"):
            BackoffPolicy(**kwargs)
