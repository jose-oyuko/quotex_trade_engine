"""Consolidations, breakouts and trends on hand-made candles (decision D-85).

The letters make candles one minute apart: `U` a buy candle and `D` a sell candle, both between
99.5 and 101.5; `E` an equal candle; `B` a candle closing above 101.5 and `b` one closing below
99.5; `T` reaches above 101.5 but closes inside; `-` is a minute without prices.
"""

from __future__ import annotations

import random

import pytest

from app.market.candles import Candle
from app.market.detector import (
    BreakBy,
    Detector,
    Found,
    MarketRules,
    Pattern,
    scan,
)

T0 = 1_700_000_040  # a minute boundary
M1 = 60
SHAPES = {
    "U": (100.0, 101.5, 99.5, 101.0),
    "D": (101.0, 101.5, 99.5, 100.0),
    "E": (100.5, 101.0, 100.0, 100.5),
    "B": (101.0, 102.5, 100.8, 102.0),
    "b": (100.0, 100.2, 98.5, 99.0),
    "T": (100.5, 102.0, 100.0, 101.0),
}
ALTERNATING = MarketRules()


def bars(text: str) -> list[Candle]:
    found = []
    for i, letter in enumerate(text.replace(" ", "")):
        if letter != "-":
            o, h, low, c = SHAPES[letter]
            found.append(Candle(T0 + i * M1, o, h, low, c, 60))
    return found


def at(i: int) -> int:
    return T0 + i * M1


def run(text: str, rules: MarketRules = ALTERNATING) -> Found:
    return scan(bars(text), rules, M1)


def test_five_alternating_candles_make_a_consolidation_and_four_do_not() -> None:
    assert run("UUDUDD").consolidations == []  # four alternate, then the run stops
    (cons,) = run("UDUDU").consolidations
    assert (cons.first, cons.found, cons.end) == (at(0), at(5), at(5))
    assert (cons.high, cons.low) == (101.5, 99.5)
    assert cons.breakout is None and cons.ended == "end"
    (mirror,) = run("DUDUD").consolidations
    assert mirror.first == at(0) and mirror.found == at(5)


def test_an_equal_candle_ends_an_alternating_run() -> None:
    assert run("UDEUDUD").consolidations == []
    (cons,) = run("UDEUDUDU").consolidations
    assert cons.first == at(3)


def test_the_range_is_the_lowest_low_and_highest_high() -> None:
    candles = bars("UDUDU")
    candles[1] = Candle(at(1), 101.0, 103.0, 99.5, 100.0, 60)
    candles[3] = Candle(at(3), 101.0, 101.5, 97.0, 100.0, 60)
    (cons,) = scan(candles, ALTERNATING, M1).consolidations
    assert (cons.high, cons.low) == (103.0, 97.0)


def test_the_range_grows_while_the_candles_go_on_alternating() -> None:
    candles = [*bars("UDUDU"), Candle(at(5), 101.0, 101.5, 98.0, 100.0, 60)]
    (cons,) = scan(candles, ALTERNATING, M1).consolidations
    assert cons.low == 98.0 and cons.end == at(6)


def test_two_closes_above_the_high_make_an_up_breakout_and_one_does_not() -> None:
    (cons,) = run("UDUDU B U").consolidations  # one close above, then back inside
    assert cons.breakout is None
    (cons,) = run("UDUDU B U BB U").consolidations
    breakout = cons.breakout
    assert breakout is not None
    assert (breakout.start, breakout.known) == (at(7), at(9))
    assert (breakout.direction, breakout.level, breakout.close) == ("up", 101.5, 102.0)
    assert cons.end == at(7) and cons.ended == "breakout"


def test_two_closes_below_the_low_make_a_down_breakout() -> None:
    (cons,) = run("UDUDU bb").consolidations
    assert cons.breakout is not None
    assert (cons.breakout.direction, cons.breakout.level) == ("down", 99.5)


def test_one_breakout_candle_can_be_enough() -> None:
    rules = MarketRules(breakout_candles=1)
    (cons,) = run("UDUDU B", rules).consolidations
    assert cons.breakout is not None and cons.breakout.known == at(6)


def test_touch_counts_any_part_beyond_the_range_and_close_does_not() -> None:
    (by_close,) = run("UDUDU TT").consolidations
    assert by_close.breakout is None
    (by_touch,) = run("UDUDU TT", MarketRules(breakout_by=BreakBy.TOUCH)).consolidations
    assert by_touch.breakout is not None and by_touch.breakout.direction == "up"
    both_sides = [*bars("UDUDU"), *[Candle(at(i), 100.0, 103.0, 97.0, 100.5, 60) for i in (5, 6)]]
    (wide,) = scan(both_sides, MarketRules(breakout_by=BreakBy.TOUCH), M1).consolidations
    assert wide.breakout is None


def test_candles_that_stop_alternating_but_stay_inside_still_belong_to_it() -> None:
    (cons,) = run("UDUDU UU BB").consolidations
    assert (cons.first, cons.end) == (at(0), at(7))


def test_a_trend_runs_from_the_breakout_to_the_next_consolidation() -> None:
    found = run("UDUDU BB UUU UDUDU")
    _, second = found.consolidations
    (trend,) = found.trends
    assert (trend.start, trend.end, trend.stopped) == (at(7), at(10), at(15))
    assert (trend.direction, trend.ended) == ("up", "consolidation")
    assert (trend.open, trend.close) == (102.0, 100.0)  # the breakout's close, then the next open
    assert trend.move == -2.0
    assert (second.first, second.found) == (at(10), at(15))


