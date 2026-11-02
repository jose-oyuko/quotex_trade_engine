"""The strategy tables of docs/DOMAIN.md section 2. Test names follow the document's examples."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.enums import Direction, Strategy
from app.engine.strategies import (
    FLIP_STRATEGIES,
    StepPlan,
    flipped,
    has_follow_up,
    max_trades,
    plan_step,
    step_stake,
)

CALL, PUT = Direction.CALL, Direction.PUT
D = Decimal
BASE = D("100")
MULTS = (D("2.0"), D("2.5"), D("3.0"))


def table(strategy: Strategy, steps: int, origin: Direction = CALL) -> list[tuple[str, str]]:
    """(direction, stake) for step 0..steps, as the plain strings of the document's tables."""
    plans = [plan_step(strategy, k, origin, BASE, MULTS) for k in range(steps + 1)]
    return [(p.direction.value, format(p.stake.normalize(), "f")) for p in plans]


# --- worked examples (base 100, N = 3, multipliers [2.0, 2.5, 3.0], origin CALL, all lose) ---


def test_worked_example_flip_every_loss() -> None:
    assert table(Strategy.FLIP_EVERY_LOSS, 3) == [
        ("call", "100"),
        ("put", "200"),
        ("call", "250"),
        ("put", "300"),
    ]


def test_worked_example_two_step_flip() -> None:
    assert table(Strategy.TWO_STEP_FLIP, 3) == [
        ("call", "100"),
        ("call", "200"),
        ("put", "250"),
        ("put", "300"),
    ]


def test_worked_example_two_step_flip_with_n_4_the_next_would_be_call() -> None:
    mults = (*MULTS, D("4.0"))
    plan = plan_step(Strategy.TWO_STEP_FLIP, 4, CALL, BASE, mults)
    assert plan == StepPlan(4, CALL, D("400.00"))


def test_worked_example_martingale() -> None:
    assert table(Strategy.MARTINGALE, 3) == [
        ("call", "100"),
        ("call", "200"),
        ("call", "250"),
        ("call", "300"),
    ]


def test_no_martingale_is_always_the_base_stake_and_has_no_follow_ups() -> None:
    assert table(Strategy.NO_MARTINGALE, 0) == [("call", "100")]
    assert has_follow_up(Strategy.NO_MARTINGALE, 0, 3) is False
    assert max_trades(Strategy.NO_MARTINGALE, 3) == 1


# --- shape of longer chains (an 8-step chain needs eight multipliers) ---


def test_flip_every_loss_alternates_all_the_way() -> None:
    mults = tuple(D(2) for _ in range(8))
    directions = [
        plan_step(Strategy.FLIP_EVERY_LOSS, k, CALL, BASE, mults).direction for k in range(9)
    ]
    assert directions == [CALL, PUT, CALL, PUT, CALL, PUT, CALL, PUT, CALL]


def test_two_step_flip_goes_in_pairs_all_the_way() -> None:
    mults = tuple(D(2) for _ in range(8))
    directions = [
        plan_step(Strategy.TWO_STEP_FLIP, k, CALL, BASE, mults).direction for k in range(9)
    ]
    assert directions == [CALL, CALL, PUT, PUT, CALL, CALL, PUT, PUT, CALL]


@pytest.mark.parametrize("strategy", list(Strategy))
def test_a_put_signal_mirrors_a_call_signal(strategy: Strategy) -> None:
    mirror = [
        (flipped(a.direction), a.stake)
        for a in (plan_step(strategy, k, CALL, BASE, MULTS) for k in range(4))
    ]
    actual = [
        (p.direction, p.stake) for p in (plan_step(strategy, k, PUT, BASE, MULTS) for k in range(4))
    ]
    assert actual == mirror


# --- chain length: original + N follow-ups for every multiplier strategy (D-8) ---


@pytest.mark.parametrize(
    "strategy", [Strategy.MARTINGALE, Strategy.FLIP_EVERY_LOSS, Strategy.TWO_STEP_FLIP]
)
def test_the_chain_is_the_original_plus_n_follow_ups(strategy: Strategy) -> None:
    assert max_trades(strategy, 3) == 4
    assert [has_follow_up(strategy, k, 3) for k in range(5)] == [True, True, True, False, False]


def test_the_legacy_martingale_one_trade_short_quirk_is_gone() -> None:
    """The old bot's plain martingale stopped after `max` losses (docs/DOMAIN.md section 2 note)."""
    assert max_trades(Strategy.MARTINGALE, 3) == max_trades(Strategy.FLIP_EVERY_LOSS, 3)


def test_only_the_flip_strategies_block_new_signals() -> None:
    assert {Strategy.FLIP_EVERY_LOSS, Strategy.TWO_STEP_FLIP} == FLIP_STRATEGIES


# --- stakes ---


def test_step_zero_is_exactly_the_base_stake() -> None:
    assert step_stake(0, D("1.25"), ()) == D("1.25")


@pytest.mark.parametrize(
    ("base", "multiplier", "expected"),
    [
        ("1.00", "2.5", "2.50"),
        ("1.10", "1.5", "1.65"),
        ("0.33", "2.5", "0.83"),  # 0.825 rounds half up
        ("0.35", "2.5", "0.88"),  # 0.875 rounds half up
        ("1.00", "2.333", "2.33"),
        ("10.00", "0.5", "5.00"),
    ],
)
def test_stakes_are_rounded_to_the_cent_half_up(base: str, multiplier: str, expected: str) -> None:
    assert step_stake(1, D(base), (D(multiplier),)) == D(expected)


def test_a_stake_that_rounds_to_nothing_is_refused_not_sent() -> None:
    with pytest.raises(ValueError, match=r"rounds to 0\.00"):
        step_stake(1, D("0.01"), (D("0.1"),))


def test_a_missing_multiplier_is_an_error_never_a_reused_one() -> None:
    with pytest.raises(ValueError, match="no multiplier for step 3"):
        step_stake(3, BASE, (D(2), D(3)))
