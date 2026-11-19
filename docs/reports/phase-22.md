# Phase 22 — Never freeze on a dropped connection; continue chains when nothing was missed — Report

**Date:** 2026-11-19
**Status:** Done; the live check on the owner's Deriv demo is still to be run (section 7)

## 1. Summary

The engine froze twice on 2026-11-18, each time when Deriv's connection dropped while trades were open.
The cause was a retry loop that never paused. It is fixed, and a test reproduces the exact freeze: on the old
code the test hangs, on the new code the engine keeps turning through the outage and settles every open
trade.

Beyond the fix:
- **Chains follow the owner's rule.** A chain carries on through a lost connection, and on Deriv through a
  restart, unless one of its trade times was missed. A step is never sent late.
- **Nothing on Deriv stays "unknown".** After a restart the engine asks Deriv for the result of every trade
  that was open, and of the trades an earlier restart left `unknown`.
- **Session runs carry on after a crash or Ctrl+C** while their window is open, with the missed rounds
  counted as skipped.
- ***Start now* asks Deriv for the payout first,** so it trades from its first round.
- **A stall watchdog** names the place in the code if the engine ever freezes again, and Ctrl+C now always
  ends the program.

## 2. What was done

**The freeze (decision D-78)**
- `app/deriv/connection.py`: a connection tells its owner the moment its socket closes (`on_lost`).
- `app/deriv/adapter.py`:
  - The adapter marks itself down at once.
  - `await_result` waits for a *different, open* connection after a drop, never the dead one (it pauses
    if needed).
  - A request with no answer is asked again after a 0.5 s pause.
  - It records `connected_since`.
- The other retry loops in `app/deriv/` and `app/quotex/` were checked. They all wait (backoff, monitor
  interval), so there was nothing else to fix.

**The "missed" rule (decision D-79)**
- `connected_since` is new on the broker protocol. The Deriv, Quotex and fake adapters all record it.
- `app/engine/manager.py` (`_missed`):
  - After a settled loss, if the connection in use was made after that trade expired, the next step was due
    while the connection was down.
  - The chain then ends as `failed`, with the reason "missed: step N was due at HH:MM:SS UTC, while the
    connection to Deriv was down; a step is never sent late".
  - `app/engine/chain.py`: `apply_result(..., missed=...)`.
- `app/engine/executor.py`: a step that comes due while the broker is not connected is not sent, and says
  so in words.

**After a restart (amends D-35 for Deriv)**
- `app/engine/manager.py` `recover()`:
  - A Deriv chain whose trade is still open is rebuilt (`Chain.resume`) and its stake counted again
    (`RiskGuard.adopt`).
  - It waits for Deriv's "connected" event (an event, not a timed wait), reads the trade's result, then
    follows the same "missed" rule.
- Any other open Deriv trade gets its result. Deriv trades left `unknown` in the last 7 days are looked up
  (`TradeRepository.list_unknown_since`, `RecoveryState.unknown_trades`). They keep the day they were first
  recorded on and are marked "result read from the broker after a restart".
- Quotex keeps D-35 (`unknown`).
- **Stop on the dashboard is not Ctrl+C:**
  - Stop ends the run and marks what was in flight `unknown` at once (`recover(..., carry_on=False)`), as
    before; the next start reads those Deriv results.
  - The application closing (`Engine.stop(closing=True)`) leaves everything for the next start to carry on.

**Session runs resume (amends D-73)**
- `app/sessions/scheduler.py`: a run found `running` at start-up carries on when:
  - its window is still open;
  - its session exists and is switched on;
  - the kill switch is off;
  - the account is the same.
- Its counters carry on. Its chains that the manager carried on stay its own.
- Missed candles count as skipped rounds: "carried on after a restart: N round(s) missed while the
  application was not running".
- A one-pair-at-a-time run first lets a pair it carried on finish.
- Otherwise it ends `interrupted`, with the reason in its note.

**Start now on Deriv**
- Every run asks for the asset's payout before its first round. This does nothing extra when a scheduled
  start already asked a minute ahead.
- A round that finds no payout asks for it in the background, so the next round can trade.
- The fake Deriv now knows a payout only after it was asked for, like Deriv, so the tests can see this
  bug.

**The stall watchdog (decision D-80)**
- `app/core/watchdog.py`, started in `app/main.py`: a thread checks every second that the event loop turns.
- After 10 s without a turn it logs `engine_stalled` with the loop's stack (again every 60 s, then
  `engine_unstalled`).
- Ctrl+C (and a service stop) also starts a 15 s clock. If the program is still there after that, it is
  ended (`engine_forced_exit`).
- The brokers now close at the same time when the engine stops, so a normal stop takes at most 10 s.

