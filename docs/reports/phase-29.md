# Phase 29 — Candles, the consolidation detector and its statistics — Report

**Date:** 2026-11-20
**Status:** Done. The first real answer is in section 8: on two separate weeks of Volatility 75 (1s), M1
and M5, the stretch after a breakout is no calmer than any other moment.

## 1. Summary

The engine can now find consolidations, breakouts and trends in the stored Deriv prices, on candles of any
length.
- **One detector** (`app/market/`) reads candles one at a time and never looks ahead. The Market page
  (Phase 30), the trend backtests (Phase 31) and a live engine (Phase 32) would all use this same code.
- **Five patterns** of "consolidation" can be chosen, as you asked (section 8 compares them):
  - your alternating candles;
  - "mixed" (one candle may not alternate);
  - "tight" (a narrow range);
  - "overlap" (each candle inside the one before);
  - "choppy" (lots of movement, little net progress).
- **Statistics** answer your question with fair comparisons and a 95% range on every figure:
  - how long trends last after a breakout, against the same from any moment;
  - whether the breakout's direction goes on;
  - how many flip pairs go deep while trending, against any time.
- **`npm run market:scan`** prints all of it in the terminal; `--compare` puts the patterns side by
  side.
- **The API** (`/api/v1/market/...`) serves candles for the chart and scans for the Market page.

## 2. What was done

- **New, pure code** (`backend/app/market/`):
  - `candles.py`: candles of any length from prices, aligned like session candles; a period without
    prices stays a gap;
  - `detector.py`: the five patterns, the range, the breakout (`close` or `touch`, 1 to 10 candles) and
    the trend, one candle at a time;
  - `stats.py`: trend waits against any moment, the breakout's direction, deep flip pairs (counted from
    candle colours), how well a pattern describes the deep stretches, and a pattern comparison.
- **New service** `app/services/market.py`: loads the stored prices and scans in a worker thread. It
  also sets the limits: 5,000 candles per chart request, and 31 days or 200,000 candles per scan.
- **New API:**
  - `app/api/routers/market.py`, `app/api/schemas/market.py`: `GET /market/candles`,
    `GET /market/patterns`, `POST /market/scan`;
  - error `invalid_market` (422).
- **New script:** `scripts/market_scan.py` (`npm run market:scan`).
- **Wiring:** `main.py`, `deps.py`, `errors.py`; `docs/openapi.json` and `frontend/src/api/schema.d.ts`
  regenerated.
- **Architecture rule:** `app/market` imports nothing above it, not even the backtests.
- **Docs:** DOMAIN section 9 (the definitions and the statistics), API, OPERATIONS ("Consolidations and
  trends"), ARCHITECTURE, PHASES/DECISIONS (D-85, with your 2026-11-20 answers).
- **Data:** a second week of Volatility 75 (1s) was downloaded from Deriv's public price service (no
  login): 29 Oct to 5 Nov, 604,332 prices, for the second-period check.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| 5 alternating candles make a consolidation, 4 do not | ✅ | `test_five_alternating_candles_make_a_consolidation_and_four_do_not` |
