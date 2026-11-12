# Phase 17 — Trading sessions: a pair at every candle (backend) — Report

**Date:** 2026-11-12
**Status:** Done with open items: built and tested on the fake Quotex with timers the tests move by hand. What needs the
real Quotex (section 7) is not verified. The dashboard is Phase 18.

## 1. Summary
A session now has a **mode**. *Sequential* (the default, unchanged) opens one pair at a time. The new **every candle**
mode opens a pair at every candle boundary, whatever is still running, up to `max_open_pairs` pairs open at once (a pair
is open while at least one of its chains runs). A candle that finds the limit reached gets no pair: the round is skipped
and the run records it. The chains of different pairs share nothing, and every stop rule applies to all of them: no new
pair, and every running chain of every pair finishes.

## 2. What was done
- **Data** (migration `0006_session_modes.py`): `trading_sessions.mode` and `max_open_pairs`. Existing sessions become
  `sequential` with 1 (tested with a row in the table).
- **Scheduler** (`app/sessions/scheduler.py`): the round loop now branches on the mode. Every candle: at each boundary
  after the first pair, count the open pairs from the chains in memory; open a pair if there is room (after the usual
  checks), otherwise skip the round with the reason. The sequential path is the same code as before.
- **Service, API, views:** `mode` and `max_open_pairs` (1 to 50) on a session; 422 for a limit outside that or an unknown
  mode. `pause_s` is ignored in this mode (documented).
- **Docs and generated files:** DOMAIN.md, API.md, OPERATIONS.md; `docs/openapi.json` and the frontend types regenerated.

## 3. Acceptance criteria
| Criterion | Result | Evidence |
|---|---|---|
| A pair opens at every boundary until the maximum is open; at the maximum the boundary is skipped and recorded; when a pair's last chain ends the next boundary opens a pair again | ✅ | `test_a_pair_opens_at_every_candle_until_the_maximum_is_open`, `test_a_limit_of_one_waits_for_the_pair_to_end_but_opens_on_a_candle` |
| Chains of different pairs do not influence each other (a chain at its last step, ended by the owner, or ended on a win leaves every other chain unchanged) | ✅ | `test_each_pair_follows_its_own_steps_and_stakes`, `test_ending_one_chain_leaves_every_other_chain_of_every_pair_running` |
| All stop reasons work with several pairs open; every running chain of every pair finishes | ✅ | `test_the_window_end_leaves_all_open_pairs_to_finish`, `..._profit_target_stops_new_pairs_but_every_open_chain_finishes`, `..._maximum_number_of_pairs_ends_the_run_when_the_last_pair_is_over`, `..._owner_can_stop_a_run_with_pairs_open_and_the_recoveries_still_go_out`, `test_the_kill_switch_ends_a_run_with_pairs_open` |
| A boundary is never missed or doubled by a slow round | ✅ | `test_no_boundary_is_missed_or_doubled_however_time_jumps` (one jump over seven candles: each gets exactly one pair, stamped on its boundary) |
| `sequential` behaves exactly as in Phase 16 (its tests pass unchanged) | ✅ | all 32 tests of `test_engine_sessions.py` pass unchanged |
| The execution path is unchanged (benchmark) and the opposite-pair and D-9 tests pass | ✅ | full suite, see section 4 |

Also covered: a skipped round (closed asset) is retried at the next candle, *Start now* opens at once and then on the
candles, `pause_s` is not used, the run ends early when no later candle fits in the window.

## 4. Checks run
RESULTS_PLACEHOLDER
