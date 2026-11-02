"""How much time the engine itself adds between a signal and the order (docs/PHASES.md Phase 4).

The bounds are deliberately loose so the test is not flaky on a busy machine; the real figures
(median and 99th percentile, printed with `-s`) are in the phase report. Quotex's own network time
is not part of this: the fake adapter answers at once.
"""

from __future__ import annotations

import statistics

import pytest

from tests.engine_support import measure_latency

COUNT = 300


def summary(samples: list[int]) -> tuple[float, float, float]:
    ordered = sorted(samples)
    return (
        statistics.median(ordered) / 1000,
        ordered[int(len(ordered) * 0.99)] / 1000,
        ordered[-1] / 1000,
    )


@pytest.mark.parametrize("through_parser", [False, True], ids=["engine-only", "message-to-order"])
async def test_the_engines_own_overhead_is_microseconds(through_parser: bool) -> None:
    samples = await measure_latency(COUNT, through_parser=through_parser)
    median_us, p99_us, worst_us = summary(samples)
    label = "message -> place_order" if through_parser else "signal -> place_order"
    print(
        f"\n{label} ({COUNT} signals): median {median_us:.0f} us, "
        f"p99 {p99_us:.0f} us, worst {worst_us:.0f} us"
    )
    assert len(samples) == COUNT
    assert median_us < 2_000  # 2 ms
    assert p99_us < 10_000  # 10 ms