**Guides**
- FAILURE_MODES: the table, Deriv drops, crash, shutdown, and a new section "The engine freezes".
- TROUBLESHOOTING: "missed", "result read from the broker", `engine_stalled`, the payout.
- OPERATIONS: restarts, stopping, and a new section "A steadier connection on a home PC".
- DOMAIN (run states, the missed rule), ARCHITECTURE (the watchdog), DECISIONS (D-78 to D-80, and how they
  were settled).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Fake Deriv closes with 1001 while 1, then 5, contracts are open; the engine stays responsive, reconnects and settles every open trade with the server's result | ✅ | `test_a_deriv_restart_with_one_contract_open_never_freezes_the_engine`, `..._five_contracts_open_...`. Instead of a health request, a heartbeat on the same event loop is checked: it must turn at least 10 times in 0.5 s during the outage (a stricter test of the same thing). On the old code the five-contract test **hung until killed after 60 s** (the freeze, reproduced). |
| The same with a socket that dies without a close frame | ✅ | `test_a_network_cut_with_contracts_open_never_freezes_the_engine` |
| Back before expiry: chains continue | ✅ | `test_back_before_the_trade_expires_the_chain_simply_continues` |
| A drop longer than the time limit: the trade ends `unknown`, never a guess; the next start settles it from Deriv | ✅ | The time limit is unchanged (executor). `test_trades_an_earlier_restart_left_unknown_get_their_real_result`, `test_a_trade_deriv_cannot_report_stays_as_it_was` |
| Back after expiry: the trade gets its real result, the chain ends as missed with the reason | ✅ | `test_back_after_the_trade_expired_the_step_is_missed_and_the_chain_ends`, `test_a_result_that_arrives_while_the_broker_is_down_misses_the_step`, `test_the_same_rule_holds_for_quotex_while_the_engine_runs` |
| Restart (Deriv): before expiry continues; after expiry ends as missed with the real result; a run in its window resumes and counts missed rounds; Quotex still `unknown` | ✅ | `test_a_restart_before_the_open_trade_expires_carries_the_chain_on`, `test_a_restart_after_the_open_trade_expired_reads_its_result_and_ends_the_chain`, `test_a_chain_carried_on_waits_for_deriv_to_connect_first`, `test_a_run_found_going_after_a_restart_carries_on_in_its_window`, `test_a_quotex_chain_still_ends_unknown_after_a_restart` |
| Watchdog: a blocked loop gives `engine_stalled` with a stack; Ctrl+C on a stalled loop ends the process in time | ✅ | `tests/unit/test_watchdog.py` (5 tests; the stack names the blocking function) |
| Start now on a fresh Deriv connection trades from its first round; a round without a payout fetches it | ✅ | `test_start_now_on_deriv_trades_from_its_first_round`, `test_a_round_without_a_payout_asks_deriv_so_the_next_round_trades`; and on the demo: first pair 0.3 s after *Start now* |
| `ruff`, `mypy`, the whole test suite pass; guides updated | ✅ / ⚠️ | See section 4: everything passes except the report speed test, which was already failing before this phase on this PC |
| Live (owner): Wi-Fi off/on while trades are open | ⏸ | Section 7 |

## 4. Checks run

```
$ uv run ruff check .                 All checks passed!
$ uv run ruff format --check .        289 files already formatted
$ uv run mypy                         Success: no issues found in 151 source files
$ uv run pytest --deselect tests/integration/test_reports_performance.py
                                      1517 passed, 2 failed (test_watchdog: see 5.6)
$ uv run pytest tests/unit            (after the fix) 735 passed
$ npm run api:check                   schema.d.ts is up to date (no API change)
```

The report speed test (`test_reports_performance`) was not run again. It failed on this PC before this phase
(Phase 21 report, section 5.3), and nothing in this phase touches the reports. The frontend is unchanged.

**Self-test on `npm run demo`** (fake brokers only, port 8011, its own demo database):
1. Made a Deriv session (R_75, 1 minute, a pair at every candle, martingale) and pressed *Start now* on a
   freshly started engine. The first pair was sent **0.3 s** later, with 0 skipped rounds. Before this fix
   every round was skipped ("the payout of R_75 is not known").
2. After 3 pairs, **killed the demo process** (like a crash), waited about 2 minutes, and started it again
   (without `--reset`). The log said `session_run_resumed rounds_missed=3`. The same run (same id) was
   `running`, with "carried on after a restart: 3 round(s) missed while the application was not running".
   At the next candle (07:05) pair 4 went out.

## 5. Challenges and how they were resolved

1. **The existing reconnect test passed by luck.** `test_a_result_that_comes_during_a_reconnect_is_still_reported`
   uses a 0.01 s monitor, so the monitor noticed the drop before the result loop started spinning. At the
   real setting of 1 s the loop wins and the engine freezes. The new tests use the real setting, and one of
   them was run against the old code to prove it catches the freeze (it hung until killed).
