"""Expected against actual: when does the report say a win rate is better (or worse) than chance?"""

from __future__ import annotations

import pytest

from app.reports.models import SAMPLE_SMALL, SAMPLE_TINY, Metrics, expectation_of, sample_of

# 100 trades at an 85% payout: break-even is 1/1.85 = 54.05% and one standard error is
# sqrt(0.5405 x 0.4595 / 100) = 4.98 points, so the verdict changes at about 64% and 44%.


@pytest.mark.parametrize(
    ("wins", "losses", "verdict"),
    [
        (54, 46, "consistent_with_break_even"),  # right on the line
        (60, 40, "consistent_with_break_even"),  # z = 1.2: a good run, still luck-sized
        (63, 37, "consistent_with_break_even"),  # z = 1.8
        (65, 35, "above_break_even"),  # z = 2.2
        (48, 52, "consistent_with_break_even"),  # z = -1.2
        (44, 56, "below_break_even"),  # z = -2.0 or beyond
        (30, 70, "below_break_even"),
    ],
)
def test_the_verdict_changes_only_beyond_two_standard_errors(
    wins: int, losses: int, verdict: str
) -> None:
    assert expectation_of(wins, losses, 85.0).verdict == verdict


def test_the_numbers_behind_the_verdict() -> None:
    e = expectation_of(65, 35, 85.0)
    assert e.breakeven_win_rate == pytest.approx(0.54054, abs=1e-4)
    assert e.actual_win_rate == pytest.approx(0.65)
    assert e.edge == pytest.approx(0.10946, abs=1e-4)
    assert e.z_score == pytest.approx(2.197, abs=1e-2)


def test_a_higher_payout_lowers_the_bar_and_a_lower_one_raises_it() -> None:
    assert expectation_of(50, 50, 100.0).breakeven_win_rate == pytest.approx(0.5)
    assert expectation_of(50, 50, 70.0).breakeven_win_rate == pytest.approx(1 / 1.7)


@pytest.mark.parametrize("trades", [1, 9, 29])
def test_a_short_record_is_never_a_verdict_however_extreme(trades: int) -> None:
    assert expectation_of(trades, 0, 85.0).verdict == "not_enough_data"
    assert expectation_of(0, trades, 85.0).verdict == "not_enough_data"
    assert expectation_of(trades, 0, 85.0).z_score is not None  # the number is still shown


def test_the_thirtieth_trade_is_the_first_that_can_count() -> None:
    assert expectation_of(30, 0, 85.0).verdict == "above_break_even"


@pytest.mark.parametrize(("wins", "losses", "payout"), [(0, 0, 85.0), (5, 5, None), (5, 5, 0.0)])
def test_nothing_to_compare_gives_no_numbers(wins: int, losses: int, payout: float | None) -> None:
    e = expectation_of(wins, losses, payout)
    assert (e.breakeven_win_rate, e.z_score, e.verdict) == (None, None, "not_enough_data")


def test_the_sample_labels_change_at_ten_and_thirty() -> None:
    assert [
        sample_of(n) for n in (0, SAMPLE_TINY - 1, SAMPLE_TINY, SAMPLE_SMALL - 1, SAMPLE_SMALL)
    ] == [
        "tiny",
        "tiny",
        "small",
        "small",
        "ok",
    ]
    assert (SAMPLE_TINY, SAMPLE_SMALL) == (10, 30)  # the dashboard and docs repeat these


def test_the_ratios_have_sensible_edges() -> None:
    from decimal import Decimal

    none = Metrics(0, 0, 0, 0, Decimal(0), Decimal(0), None)
    assert (none.win_rate, none.roi, none.avg_stake) == (None, None, None)
    some = Metrics(4, 3, 1, 0, Decimal("2.00"), Decimal("8.00"), 80.0)
    assert (some.win_rate, some.roi, some.avg_stake) == (0.75, 0.25, Decimal("2.00"))
