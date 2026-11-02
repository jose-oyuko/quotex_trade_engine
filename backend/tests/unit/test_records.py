from decimal import Decimal

import pytest

from tests.factories import make_settings


def test_valid_settings_are_accepted() -> None:
    settings = make_settings(1)
    assert settings.max_steps == len(settings.multipliers) == 3


def test_zero_steps_means_no_multipliers() -> None:
    settings = make_settings(1, max_steps=0, multipliers=())
    assert settings.multipliers == ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"base_stake": Decimal("0")}, "base_stake"),
        ({"max_steps": -1, "multipliers": ()}, "max_steps"),
        ({"max_steps": 4}, "one multiplier per step"),
        ({"max_steps": 2}, "one multiplier per step"),
        ({"multipliers": (Decimal("2"), Decimal("0"), Decimal("3"))}, "multiplier"),
        ({"min_payout_pct": 101}, "min_payout_pct"),
        ({"min_payout_pct": -1}, "min_payout_pct"),
    ],
)
def test_invalid_settings_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_settings(1, **overrides)
