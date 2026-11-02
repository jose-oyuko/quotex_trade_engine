from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects import sqlite

from app.db.types import DecimalList, Money, UTCDateTime

DIALECT = sqlite.dialect()


class TestMoney:
    def test_stored_as_integer_cents(self) -> None:
        assert Money().process_bind_param(Decimal("12.34"), DIALECT) == 1234

    def test_roundtrip_is_exact(self) -> None:
        for text in ["0.01", "1.00", "2.50", "123456.78", "-4.20"]:
            minor = Money().process_bind_param(Decimal(text), DIALECT)
            assert Money().process_result_value(minor, DIALECT) == Decimal(text)

    def test_float_is_refused(self) -> None:
        with pytest.raises(TypeError, match="Decimal"):
            Money().process_bind_param(1.5, DIALECT)  # type: ignore[arg-type]

    def test_more_than_two_decimals_is_refused(self) -> None:
        with pytest.raises(ValueError, match="2 decimal places"):
            Money().process_bind_param(Decimal("3.375"), DIALECT)

    def test_trailing_zeros_beyond_two_decimals_are_fine(self) -> None:
        assert Money().process_bind_param(Decimal("2.500"), DIALECT) == 250

    def test_none_passes_through(self) -> None:
        assert Money().process_bind_param(None, DIALECT) is None
        assert Money().process_result_value(None, DIALECT) is None


class TestUTCDateTime:
    def test_naive_datetime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            UTCDateTime().process_bind_param(datetime(2026, 11, 1, 12, 0), DIALECT)

    def test_other_zones_are_converted_to_utc(self) -> None:
        plus_three = timezone(timedelta(hours=3))
        stored = UTCDateTime().process_bind_param(
            datetime(2026, 11, 1, 15, 0, tzinfo=plus_three), DIALECT
        )
        assert stored == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    def test_result_gets_utc_back(self) -> None:
        result = UTCDateTime().process_result_value(datetime(2026, 11, 1, 12, 0), DIALECT)
        assert result == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        assert result is not None and result.tzinfo is UTC


def test_decimal_list_roundtrip_keeps_exact_values() -> None:
    values = (Decimal("2.0"), Decimal("2.5"), Decimal("0.1"))
    stored = DecimalList().process_bind_param(values, DIALECT)
    assert stored == ["2.0", "2.5", "0.1"]
    assert DecimalList().process_result_value(stored, DIALECT) == values
