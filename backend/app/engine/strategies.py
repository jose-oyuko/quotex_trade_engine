"""The four strategies as pure functions (docs/DOMAIN.md section 2). No state, no I/O.

`k` is the number of consecutive losses so far, which is also the index of the follow-up being
planned: step 0 is the original signal trade, step k the k-th follow-up. Multiplier `m_k` is the
k-th entry of the group's list (1-based), so `multipliers[k - 1]`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.enums import Direction, Strategy

CENT = Decimal("0.01")

# While a chain of one of these is running, new signals of the same group are ignored (D-9).
FLIP_STRATEGIES = frozenset({Strategy.FLIP_EVERY_LOSS, Strategy.TWO_STEP_FLIP})


@dataclass(slots=True, frozen=True)
class StepPlan:
    """What to trade at one step."""

    step: int
    direction: Direction
    stake: Decimal


def flipped(direction: Direction) -> Direction:
    return Direction.PUT if direction is Direction.CALL else Direction.CALL


def has_follow_up(strategy: Strategy, step: int, max_steps: int) -> bool:
    """Is there a step after `step`? Every multiplier strategy allows the original trade plus
    `max_steps` follow-ups; `no_martingale` never has any."""
    return strategy is not Strategy.NO_MARTINGALE and step < max_steps


def max_trades(strategy: Strategy, max_steps: int) -> int:
    return 1 if strategy is Strategy.NO_MARTINGALE else max_steps + 1


def step_direction(strategy: Strategy, step: int, origin: Direction) -> Direction:
    if step == 0 or strategy in (Strategy.NO_MARTINGALE, Strategy.MARTINGALE):
        return origin
    if strategy is Strategy.FLIP_EVERY_LOSS:
        return flipped(origin) if step % 2 == 1 else origin
    # TWO_STEP_FLIP: origin, origin, flipped, flipped, origin, origin, ...
    return flipped(origin) if (step // 2) % 2 == 1 else origin


def step_stake(step: int, base: Decimal, multipliers: Sequence[Decimal]) -> Decimal:
    """`base` for step 0, `base * m_k` rounded to the cent (half up) for follow-up k.

    Rounding is explicit here because the storage layer refuses more than two decimals (D-22)
    instead of rounding silently.
    """
    if step == 0:
        return base
    if step > len(multipliers):
        raise ValueError(f"no multiplier for step {step}: only {len(multipliers)} configured")
    stake = (base * multipliers[step - 1]).quantize(CENT, rounding=ROUND_HALF_UP)
    if stake <= 0:
        raise ValueError(f"stake for step {step} rounds to {stake}: base or multiplier too small")
    return stake


def plan_step(
    strategy: Strategy,
    step: int,
    origin: Direction,
    base: Decimal,
    multipliers: Sequence[Decimal],
) -> StepPlan:
    return StepPlan(
        step=step,
        direction=step_direction(strategy, step, origin),
        stake=step_stake(step, base, multipliers),
    )