def test_the_next_consolidation_is_made_of_candles_after_the_breakout() -> None:
    # D B D B U: alternates across the breakout, but only "D U D U D" after it counts
    found = run("UDUDU BB DUDUD")
    assert [c.first for c in found.consolidations] == [at(0), at(7)]
    assert found.trends[0].end == found.trends[0].start == at(7)


def test_a_gap_ends_whatever_was_going_on() -> None:
    assert run("UD-UDU").consolidations == []  # no run across a gap
    (cons,) = run("UDUDU U-UDUDU").consolidations[:1]
    assert (cons.ended, cons.end) == ("gap", at(6))
    found = run("UDUDU BB UU-U")
    (trend,) = found.trends
    assert (trend.ended, trend.end, trend.stopped) == ("gap", at(9), at(9))
    assert trend.close == 101.0


def test_what_is_still_going_on_at_the_end_is_closed_as_end() -> None:
    found = run("UDUDU BB UU")
    (trend,) = found.trends
    assert (trend.ended, trend.end) == ("end", at(9))


def test_feeding_candles_one_at_a_time_never_changes_what_was_decided() -> None:
    rng = random.Random(7)  # noqa: S311 - made-up prices, not secrets
    candles, price = [], 100.0
    for i in range(1500):
        o = price
        price += rng.choice((-1, 1)) * rng.uniform(0.1, 1.0)
        candles.append(Candle(T0 + i * M1, o, max(o, price) + 0.2, min(o, price) - 0.2, price, 60))
    for rules in (ALTERNATING, MarketRules(Pattern.CHOPPY, candles=10)):
        full = scan(candles, rules, M1)
        assert len(full.consolidations) > 10 and len(full.trends) > 10
        detector = Detector(rules, M1)
        for k, candle in enumerate(candles):
            detector.feed(candle)
            if k % 97:
                continue
            # what was closed so far is exactly the start of what the whole period finds
            closed = detector.found
            assert closed.consolidations == full.consolidations[: len(closed.consolidations)]
            assert closed.trends == full.trends[: len(closed.trends)]


def test_the_mixed_pattern_lets_one_candle_not_alternate() -> None:
    assert run("UDUUDU").consolidations == []
    (cons,) = run("UDUUDU", MarketRules(Pattern.MIXED, candles=6, misses=1)).consolidations
    assert cons.first == at(0)
    assert run("UUDDUU", MarketRules(Pattern.MIXED, candles=6, misses=1)).consolidations == []


def test_the_tight_pattern_compares_the_range_with_the_average_candle() -> None:
    wide = [Candle(at(i), 100.0, 102.0, 98.0, 101.0, 60) for i in range(30)]  # size 4
    narrow = [Candle(at(30 + i), 100.0, 101.0, 99.0, 100.5, 60) for i in range(8)]  # span 2
    rules = MarketRules(Pattern.TIGHT, candles=8, width=0.6)
    (cons,) = scan(wide + narrow, rules, M1).consolidations
    assert (cons.first, cons.found) == (at(30), at(38))
    assert (
        scan(wide + narrow, MarketRules(Pattern.TIGHT, candles=8, width=0.4), M1).consolidations
        == []
    )
    assert scan(narrow, rules, M1).consolidations == []  # no average to compare with yet


def test_the_overlap_pattern_needs_each_body_inside_the_candle_before() -> None:
    inside = [Candle(at(i), 100.0, 102.0, 98.0, 101.0, 60) for i in range(4)]
    (cons,) = scan(inside, MarketRules(Pattern.OVERLAP, candles=4), M1).consolidations
    assert cons.first == at(0)
    climbing = [Candle(at(i), 100.0 + i, 102.0 + i, 99.0 + i, 101.5 + i, 60) for i in range(4)]
    assert scan(climbing, MarketRules(Pattern.OVERLAP, candles=4), M1).consolidations == []


def test_the_choppy_pattern_compares_the_net_move_with_all_the_moves() -> None:
    rules = MarketRules(Pattern.CHOPPY, candles=6, net_share=0.2)
    assert len(run("UDUDUD", rules).consolidations) == 1  # net 0 of 6
    rising = [Candle(at(i), 100.0 + i, 101.5 + i, 99.5 + i, 101.0 + i, 60) for i in range(5)]
    falling = Candle(at(5), 105.0, 105.5, 103.5, 104.0, 60)
    assert scan([*rising, falling], rules, M1).consolidations == []  # net 4 of 6


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"candles": 1}, "2 to 50 candles"),
        ({"breakout_candles": 0}, "1 to 10 candles"),
        ({"pattern": Pattern.MIXED, "candles": 5, "misses": 4}, "0 to 3 misses"),
        ({"pattern": Pattern.TIGHT, "width": 0}, "width above 0"),
        ({"pattern": Pattern.CHOPPY, "net_share": 1.0}, "between 0 and 1"),
    ],
)
def test_rules_out_of_bounds_are_refused(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MarketRules(**changes)  # type: ignore[arg-type]


def test_candles_must_come_in_time_order() -> None:
    detector = Detector(ALTERNATING, M1)
    first, second = bars("UD")
    detector.feed(second)
    with pytest.raises(ValueError, match="time order"):
        detector.feed(first)
    detector.finish()
    with pytest.raises(RuntimeError, match="finished"):
        detector.feed(second)
    assert detector.state == "searching"
