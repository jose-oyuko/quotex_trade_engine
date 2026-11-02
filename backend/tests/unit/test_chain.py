from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.enums import AccountType, ChainStatus, Direction, Strategy
from app.domain.ids import new_id
from app.engine.chain import Chain, ChainSpec, InvalidTransitionError
from app.quotex.base import TradeOutcome
from tests.signal_support import T0

D = Decimal
WON, LOST, DRAW = TradeOutcome.WON, TradeOutcome.LOST, TradeOutcome.DRAW


def make_chain(
    strategy: Strategy = Strategy.FLIP_EVERY_LOSS,
    steps: int = 3,
    origin: Direction = Direction.CALL,
) -> Chain:
    spec = ChainSpec(
        id=new_id(),
        group_id=1,
        signal_id=new_id(),
        asset="EURUSD",
        origin_direction=origin,
        duration_s=60,
        account_type=AccountType.DEMO,
        strategy=strategy,
        base_stake=D("100"),
        multipliers=(D("2.0"), D("2.5"), D("3.0"), D("3.5"))[:steps],
        max_steps=steps,
    )
    return Chain(spec, T0)


def lose(chain: Chain, times: int) -> None:
    for _ in range(times):
        chain.apply_result(LOST, T0)


def test_a_new_chain_is_pending_at_step_zero() -> None:
    chain = make_chain()
    assert (chain.status, chain.step, chain.consecutive_losses) == (ChainStatus.PENDING, 0, 0)
    assert chain.active
    assert chain.plan().stake == D("100")


def test_the_first_confirmed_order_opens_the_chain() -> None:
    chain = make_chain()
    chain.mark_open(T0 + timedelta(seconds=1))
    assert chain.status is ChainStatus.OPEN
    assert chain.updated_at == T0 + timedelta(seconds=1)


@pytest.mark.parametrize("losses", [0, 1, 2, 3])
def test_a_win_at_any_step_completes_the_chain(losses: int) -> None:
    chain = make_chain()
    chain.mark_open(T0)
    lose(chain, losses)
    assert chain.apply_result(WON, T0) is None
    assert chain.status is ChainStatus.COMPLETED
    assert chain.end_reason == f"won at step {losses}"
    assert chain.ended_at == T0
    assert not chain.active


def test_win_at_step_2_of_flip_every_loss_matches_the_document() -> None:
    """CALL 100 (L) -> PUT 200 (L) -> CALL 250 (W) -> completed."""
    chain = make_chain()
    chain.mark_open(T0)
    second = chain.apply_result(LOST, T0)
    assert second is not None and (second.direction, second.stake) == (Direction.PUT, D("200.00"))
    third = chain.apply_result(LOST, T0)
    assert third is not None and (third.direction, third.stake) == (Direction.CALL, D("250.00"))
    assert chain.apply_result(WON, T0) is None
    assert (chain.status, chain.step, chain.consecutive_losses) == (ChainStatus.COMPLETED, 2, 2)


def test_losing_every_trade_exhausts_the_chain_after_the_last_follow_up() -> None:
    chain = make_chain(steps=3)
    chain.mark_open(T0)
    for expected_step in (1, 2, 3):
        plan = chain.apply_result(LOST, T0)
        assert plan is not None and plan.step == expected_step
        assert chain.status is ChainStatus.OPEN
    assert chain.apply_result(LOST, T0) is None
    assert chain.status is ChainStatus.EXHAUSTED
    assert (chain.step, chain.consecutive_losses) == (3, 4)
    assert chain.end_reason == "all 4 trade(s) lost"


def test_no_trade_is_planned_after_the_chain_is_exhausted() -> None:
    chain = make_chain(Strategy.MARTINGALE, steps=2)
    chain.mark_open(T0)
    assert chain.apply_result(LOST, T0) is not None
    assert chain.apply_result(LOST, T0) is not None
    assert chain.apply_result(LOST, T0) is None
    with pytest.raises(InvalidTransitionError, match="already exhausted"):
        chain.apply_result(LOST, T0)


def test_no_martingale_ends_after_one_trade_either_way() -> None:
    lost = make_chain(Strategy.NO_MARTINGALE, steps=0)
    lost.mark_open(T0)
    assert lost.apply_result(LOST, T0) is None and lost.status is ChainStatus.EXHAUSTED
    won = make_chain(Strategy.NO_MARTINGALE, steps=0)
    won.mark_open(T0)
    assert won.apply_result(WON, T0) is None and won.status is ChainStatus.COMPLETED


def test_a_draw_ends_the_chain_because_the_stake_was_refunded() -> None:
    chain = make_chain()
    chain.mark_open(T0)
    lose(chain, 1)
    assert chain.apply_result(DRAW, T0) is None
    assert chain.status is ChainStatus.COMPLETED
    assert chain.end_reason is not None and "draw at step 1" in chain.end_reason


def test_a_refused_order_fails_the_chain() -> None:
    chain = make_chain()
    chain.fail("AssetClosedError: EURUSD is closed", T0)
    assert chain.status is ChainStatus.FAILED
    assert chain.end_reason == "AssetClosedError: EURUSD is closed"


def test_a_follow_up_that_cannot_be_placed_fails_a_running_chain() -> None:
    chain = make_chain()
    chain.mark_open(T0)
    assert chain.apply_result(LOST, T0) is not None
    chain.fail("NotConnectedError", T0)
    assert chain.status is ChainStatus.FAILED and chain.step == 1


def test_an_unclear_outcome_marks_the_chain_unknown() -> None:
    chain = make_chain()
    chain.mark_open(T0)
    chain.mark_unknown("no confirmation", T0)
    assert chain.status is ChainStatus.UNKNOWN


def test_the_owner_can_stop_a_chain() -> None:
    chain = make_chain()
    chain.mark_open(T0)
    chain.stop("stopped by the owner", T0)
    assert chain.status is ChainStatus.STOPPED


@pytest.mark.parametrize("end", ["fail", "mark_unknown", "stop"], ids=["fail", "unknown", "stop"])
def test_an_ended_chain_cannot_be_changed_again(end: str) -> None:
    chain = make_chain()
    chain.apply_result(WON, T0)
    with pytest.raises(InvalidTransitionError):
        getattr(chain, end)("again", T0)
    with pytest.raises(InvalidTransitionError):
        chain.mark_open(T0)


def test_the_record_snapshots_everything_the_database_stores() -> None:
    chain = make_chain(origin=Direction.PUT)
    chain.mark_open(T0)
    lose(chain, 1)
    record = chain.to_record()
    assert (record.id, record.group_id, record.asset) == (chain.id, 1, "EURUSD")
    assert (record.origin_direction, record.duration_s) == (Direction.PUT, 60)
    assert (record.strategy, record.status, record.step) == (
        Strategy.FLIP_EVERY_LOSS,
        ChainStatus.OPEN,
        1,
    )
    assert (record.consecutive_losses, record.max_steps, record.base_stake) == (1, 3, D("100"))
    assert record.multipliers == (D("2.0"), D("2.5"), D("3.0"))
    assert record.account_type is AccountType.DEMO and record.ended_at is None


def test_two_chains_never_share_counters() -> None:
    a, b = make_chain(), make_chain()
    lose(a, 2)
    assert (a.consecutive_losses, b.consecutive_losses) == (2, 0)
    assert b.plan().stake == D("100")