| An equal candle ends the run | ✅ | `test_an_equal_candle_ends_an_alternating_run` |
| The range is the lowest low and highest high | ✅ | `test_the_range_is_the_lowest_low_and_highest_high`, `..._grows_while_the_candles_go_on_alternating` |
| 2 closes above the high make an up breakout, 1 does not | ✅ | `test_two_closes_above_the_high_make_an_up_breakout_and_one_does_not`, `..._down_breakout`, `test_one_breakout_candle_can_be_enough` |
| `touch` against `close` | ✅ | `test_touch_counts_any_part_beyond_the_range_and_close_does_not` |
| Candles inside the range after the alternation stay in it | ✅ | `test_candles_that_stop_alternating_but_stay_inside_still_belong_to_it` |
| A trend ends where the next consolidation starts | ✅ | `test_a_trend_runs_from_the_breakout_to_the_next_consolidation`, `test_the_next_consolidation_is_made_of_candles_after_the_breakout` |
| A gap ends any run | ✅ | `test_a_gap_ends_whatever_was_going_on` |
| Candles from prices: M1/M5 boundaries, open/close, gaps | ✅ | `test_market_candles.py` (4 tests) |
| Never looks ahead | ✅ | `test_feeding_candles_one_at_a_time_never_changes_what_was_decided` (1,500 random candles, two patterns) |
| Statistics on candles with a known answer; the random-moment comparison | ✅ | `test_market_stats.py` (5 tests) |
| The other patterns (added on your request) | ✅ | `test_the_mixed_pattern_...`, `..._tight_...`, `..._overlap_...`, `..._choppy_...`, `test_rules_out_of_bounds_are_refused` |
| API tests | ✅ | `test_api_market.py` (3 tests); `test_market_scan_script.py` (3 tests) |
| `ruff`, `mypy`, the whole suite | ✅ | Section 4 |
| Run on two weeks of Volatility 75 (1s), M1 and M5 | ✅ | Section 8 |

## 4. Checks run

```
$ uv run ruff check . ; uv run ruff format --check .     All checks passed; 326 files already formatted
$ uv run mypy                                           Success: no issues found in 171 source files
$ uv run pytest -q                                      1645 passed, 2 failed (11 min)
    test_openapi: had loaded before the 3 new routes were added to its list
    test_reports_performance: the known timing test, slow under the full run
$ (those two, and test_api_auth, again on their own)    39 passed
$ npm run api:check ; npm --prefix frontend run typecheck   up to date; clean
$ npm run api:generate                                  openapi.json and schema.d.ts regenerated
```

## 5. Challenges and how they were resolved

1. **A breakout candle that still alternates.**
   - In "buy, sell, buy, sell, buy, then two sells closing below the range", the first sell still
     alternated with the buy before it. So the first version counted it as "still consolidating",
     widened the range to it, and never saw the breakout.
   - Resolution: a candle beyond the range now counts towards the breakout first, alternating or not.
     Only candles that stay inside widen the range. A hand-made test covers it.
2. **A fair "random moment".**
   - After a breakout the detector starts afresh, so a new consolidation needs at least 5 new candles.
     From an arbitrary moment, a pattern half-built from earlier candles could complete sooner, which
     would flatter trends unfairly.
   - Resolution: the comparison counts from every candle *also started afresh*, so both sides are
     measured the same way.
3. **Patterns judged by what hurts.** A flip chain loses step after step exactly while candles
   alternate, so "deep stretches" are measured directly from candle colours. That gives every pattern
   the same yardstick.
4. **The download first failed** with "no module named app": I ran the script by its file path. Run as
   `npm run history:download` does (`python -m scripts.history_download`), it worked.

## 6. Deviations from the plan

- **Five patterns instead of one,** at your request of 2026-11-20 (recorded in PHASES and D-85).
- **"Random moments" are every moment.** Instead of sampling random times, the comparison uses every
  candle, so it is the same each run.
- **The equal-candle rule is fixed, not a setting:** an equal candle always ends an alternating run.
  The `mixed` pattern is the way to tolerate one.

## 7. Could not be verified

Nothing in this phase needs your login. To see it yourself:

1. Run:
   ```
   npm run market:scan -- --asset 1HZ75V --from 2026-11-12 --to 2026-11-19 --compare
   npm run market:scan -- --asset 1HZ75V --from 2026-10-29 --to 2026-11-05 --length M5
   ```
2. **Expected:** the table in section 8, and for one week the figures as words.
3. **Try your own settings,** e.g. `--candles 6 --breakout-candles 3`. Each share has its 95% range in
   brackets: two figures whose ranges overlap are not really different.

Looking at the consolidations on a chart, to confirm we see them the same way, is Phase 30.

## 8. Measurements: the answer so far

