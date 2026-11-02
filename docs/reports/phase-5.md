# Phase 5 — Safety and control — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes. Like Phases 2-4 it has
only run on fakes (section 7). Committed at the owner's instruction after review.

## 1. Summary
Every order now passes a `RiskGuard` just before it is sent. It enforces a maximum stake, a maximum
number of open trades, a cap on the total of open stakes, a maximum chain length, a minimum payout per
group, and daily stop-loss and profit-target limits, globally and per group. There is a kill switch, group
pausing, "stop after the current trade" and "end chain", and switching between demo and real is refused
while anything is running. A blocked order is not sent, its chain ends, and a `risk.tripped` event states
exactly what was blocked and why; it is stored. The kill switch, pauses, limits and the day's totals
survive a restart. The guard adds about **5 µs** to an order.

## 2. What was done
- **`app/engine/risk.py`** — `RiskLimits`, `GroupRiskLimits`, `RiskGuard`: `admit` (check + reserve),
  `release`, `settled` (frees the slot, books the profit), the daily-window logic (`day_start`),
  kill switch, paused groups, and save/restore of all of it (D-37).
- **Controls** (`ChainManager`, for the Phase 6 API to call): `pause_group` / `resume_group`,
  `engage_kill_switch(stop_chains=…)` / `release_kill_switch`, `stop_after_current(chain_id)`,
  `end_chain(chain_id)`. A control on a chain that is not running raises `UnknownChainError`.
