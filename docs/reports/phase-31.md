# Phase 31 — Backtesting the trend sessions — Report

**Date:** 2026-11-24
**Status:** Done. The answer is in section 3a: trend sessions did **not** do better. Your look in a
browser is pending (section 7).

## 1. Summary

A backtest can now open pairs **only after a breakout**, until the next consolidation, instead of all
through the window, and compare both side by side on the same prices. It can also replay everything on
a **second period** that judges settings chosen on the first. The Market page can mark **where a
backtest's pairs were opened**, coloured by what each pair made.

The run the phase asked for (Volatility 75 (1s), two separate weeks, M1 and M5, against always-on
sessions) says plainly: **trading only the trends did not do better.** Per pair it lost about the same
or more, pairs lost every step as often, and no difference held on both weeks. It lost less money in
total only because it traded fewer hours (about 40% of the time).

## 2. What was done

- **Backend:**
  - `app/backtest/replay.py`:
    - `OpenRule` (`window`, `breakout`), and `Run` (strategy × way of opening × period);
    - `BacktestSetup` gains `opens`, `market` (the detector's rules), `trend_max_candles` (default 20)
      and the second period `check_first_day`/`check_last_day`;
    - `trend_spans()`: runs the Phase 29 detector on candles of the trade length, from 100 candles
      before the first window, and gives the stretches from each breakout's `known` moment to the next
      consolidation's `stopped` moment (or the time limit);
    - `replay_window()` opens pairs only inside those stretches; running chains finish;
    - `replay()` runs every run, and counts `spans` and `active_s` (hours pairs could open).
  - `app/services/backtests.py`:
    - checks of both periods and of the 12-run limit;
    - loads the prices of both periods plus the warm-up;
    - one result per run (`opens`, `period`, `index`);
    - backtests saved before this phase still read;
    - `pairs()` for the Market page.
  - `app/backtest/store.py`: `chain_outcomes()`.
  - API: `POST /backtests` takes the new fields; `GET /backtests/{id}/pairs?run=`; the chain filter now
    indexes runs (up to 12).
  - `npm run backtest`: `--opens`, `--pattern`, `--candles`, `--breakout-candles`, `--breakout-by`,
    `--trend-max`, `--check-from`/`--check-to`.
- **Frontend:**
  - **Backtest page form:**
    - *When pairs open* (two tick boxes), and when *after a breakout* is ticked, the definition (as on
      the Market page) and *Stop after (candles)*;
    - *A second period to judge on*;
    - a "N of at most 12 runs" counter.
  - **Backtest result:**
    - each column named like *Flip every loss ×2, 4 · after a breakout · period 2*;
    - new rows: *Hours pairs could open* and *Profit per pair*;
    - a line saying which period chose the settings and which judges them, and one describing the
      trend rules.
  - **Market page:** *A backtest's pairs*. Choose a finished backtest of the asset and a run: each pair
    is marked on the candle it opened in (green circle: made money; red circle: lost; red square: a
    leg lost every step).
- **Tests:**
  - new `tests/unit/test_backtest_trends.py` (7);
  - additions to `test_api_backtests.py`, `test_backtest_script.py`, `backtestSchema.test.ts`,
    `BacktestPage.test.tsx` and `MarketPage.test.tsx`.
- **Docs:** API, OPERATIONS (trend sessions, the Market page's pairs), DOMAIN section 9, STATUS.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Pairs open only after a breakout, never before it is known | ✅ | `test_pairs_open_only_after_a_breakout_is_known_and_stop_at_the_next_consolidation`: first pair at the breakout's `known` minute (10:07), none earlier |
| They stop on time or at the next consolidation, whichever is first | ✅ | same test (14 pairs to the consolidation; 5 with a 5-candle limit); `test_a_trend_runs_from_the_known_breakout_until_the_next_consolidation_is_known` |
| Running chains finish, then it waits again | ✅ | `test_running_chains_finish_after_the_trend_and_nothing_opens_until_the_next_breakout` |
| The detector in the backtest finds exactly what the Market page shows | ✅ | `test_the_backtest_finds_the_same_trends_as_the_market_page`: the Market scan (`scan_stored`) of the same stored prices gives the same stretches |
| Determinism, API and form tests, the whole suite | ✅ | `test_trend_sessions_run_beside_always_on_ones_on_two_periods`, the form and page tests; section 4 |
| Compared side by side: trend sessions, always-on, other strategies | ✅ | runs × strategies in one backtest, section 3a |
| Two periods, the result page says which is which | ✅ | `shows which period chose the settings and which judged them`; screenshot |
| The Backtest page gains the start rule; the Market page shows where pairs opened | ✅ | `runs trend sessions beside always-on ones, on a second period too`, `marks where a backtest run opened its pairs, by what each made` |
| A run on two weeks of 1HZ75V, M1 and M5, against always-on; the report says plainly | ✅ | section 3a |

### 3a. The answer: two weeks of Volatility 75 (1s)

**Setup:**
- Your stored real prices.
- Week 1 (29 Oct to 4 Nov) chooses the settings; week 2 (12 to 18 Nov) judges them.
- All day, a pair at every candle, up to 5 open, base stake 1.00, payout 88% assumed.
- Trends: your definition (alternating 5, breakout 2 closes), stopping after 20 candles or at the next
  consolidation.
- Strategies: *flip every loss* ×2, 4, 8, 16, 32 (6 trades), and *growing flip* (9 trades).

```
npm run backtest -- --asset 1HZ75V --from 2026-10-29 --to 2026-11-04 --check-from 2026-11-12
    --check-to 2026-11-18 --window 00:00-23:59 --length 60 (or 300) --mode every_candle
    --open-pairs 5 --opens window,breakout --strategy flip_every_loss:2,4,8,16,32
    --strategy growing_flip:2,4,8,16,32,64,128,256
```

**Profit per pair** and **chains lost every step**, always-on → trend:

| | Week 1 per pair | Week 1 lost every step | Week 2 per pair | Week 2 lost every step |
|---|---|---|---|---|
| M1 flip every loss | −0.63 → −0.76 | 1.49% → 1.59% | −0.88 → −0.73 | 1.68% → 1.57% |
| M1 growing flip | −0.95 → −1.18 | 0.18% → 0.20% | −0.75 → −0.45 | 0.16% → 0.14% |
| M5 flip every loss | −1.08 → −1.91 | 1.85% → 2.48% | −0.61 → −1.64 | 1.48% → 2.25% |
| M5 growing flip | −1.42 → −1.70 | 0.22% → 0.24% | −2.27 → −1.93 | 0.31% → 0.28% |

**Totals:**
- M1, week 1: always-on flip lost 5,890 in 168 h; trend flip lost 3,171 in 71 h.
- Trend sessions traded 40% to 43% of the time.

**In plain words:**
- **Per pair, trend sessions were worse in 5 of the 8 comparisons.** Where they were better (week 2),
  they had been worse in week 1. Nothing held on both weeks.
- **Chains lost every step happened as often while trending** (within noise). On M5 flip they were
  even a little more frequent both weeks: 40 and 32 cases, too few to be sure.
- **Losses bunch up more** in trend sessions: up to 5 flip chains lost in a row, against 2 always-on.
  Several pairs opened in the same trend go deep together.
- **The smaller total loss and drawdown come only from trading fewer hours**, not from better trades.
- This agrees with Phase 29's candle-colour figures: on these indices, where a consolidation ends tells
  nothing about the next candles.

**My recommendation: do not build Phase 32 (trend sessions live).** Your decision.

## 4. Checks run

```
$ uv run ruff check . ; uv run ruff format --check . ; uv run mypy      clean (171 files)
$ uv run pytest -q                                                  1654 passed, 1 failed (11 min)
$ uv run pytest -q tests/unit/test_openapi.py                       9 passed (after the fix below)
$ npm run lint ; npm run typecheck ; npm run format:check           clean
$ npx vitest run                                                    44 files, 514 passed
$ npm run build                                                     built (Market page 62 kB gzipped)
$ npm run api:check                                                 schema.d.ts is up to date
```

**Demo self-test** (`npm run demo -- --port 8765`, made-up prices; your app on port 8000 left alone):
- logged in, downloaded two days of `1HZ75V`;
- one trend-and-always-on backtest on two periods: replayed in 1.5 s, four runs;
- trend runs: 33 and 31 trends, 9.4 h and 8.6 h of 24 h;
- `/pairs` for run 1 returned 555 pairs (equal to the run's pairs);
- half a second period refused (422);
- headless Edge screenshots:
  - the result shows the four named columns and the period line;
  - the Market page marks 508 pairs of the period-2 trend run: the dots start after each breakout arrow
    and stop at the next amber rectangle.

The demo was stopped afterwards.

## 5. Challenges and how they were resolved

1. **When a trend "starts" and "stops" without looking ahead.**
   - A trend's `end` in the detector is the first candle of the next consolidation, which is only known
     several candles later.
   - The backtest stops at `stopped`, the moment the consolidation is complete, and starts at the
     breakout's `known` moment. A test checks no pair opens before it.
2. **Matching the Market page.**
   - The detector depends on where it starts reading.
   - The backtest reads from 100 candles before the window. The test compares it with a Market scan
     from the same start on the same stored prices.
3. **Runs instead of strategies.**
   - A backtest now has up to 12 result columns. The stored chains are keyed by run.
   - Backtests saved before this phase have no new fields; they read as "always on, one period" (tested).
4. **The full suite caught one miss:** `test_the_api_offers_exactly_the_expected_operations` lists
   every API operation, and the new `GET /backtests/{id}/pairs` was not in it. Added; that file passes.
5. **Shell quoting:** inline edit scripts with apostrophes broke the shell; they were written to files
   instead.

## 6. Deviations from the plan

- **"Pairs: a pair at every candle":** the backtest keeps the session's own mode (one at a time or every
  candle), so both can be tried. The run above used every candle, as planned.
- **"Default: the median trend length from Phase 29":** fixed at 20 candles (Phase 29's medians were
  18 to 22), not measured anew on each run, which would have used the judged period's own data.
- **"Optionally within a daily window and on chosen days":** these are the backtest's existing window
  and weekday fields. A trend already on when a window opens is traded from the window's start.
- **Limit:** at most 12 runs (6 strategies × 2 ways × 2 periods would be 24).

## 7. Could not be verified (your check)

1. Start the app (`npm start`); rebuild first (`npm run build` in `frontend`) if it serves the built
   pages.
2. **Backtest page:**
   - New backtest, *Volatility 75 (1s) Index*, days 2026-10-29 to 2026-11-04, window 00:00 to 23:59, a
     pair at every candle;
   - tick both ways under *When pairs open*;
   - set *A second period to judge on* to 2026-11-12 to 2026-11-18;
   - then *Run the backtest*.
   - Expected: in about a minute, a table with columns like *… · always on · period 1* and *… · after a
     breakout · period 2*, and figures close to section 3a.
3. **Market page:**
   - under *A backtest's pairs*, choose that backtest and a *after a breakout* run;
   - *Go to* a time in its period.
   - Expected: green and red dots on the candles after each breakout arrow, none inside the amber
     rectangles. The dots are small and sit on the candles; tell me if they are hard to see.
4. **Your decision:** stop here (my recommendation), or something else (section 10).

## 8. Measurements

- One week, every candle, 2 strategies × 2 ways × 2 periods (8 runs):
  - M1 replayed in 10.8 s (14.5 s with loading);
  - M5 replayed in 3.4 s.
- The detector itself adds well under a second per week.

## 9. New dependencies / files of note

- No new dependencies.
- New: `backend/tests/unit/test_backtest_trends.py`, `frontend/src/features/market/BacktestPairs.tsx`.

## 10. Suggestions and open questions

- **Phase 32 is not supported by the data.** I suggest not building it.
- **If you want to try other ideas,** the tool is now in place. Change the pattern, the breakout or
  the stop time on the Backtest page and judge on the second week. Remember that one week looking
  better is expected by chance; only a difference that holds on both counts.
- **The "no price data" rounds in week 2** (1,088 on M1 always-on): the stored week starts at
  12 Nov 18:07 UTC, so the first 18 hours of 12 Nov have no prices. Those candles are skipped and
  counted, never guessed. Downloading 12 Nov would fill them; it does not change the conclusion.
- **The underlying fact** (Phases 27, 29, 31): with 88% payout every pair loses on average, whatever the
  timing. A strategy changes how losses bunch, not the odds.

## 11. Git state

Phase 31 was committed on 2026-11-24 with your word ("you can commit it"). The rectangle follow-up of
Phase 30 was committed before it (`a3dac1b`).