2. **Ctrl+C closed the session run.** The first version would have let a run carry on after a crash, but not
   after Ctrl+C, because a normal stop ended the run as `engine_stopped`. That contradicted what was agreed.
   The engine now tells *the application is closing* apart from *the owner pressed Stop*.
3. **Stop on the dashboard calls the restart-recovery step straight away.** With the new recovery that would
   have tried to carry Deriv chains on inside an engine that had just stopped. It now has a "carry nothing
   on" mode (`carry_on=False`).
4. **Architecture rule D-13** ("nothing in the engine sleeps"): the first version waited for the broker by
   looking every half second. The rule's test caught it. It now waits for the broker's `ConnectionChanged`
   event.
5. **The risk guard's day totals.** Booking a late result on the day it was first recorded first changed what
   `settled()` means for every trade, which broke a test. It is now an explicit `at=` used only for late
   lookups.
6. **Two watchdog tests failed only in the full run.** The watchdog did log `engine_stalled` (naming the
   blocking function) and `engine_forced_exit`, but once another test has set logging up, structlog's
   log-capture helper sees nothing. The watchdog now takes its logger as a parameter and the tests record
   its lines directly. All unit tests then passed (735); the only change since the full run was these
   two tests and that parameter.

## 6. Deviations from the plan

- **The scope of the "missed" rule (D-79).** The plan's wording ("the step that was due during the outage is
  missed") is implemented by comparing the connection time with the trade's expiry, for both brokers.
- **Quotex during a reconnect.** The rule applies, but its open trade usually ends `unknown`, because our
  Quotex adapter waits for the result on the connection that placed the order. Written in DECISIONS and
  FAILURE_MODES.
- **No new chain status.** A missed chain ends as `failed` with a "missed: ..." reason, so the dashboard and
  reports needed no change.
- **Ctrl+C is not Stop:** added (see 5.2); recorded under "D-78 to D-80 settled in Phase 22".
- **The fake Deriv's payout** now behaves like Deriv (known only after it was asked for). No other test
  needed a change because of it.

## 7. Could not be verified (owner's live check, Deriv demo)

What I ran (section 4) used fake brokers only, and I did not run any live script.

1. **Restart the app:** close it with Ctrl+C, then `npm start`. If Ctrl+C ever hangs, it now ends by itself
   within 15 seconds.
2. **Start your *Deriv Trial* session with *Start now*.** **Expected:** the first pair goes out at once (no
   "payout is not known").
3. **A short drop:** while trades are open, turn the Wi-Fi off for about 10 seconds and on again, well before
   the trades expire. **Expected:**
   - the banner shows Deriv reconnecting, then connected;
   - every open trade gets its result;
   - losing chains send their next step on time;
   - the dashboard keeps answering throughout.
4. **A long drop:** turn the Wi-Fi off for longer than one trade (more than 1 minute on 1-minute trades), then
   on. **Expected:**
   - those trades still get their real results;
   - a losing chain ends with "missed: step N was due at ... while the connection to Deriv was down";
   - new pairs open at the next candle;
   - the engine never freezes.
5. **A crash:** while a run is going, close the window (or press Ctrl+C), wait 2–3 minutes, then `npm start`.
   **Expected:**
   - the run carries on, with "N round(s) missed while the application was not running";
   - trades that were open have real results ("result read from the broker after a restart").
6. **The 9 trades from 2026-11-18:** after the first start of this version they show their real results
   (won/lost) instead of `unknown`. Compare one with Deriv's statement.
7. If the log ever shows `engine_stalled`, keep that line: it says exactly where the engine was stuck.

## 8. Measurements

No new timings. The engine's own work stays about 1 ms per step (Phase 22 changes nothing on the order
path except one in-memory check of the connection state).

## 9. New dependencies / files of note

- No new dependencies.
- New files:
  - `backend/app/core/watchdog.py`: the stall watchdog.
  - `backend/tests/integration/test_engine_continuity.py` (11 tests).
  - `backend/tests/unit/test_watchdog.py` (5 tests).
  - In `backend/tests/integration/test_deriv_adapter.py`: 4 new tests.
  - In `backend/tests/integration/test_engine_sessions.py`: 7 new tests, in place of the old "left-over run"
    test.
  - In `backend/tests/deriv_server.py`: a 1001 close and a network cut.

## 10. Suggestions and open questions

- **Phase 23** (a switch per broker) and **Phase 24** (faster results) are next, as planned.
- **Quotex results across a reconnect** could be read from Quotex's trade history after a new login. That
  would let Quotex chains carry on too (D-35 stays for Quotex until then).
- **A VPS** remains the real cure for a home network's drops (see OPERATIONS, "A steadier connection").

## 11. Git state

Committed with the owner's standing permission ("commit every major milestone, after testing"): see
STATUS for the hash.