- **Account guard** (`Engine.switch_account`): refused while a chain or an open trade exists
  (`AccountSwitchRefusedError`); real still needs `QUOTEX_ALLOW_REAL` (the adapter's own check).
- **Executor / chain / manager changes:** the executor asks the guard before publishing the pending trade
  and tells it about every settled, refused or unknown trade; a blocked order becomes a `failed` trade with
  the reason and ends its chain (`stopped` for the kill switch, `failed` for a limit); a chain can be
  ended by the owner while its trade is open and the trade is still recorded.
- **Persistence plumbing:** a `setting.changed` event stored by the DB writer in `app_settings`; start-up
  recovery now also loads the app settings and the last 48 h of settled trades (to rebuild the day's totals).
- **Docs:** D-37, D-38, ARCHITECTURE layout, README "Safety", STATUS.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Each limit has tests for just below / at / above the threshold | ✅ | `tests/unit/test_risk_guard.py` (70 tests): max stake (`9.99/10.00/10.01`), group max stake, max concurrent trades (2nd/3rd/4th), max exposure (`5.99/6.00/6.01` on top of 4.00), max chain length (trade 2/3/4), minimum payout (`81/80/79`), daily stop-loss (`-9.99/-10.00/-10.01`), daily profit target (`9.99/10.00/10.01`), group stop-loss and profit target. What "at" means for each is in D-37 |
| Kill switch: no order after it is engaged, including follow-ups already queued | ✅ | `test_engine_safety.py::test_no_order_goes_out_after_the_kill_switch_even_with_many_follow_ups_queued` (three chains each waiting for a loss; engage; three losses arrive at once; zero new orders, three `stopped` chains, three `risk.tripped`), `…_stops_a_follow_up_that_was_waiting_for_a_loss`, `…_can_stop_the_running_chains_at_once` |
| Daily limits reset at a documented time/timezone (tested) | ✅ | Default 00:00 UTC, configurable zone + time (D-37). `test_the_daily_totals_reset_at_the_boundary_and_not_a_second_before` (23:59:58 blocked, 23:59:59 blocked, 00:00:00 free), `test_the_reset_follows_the_configured_zone_and_time` (06:00 in UTC-3 = 09:00 UTC), the daylight-saving day boundary in New York, and `test_the_daily_stop_loss_ends_trading_for_the_day_and_resets_after_midnight` through a running engine |
| Hot-path overhead of `RiskGuard` measured and reported | ✅ | section 8 |
| A tripped limit publishes `risk.tripped`, is persisted, and says what was blocked | ✅ | `test_a_blocked_order_publishes_a_risk_event_that_says_what_was_blocked`; stored in `test_blocked_orders_are_stored_as_risk_events` (kind, group, message, asset/step/stake) |
| Pause/resume group; stop after current; skip to base / end chain | ✅ | `test_pausing_a_group_ignores_new_signals_but_lets_running_chains_finish`, `test_stop_after_current_…` (loss ends it, a win is unchanged), `test_ending_a_chain_frees_the_group_now_and_the_open_trade_is_still_recorded` |
| Account-type guard: real needs the setting; switching with open chains refused | ✅ | `test_the_account_cannot_be_switched_while_a_chain_is_running`, `…_trade_of_an_ended_chain_is_open`, `test_real_money_needs_the_explicit_setting` |

## 4. Checks run
```
$ npm run check
ruff check: All checks passed!      ruff format: 126 files already formatted
mypy (strict): Success: no issues found in 69 source files
pytest: 624 passed in 24.3 s        vitest: 3 passed       vite build: built in 187 ms
```
Mutation checks: I broke the safety code on purpose in 25 ways: every `>` / `>=` boundary above, a day that
never resets, demo and real totals mixed, the kill switch ignored, reservations never released, an
unreadable setting ignored, the kill switch not restored, a paused group still taking signals, profit not
booked, no risk event, the executor ignoring the guard's answer, the kill switch ending a chain as
`failed`, a stop request ignored, an ended chain still blocking its group, the account switch unchecked.
**All 25 are caught by a test.**

## 5. Challenges and how they were resolved
1. **A damaged stored limit crashed start-up.** A setting missing a field raised `KeyError`, which the
   loader did not expect. A test for "unreadable setting" found it. Now any unreadable stored limit or
   control engages the kill switch (D-37): the safe reading of a limit we cannot read is to stop trading,
   not to trade without it.
2. **Benchmark that tripped its own limits.** My first overhead benchmark won so much that it hit the
   profit target and the guard (correctly) started refusing. The benchmark now alternates wins and losses.
3. **A test replayed stored settings in the wrong order** (the database keeps the last write per key);
   fixed in the test, not the code.
4. **Heredoc quoting in my shell** broke again once; I used a script file.

## 6. Deviations from the plan
- **Limits and controls are set from code, not from a screen.** As in the plan ("exposed via API in Phase 6").
  Until then nothing sets limits: **all limits are off by default** (and the engine itself is off by
  default, D-36). Before the engine is ever pointed at real money, the limits must be set; I suggest the
  Phase 6 API refuses to enable real trading while no stop-loss is set (section 10).
- **Per-group limits are not columns of the group settings table** (that would be a schema change); they
  are stored as app settings (`risk.group.<id>`), which also keeps the migrations unchanged.
- **New decisions:** D-37, D-38.

## 7. Could not be verified
Everything real, as in Phases 2-4: the guard has only run with the fake Quotex and Telegram.
- That a real lost trade arrives with a **negative** profit (Phase 2 §7). The daily stop-loss and the
  group stop-loss add up the profit of settled trades; if Quotex reported a lost trade as 0, the
  stop-loss would never trigger. This must be confirmed on the demo account before relying on a stop-loss.
- The payout figure the minimum-payout rule reads (the Phase 2 §7 question about the 1-minute and
  5-minute columns).
- A kill switch pressed in the few milliseconds while an order is already being sent cannot recall it
  (D-38). With a real network that window is the round trip to the adapter's send, not the confirmation.

## 8. Measurements
Measured on this PC (real clock, fake adapter), `tests/integration/test_risk_overhead.py`:

| | median | 99th percentile | worst of 20,000 |
|---|---|---|---|
| `RiskGuard.admit`, every limit switched on | 5.3 µs | 17 µs | 0.14 ms |
| `RiskGuard.settled` (frees the slot, books the profit) | 3.0 µs | 9 µs | 0.17 ms |

End to end (3,000 signals, one at a time, as in the Phase 4 report), now with the guard and its
`pending` record in the path:

| | median | 99th percentile | 99.9th |
|---|---|---|---|
| signal → `place_order` | 96 µs | 245 µs | 0.4 ms |
| message → `place_order` | 163 µs | 364 µs | 0.5 ms |

Phase 4 measured 75 µs and 142 µs for the same two, so the guard and its bookkeeping add about 20 µs. The
figures move with how busy the PC is: a run started right after the full test suite measured about
twice as much. Quotex's own network time is not part of any of them.

## 9. New dependencies / files of note
No new dependencies. New: `app/engine/risk.py`, `app/engine/errors.py`; tests `test_risk_guard.py`,
`test_engine_safety.py`, `test_engine_safety_persistence.py`, `test_risk_overhead.py`. Changed: the
executor, chain, manager and engine (guard wiring and controls), `app/events/types.py` (`SettingChanged`),
the DB writer and recovery (settings and recent trades), `TradeRepository.list_settled_since`.

## 10. Suggestions and open questions
- **Set a stop-loss before real money.** Suggest that Phase 6/7 refuse to switch to REAL while no daily
  stop-loss and no max stake are configured.
- **Unknown trades** (no confirmation, no result, restart) are not counted in the day's result and are
  released from the open count. A conservative alternative is to count their stake as a loss; say if you
  want that.
- **A draw** counts as a result of zero.
- Several chains on one asset in a non-flip group are still allowed (Phase 4 §10); the concurrency and
  exposure limits are the guard against too many at once.
- `end_chain` / `stop_after_current` are per chain id; the dashboard will need the chain list (Phase 6).

## 11. Git state
Committed as `feat: safety and control (Phase 5)` once you approved it. Changed and new files (`git status --short`): modified `README.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `docs/STATUS.md`, `backend/app/db/recovery.py`, `…/repositories/trades.py`,
`…/db/writer.py`, `…/domain/enums.py`, `…/engine/{chain,engine,executor,manager}.py`,
`…/events/types.py`, `backend/tests/engine_support.py`; new `backend/app/engine/{risk,errors}.py` and
four test files. No secrets or data files are among them.

## 12. How to test it yourself
No account is needed; I ran 1-3 myself before writing this.

**1. Everything**
```
npm run check
```
Expect `624 passed` (backend), `3 passed` (frontend), lint, types and build clean.

**2. Every limit at its boundary, readable**
```
cd backend
uv run pytest tests/unit/test_risk_guard.py -v
```
Each limit appears three times (just below / at / above), for example `test_max_stake[9.99-True]`,
`[10.00-True]`, `[10.01-False]`.

**3. The kill switch and the controls on a running engine**
```
uv run pytest tests/integration/test_engine_safety.py tests/integration/test_engine_safety_persistence.py -v
```
Look for `test_no_order_goes_out_after_the_kill_switch_even_with_many_follow_ups_queued` and
`test_the_kill_switch_pauses_and_limits_come_back_after_a_restart`.

**4. The speed figure**
```
uv run pytest tests/integration/test_risk_overhead.py -s
```
Prints `RiskGuard.admit … median … us`. Expect single-digit microseconds.

**5. LIVE (later, when the engine and the Phase 6 screens exist; demo account)**
Set a daily stop-loss of, say, 3, run a few losing demo trades and confirm trading stops. Do this before
anything else on a demo account: it also confirms that Quotex reports a loss as a negative profit
(section 7), which the stop-loss depends on.
