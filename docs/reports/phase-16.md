# Phase 16 — Trading sessions: one pair at a time (backend) — Report

**Date:** 2026-11-12
**Status:** Done with open items: built and tested on the fake Quotex with timers the tests move by hand. Everything that
needs the real Quotex (section 7) is not verified. The dashboard page is Phase 18.

## 1. Summary
A **trading session** can now be saved, and the engine opens its pairs by itself, with no Telegram signal. A session has
one asset, a trade length, a time window with a time zone and a repeat rule (*once*, or chosen weekdays), a strategy and
optional profit and loss targets. At the start time it opens the first pair (a CALL and a PUT together); the one that
loses recovers by the strategy, the one that wins ends. When both chains are over it waits the pause you set and opens
the next pair on the next candle. It stops by the soft-stop rules (no new pairs, running chains always finish). It is all
controlled through the API (`/api/v1/sessions`). The engine can also start now **without a Telegram login**.

## 2. What was done
- **Data** (migration `0005_trading_sessions.py`): tables `trading_sessions` and `session_runs`; `groups.source`
  (`telegram`/`session`) and a nullable `telegram_chat_id` (a session's hidden group has no chat); `chains.session_run_id`
  and `chains.pair_no`. Existing groups stay `telegram`. Upgrade and downgrade are tested with data in the tables.
- **Schedule rules** (`app/sessions/schedule.py`, pure): window in the session's zone, midnight crossing, daylight saving
  (a start time that does not exist gives no window), repeat (`once` = the first window after it was saved), the overlap
  test between two sessions over two weeks, candle boundaries (multiples of the trade length from the epoch).
- **Scheduler** (`app/sessions/scheduler.py`): waits for windows; a minute before, makes the asset ready; at the start
  time opens the pair; checks *both* orders before either is sent (kill switch, connected, asset open, payout at
  least the minimum), else skips the round and records why; sequential mode with the pause and the candle alignment;
  every stop reason of D-72; run accounting from the settled trades; a run is `ended` when its last chain ends.
- **Manager** (`engine/manager.py`): `open_session_chain` starts one leg without decision D-9 (the scheduler is the
  gatekeeper); `on_signal` (Telegram) is unchanged apart from sharing the chain-creation code.
- **Engine** (`engine/engine.py`): owns the scheduler; the hidden group only reaches the manager (no route, no listener);
  `Engine(source=None)` runs with signals off; the account cannot be switched while a run is going; the scheduler stops
  first on `stop()`.
- **Telegram optional:** `build_engine` falls back to no Telegram source; the login list marks the three Telegram items
  not required; `/health` no longer complains about a Telegram that is off on purpose.
- **Service and API:** `SessionService` (validation in words, hidden group, overlap check, refuses edit/delete while
  running, refuses delete with runs on record) and the routes `GET/POST /sessions`, `GET/PUT/DELETE /sessions/{id}`,
  `POST /sessions/{id}/start|stop`, `GET /sessions/runs`. Chains now carry `session_run_id` and `pair_no`.
- **WebSocket:** a `session.run` message for every run change (the repository's test requires a message for every event);
  the dashboard ignores it for now (Phase 18 uses it). `docs/openapi.json` and the frontend types were regenerated.
- **Docs:** D-73 amended (see section 6), DOMAIN.md, API.md, ARCHITECTURE.md, OPERATIONS.md, README.md.

## 3. Acceptance criteria
| Criterion | Result | Evidence |
|---|---|---|
| A 23:00-style session places its CALL and PUT at the start time exactly, nothing earlier | ✅ | `test_the_first_pair_goes_out_at_the_start_time_and_not_before` (trades stamped 11:00:00; the asset made ready at 10:59) |
| Sequential: no pair while one runs; after both ended and the pause, the next at the first boundary at or after | ✅ | `test_no_new_pair_opens_while_a_pair_is_running`, `test_after_the_pair_is_over_the_next_one_opens_at_the_next_candle`, `test_the_pause_between_pairs_is_waited_after_both_chains_ended`, `test_a_pair_that_ends_just_after_a_candle_began_counts_as_on_the_boundary` |
| Each stop reason opens no pair, lets the running chains finish, records the reason | ✅ | window end, profit target, loss limit (which loses more than the limit), max pairs, Stop, kill switch: six tests in `test_engine_sessions.py`; `test_no_pair_opens_at_or_after_the_end_of_the_window` |
| A failed check sends no order and records why | ✅ | `test_a_closed_asset_skips_the_round...`, `test_a_payout_below_the_minimum_sends_nothing`, `test_a_lost_connection_skips_the_round` |
| Overlapping windows refused on save (midnight, weekdays); Start now refused while a run is going | ✅ | `test_session_schedule.py` (overlap), `test_two_enabled_sessions_may_not_overlap`, `test_overlap_is_found_across_midnight...`, `test_start_now_opens_the_first_pair_at_once...` |
| *Once* runs one window; weekdays only on its days; a window missed with the engine off does not run | ✅ | `test_a_once_session_runs_one_window_and_never_again`, `test_a_weekday_session_runs_on_its_days_only`, `test_a_window_that_is_open_when_the_scheduler_starts_is_not_started` |
| Restart: the run becomes `interrupted`, nothing resumes | ✅ | `test_a_run_left_over_from_a_dead_process_ends_as_interrupted`, and through the real application start `test_a_run_found_still_going_at_start_up_ends_as_interrupted_and_is_not_resumed` |
| The engine starts with Quotex only and a session trades | ✅ | `test_sessions_run_without_a_telegram_login`, `test_without_a_telegram_login_the_engine_is_built_with_signals_off`, `test_an_engine_without_telegram_is_healthy_with_quotex_alone` |
| Telegram groups behave as before (D-9, D-70, pipeline tests unchanged) | ✅ | the existing suite passes unchanged apart from the Telegram-login test below |
| The execution path is unchanged; architecture rules pass | ✅ | `test_engine_latency` / the benchmark (median 2.8 ms, max 4.6 ms for 20 loopback orders); `test_the_session_scheduler_works_before_the_order_path_and_never_touches_the_database` |
| Migration: upgrade/downgrade, existing groups keep `source = telegram` | ✅ | `test_trading_sessions_keep_existing_groups_and_history` |

## 4. Checks run
```
$ ruff check . ; ruff format --check . ; mypy                  (backend)
All checks passed; 257 files formatted; no issues in 136 source files
$ pytest                                                       (backend, whole suite, 10 min)
1325 passed, 2 failed; after fixing one of them (below): 1326 passed, 1 failed (not mine, see below)
$ eslint . ; tsc -b --noEmit ; prettier --check .              (frontend)
clean; clean; clean
$ vitest run                                                   (frontend)
388 passed, 1 failed (App.test "marks the current page..."): also fails on the committed baseline
$ npm run api:check
docs/openapi.json is up to date; src/api/schema.d.ts is up to date
```
Failures, plainly:
- `test_without_a_login_the_engine_page_says_so` (Telegram login test) failed because it asserted that Telegram is a
  *missing login*. Telegram is now optional on purpose (D-71), so the test now asserts it is shown, not required and not
  listed as missing. 39 tests of that file pass.
- `test_reports_performance` (4 s bound for each report on 100,000 trades) missed it once more, by a different margin each
  run (this time only the CSV export, 4.37 s). It touches no session code and was already the slow, flaky test on this PC
  (see the opposite-pair report). Not changed.
- `App.test.tsx > marks the current page, and navigates` fails in the full frontend run and passes on its own (14 of 14).
  I ran the full frontend suite on the committed code (`git stash` of `frontend/`) and it fails the same way, so it is not
  caused by this phase. Not changed.

## 5. Challenges and how they were resolved
1. **The engine package may not sleep.** An existing architecture test forbids any `sleep` in `app/engine` (decision
   D-13: results are awaited as events). A scheduler is all waiting. Resolution: the scheduler lives in its own package,
   `app/sessions/`, which the engine only composes; a new architecture test keeps it away from the database and keeps
   the executor, chain, strategies, manager and risk modules from importing it. The original rule is untouched.
2. **A lost profit.** A first version of the safety net that forgets chains the manager no longer runs also forgot the
   mapping used to book a trade's profit, so a trade settled a moment before the net ran could be missed. The net now only
   touches the "running chains" set; the profit mapping is cleaned when the chain's end is seen or the run ends, after the
   event consumer has been given the turns it needs.
3. **A pair that "ends" in the same instant as it opens.** In a test the chains settled at once, and the next pair then
   opened at the same candle. In reality a trade lasts at least a minute, so a pair cannot end within five seconds of
   opening; the five-second grace after a boundary is what lets a pair that ends one second after a candle opens the next
   pair at once instead of losing a whole candle. The test now settles at a realistic time.
4. **Time in tests.** `asyncio.sleep` does not move a manual clock, so the tests use fake timers (`tests/session_support.py`)
   that wake each sleeper at its own moment in order. That made the "exactly at 11:00:00" test possible.
5. **Every event needs a WebSocket message** (an existing test), and the frontend handles every message type
   exhaustively. A small handler was added in three frontend files so the build stays type-safe.

## 6. Deviations from the plan
- The scheduler is in `app/sessions/`, not `engine/sessions.py` (challenge 1). PHASES.md and ARCHITECTURE.md were corrected.
- D-73 said a run in progress when the application stops ends as `interrupted`. It is exact only for a crash or kill: a
  normal engine stop (the application's shutdown included) ends the run as `engine_stopped`; `interrupted` is what the
  next start finds still marked as going. D-73 was amended.
- The `session.run` WebSocket message and its frontend handler were planned for Phase 18; the message had to exist now.
- Two small rules that were not spelled out: *Start now* is refused for a switched-off session, and saving a *once*
  session arms it again (its window is the first one that starts after the save).
- No new decision numbers (D-71 to D-73 cover it).

## 7. Could not be verified
Everything that needs the real Quotex. With the engine on the **demo** account and a session on a real asset (`EURUSD`,
or `EURUSD_otc` at the weekend) with a start two or three minutes ahead, on an M5 boundary:
1. The first pair goes out at the start second: the Trades page shows two chains of the session with trades created
   within about a round trip of each other (the log has `opposite_pair_sent`-style timing only for Telegram pairs; the
   gap here is `t_order_sent_ns` of the two first trades).
2. Both trades have the **same expiry** on Quotex (a start off the candle boundary can give different expiries in the
   default `TIME` mode; try `QUOTEX_TIME_MODE=TIMER` if they differ).
3. A call and a put on one asset at the same moment are accepted, and a draw is handled across the pair.
4. `prepare_asset` a minute before the window works with the real library; the asset names and payouts used by the
   pre-check match what the library reports (a wrong name shows up as "closed or unknown").
5. A full window: pairs one after the other, then the window end, with a recovering chain finishing after it.
6. The real engine started with no Telegram login (`build_engine` was tested with the real classes but nothing connected).

## 8. Measurements
None against the real service. The existing loopback benchmark is unchanged: `place_order` send to ack, 20 orders, median
2.8 ms, max 4.6 ms.

## 9. New dependencies / files of note
No new dependencies. New: `alembic/versions/0005_trading_sessions.py`, `app/sessions/` (`scheduler.py`, `schedule.py`),
`app/services/sessions.py`, `app/api/routers/sessions.py`, `app/api/schemas/sessions.py`,
`app/db/repositories/sessions.py`, and the tests `test_engine_sessions.py`, `test_api_sessions.py`,
`test_session_storage.py`, `test_session_schedule.py`, `test_engine_factory.py` with `tests/session_support.py`.
Tests: 80 new (32 scheduler, 16 schedule rules, 16 API, 12 storage, and one each for the factory, health, migration and
architecture rule).

## 10. Suggestions and open questions
- **The loss limit is not a cap** (D-72, by the owner's choice). The form in Phase 18 will show the worst case in figures.
  A second, hard limit that ends chains would be the way to a real cap; not built.
- **Orders still go out one at a time** (D-27), so the two legs of a pair are about one round trip apart; measure it on
  demo (section 7).
- The signal inbox now also lists the sessions' rows (raw text like `London open: pair 3, CALL EURUSD 5m`) under the hidden
  group; Phase 18 will show the session's name instead of a group id.

## 11. Git state
Committed after the checks above (the owner asked for a commit after each milestone).