**Data:** Volatility 75 (1s) (`1HZ75V`):
- **week A:** 12 to 19 Nov 2026, 8,993 M1 candles;
- **week B:** 29 Oct to 5 Nov 2026, 10,073 M1 candles.

**Deep** means a flip pair whose losing leg lost 6 trades in a row. That happens to 3.0 to 3.5% of
pairs at any moment.

**Which pattern describes the stretches that hurt?** Each pattern with its defaults and 2 breakout
candles by close. "Describes" is the share of the candles of deep stretches that fall inside a
consolidation; "inside" is the share of all time marked as consolidation.

| pattern | describes (A M1 / B M1 / A M5 / B M5) | inside (A M1 / B M1) |
|---|---|---|
| **alternating 5 (yours)** | **94% / 93% / 97% / 92%** | **30% / 26%** |
| mixed 6, 1 miss | 91% / 92% / 97% / 86% | 52% / 50% |
| tight 8, ×2 | 43% / 51% / 64% / 52% | 35% / 33% |
| overlap 4 | 39% / 39% / 55% / 45% | 25% / 25% |
| choppy 10, net 0.2 | 82% / 84% / 89% / 85% | 78% / 76% |

**Suggestion: keep your definition (alternating 5, breakout 2 closes).**
- It catches over 90% of the stretches that take flip chains deep while marking only about a quarter
  of the time. The others either miss most of them (tight, overlap) or mark nearly everything (choppy,
  mixed).
- This is not a coincidence: a flip chain is hurt *by* alternation, so alternation describes it best.

**Does a trend follow a breakout?** Your definition, both weeks:

| | A M1 | B M1 | A M5 | B M5 |
|---|---|---|---|---|
| consolidations found | 255 | 271 | 49 | 50 |
| candles until the next one: after a breakout / from any moment (median) | 22 / 21 | 21 / 22 | 18 / 23 | 20.5 / 23 |
| the candle after a breakout goes its way | 50.0% | 49.6% | 46.7% | 44.0% |
| all trend candles go the breakout's way | 50.0% | 50.4% | 48.9% | 52.1% |
| deep pairs: any moment / while trending | 3.5% / 3.8% | 3.2% / 3.3% | 3.0% / 3.1% | 3.5% / 4.0% |

**In plain words:**
- **Trends after a breakout do not last longer** than the stretch from any moment until the next
  consolidation. On M5 they were even a little shorter.
- **The breakout's direction does not continue** more than a coin toss, far from the 53.2% needed to
  break even.
- **Trading only the trends would not have avoided deep chains.** Pairs started while trending went
  deep as often as pairs started at any time.

The same holds for every variant tried: 4 to 7 alternating candles, 1 to 3 breakout candles, close or
touch. One setting looked better on one week (M5, alternating 4, breakout 2: 2.1% deep against 3.0%)
and was worse on the other (3.9% against 3.5%). That is exactly the trap the second week is there to
catch.

**Why:** on these indices each candle seems to be independent of the ones before. Consolidations are
real and visible afterwards, but where one ends tells nothing about the next candles.

**Speed:** three weeks of 1-second prices (1.2 million) load in 5.0 s, the scan takes 0.07 s and the
statistics 0.19 s. A chart request of 5,000 M1 candles reads about 300,000 prices.

## 9. New dependencies / files of note

No new dependencies. Files in section 2.

## 10. Suggestions and open questions

- **What next is your decision.** These figures suggest the trend sessions of Phase 31 will not beat
  always-on sessions, but they are counted from candle colours, not real trades. Phase 30 (the Market
  page) lets you check by eye that the consolidations are the ones you mean, and Phase 31 would replay
  the real trades. You could also stop after Phase 30 if you are convinced. I will go on with Phase 30
  as agreed and stop before Phase 31 for your word.
- **A faster chart:** building candles in SQLite instead of Python would make long M1 views quicker,
  if the page feels slow.

## 11. Git state

Committed with your permission ("commit the plan phases and get to work"): see STATUS for the hash.
