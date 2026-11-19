# Phase 24 — Settle faster, so martingale steps stop drifting — Report

**Date:** 2026-11-19
**Status:** Done. The live timeline (section 7b) agreed 3 of 3 and saved a median 2.0 s per result; the
early result is ready to be switched ON on the Settings page (it is still OFF until you do).

## 1. Summary

Each martingale step on Deriv waited about 3.6 s after the previous trade ended, for Deriv to mark the contract
"sold". This phase adds the **early result** (decision D-82). It is set on Settings, as *Deriv early result*.
- **How it decides:** the engine follows the asset's own price ticks. The moment a tick at or after the end
  time arrives, the closing price is certain (the latest tick at or before the end time).
- **The rule:** Rise wins when the close is strictly above the entry, Fall when strictly below, and equal
  loses.
- **Deriv's own result is still awaited.** If it ever differs, the trade and the day's figures are corrected
  and the risk log says so.
- **The latency report** now shows how long after expiry each result was known, and when the next step went
  out.
- **A timeline script** measures all of this on your demo account.

The early result is **off** until that measurement confirms it.

## 2. What was done

- **The early-result rules** (`app/deriv/protocol.py`): `ContractTerms` (entry, end time, payout, stake),
  `exit_quote`, `early_profit` and `tick_of`. All are pure functions with their own tests.
- **The Deriv adapter** (`app/deriv/adapter.py`):
  - With `early_result`, it follows each asset's ticks while it has a contract on it (`ticks` subscription),
    and decides the result as soon as it is certain.
  - It then waits for Deriv's own result in the background (`_verify`). If they differ, it calls the
    correction handler and logs `deriv_early_result_mismatch`.
  - If the ticks before the end time were not seen, there is no early result and Deriv's own is awaited.
  - An `observe()` hook exists for the timeline script only.
- **Corrections in the engine:**
  - The broker protocol gains `set_correction_handler`.
  - `Executor` keeps recent settled trades. On a correction it stores Deriv's result with a note, and the
    risk guard books the difference on the trade's day (`RiskGuard.rebook`).
  - It publishes `early_result_corrected` to the risk log. The chain is left as it is, since it already
    acted.
- **The setting:** `deriv_early_result` (OFF/ON) on the Settings page, documented in `.env.example`. It is
  passed to the adapter by the Deriv factory and used from the next engine start.
- **`npm run latency`** gains `expiry -> result` and `expiry -> next`, measured on the wall clock from each
  trade's stored times.
- **`npm run deriv:check -- --order --timeline [--count N]`** places N demo trades one after the other.
  For each it prints:
  - every contract update and price tick around the end time, timed from the end time;
  - when the early result was known;
  - when Deriv marked the contract sold;
  - whether the two agree.

  A summary follows. It always runs on the demo account.
- **The fake Deriv server** (tests) gained price ticks and contract terms.
- **Guides:** DOMAIN (when a result is known), OPERATIONS (measuring speed, the setting, the timeline),
  TROUBLESHOOTING (a corrected trade), FAILURE_MODES (a new row), DECISIONS (D-82 settled).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Early result for won, lost and equal exit | ✅ | `test_with_the_early_result_a_win_is_known_from_the_ticks_before_deriv_settles`, `test_a_tick_exactly_at_the_end_time_is_the_exit_and_an_equal_exit_is_a_loss`, `test_rise_and_fall_are_decided_strictly_and_an_equal_exit_loses` |
| Deriv's later result agrees and is kept | ✅ | The first test above: Deriv settles afterwards with the same result, no correction |
| A disagreement is marked and logged | ✅ | `test_when_deriv_disagrees_the_trade_is_corrected` (adapter), `test_a_corrected_result_replaces_the_early_one_loudly` (engine: trade, day's figures, risk log) |
| With the early path off, the engine waits as today | ✅ | `test_without_the_early_result_deriv_s_own_result_is_awaited` (no ticks are even followed) |
| `ruff`, `mypy`, the whole test suite pass | ✅ | Section 4 |
| Live (owner): 30 minutes on `1HZ75V`; `npm run latency` medians against 3.6 s and 4.1 s; no mismatch | ⏸ | Section 7: needs your demo account |

## 4. Checks run

```
$ uv run ruff check . ; ruff format --check . ; mypy     clean (153 source files)
$ uv run pytest --deselect tests/integration/test_reports_performance.py
                                      1543 passed, 2 failed: the new setting was not yet in
                                      .env.example nor in the settings-list test; both fixed,
                                      those two files then passed (21 tests)
$ npm run api:check                   schema.d.ts is up to date (no API shape change)
```

**Demo self-test** (fake brokers): the Settings API lists *Deriv early result* with OFF as its default. "maybe"
is refused with "Deriv early result must be one of: OFF, ON.", and "on" is saved as ON. The early path itself
cannot run on the demo, whose fake Deriv has no price ticks; it is covered by the adapter tests against the
fake Deriv server.

`npm run latency -- --account demo` on your real database (read-only), all demo trades so far:
- expiry → result: median 1.97 s, 95th 3.90 s;
- expiry → next step: median 2.01 s, 95th 3.89 s.

These mix Quotex and Deriv, and R_75 and 1HZ75V.

## 5. Challenges and how they were resolved

1. **When the closing price appears in Deriv's contract updates is not documented.** The schema says what
   the exit tick is, but not when it arrives. So the engine decides from the price stream, which it fully
   controls: exit = the latest tick at or before the end time, once a tick at or after it has come. The
   timeline script will show whether the contract updates would have been even earlier.
2. **The check script is loaded in tests without being registered as a module,** which breaks Python
   dataclasses. Its report is a `NamedTuple` instead.

## 6. Deviations from the plan

- **The plan had the owner's measurement come first,** then a choice between two ways. Both ways depend on
  the same rule, so I built the price-stream way (it needs nothing undocumented) and made it **off by
  default**. Your measurement now decides whether to switch it on, rather than how to build it.

## 7. Could not be verified (your live check, demo account)

1. **Synchronise the PC clock:** Settings > Time & language > Date & time > *Sync now*. The timeline is read
   against Deriv's end time.
2. **Run** `npm run deriv:check -- --asset 1HZ75V --order --timeline`. This places **3 trades of 1.00 on the
   demo account**, one after the other, about 1 minute each.
   - **Expected:** for each trade, the price ticks around the end time, then "result used by the engine" and
     "Deriv's own result: … (agrees)".
   - **The summary** shows how many seconds after the end time each was known.
   - Please send me the output.
3. **If all three agree:** set *Deriv early result* to **ON** on the Settings page, restart the engine, and run
   your session for 30 minutes.
4. **Then run `npm run latency -- --account demo --days 1`.**
   - **Expected:** "expiry -> result" and "expiry -> next" clearly below the 3.6 s and 4.1 s measured on R_75
     on the 18th. The risk log should have no `early_result_corrected`.
   - **If it has one:** switch the setting OFF and send me the `deriv_early_result_mismatch` log lines.

## 7b. Live timeline on the demo (run by the agent, 2026-11-19, with the owner's permission)

Two 1.00 trades on 1HZ75V completed; the other attempts failed on the network (below).

| | trade A (lost) | trade B (won) |
|---|---|---|
| tick at the end second arrives | −1.39 s | −1.36 s |
| Deriv's update "expired", with `exit_spot` | −1.29 s | −1.32 s |
| Deriv's update "sold" (`status` won/lost) | +0.70 s | +0.71 s |
| result used by the engine | +0.70 s | +0.71 s |
| Deriv's result = the rule's | yes (−1.00) | yes (+0.88) |

Times are by this PC's clock, which runs about 1.4 s behind Deriv's (the tick of the end second arrives at
"−1.4 s"): the gaps are what counts. **Deriv knows the exit price about 2.0 s before it marks the contract
sold**, and its `exit_spot` is exactly the tick of the end second, as the rule says.

**Why the engine did not use it:** the live API names the prices `entry_spot` and `exit_spot` (and
`entry_spot_time`, `exit_spot_time`), not `entry_tick` and `exit_tick` as in the published schema, so the
engine never had the entry price and fell back to waiting. **Fixed:** both spellings are read, and Deriv's
own `exit_spot` (in the first update after the end time) now also decides the early result, whichever of it
and the price tick comes first. The fake Deriv sends the live names; new tests cover both paths.

**Network:** 5 of 7 runs could not finish: "Deriv did not answer in time" (twice), "Could not reach Deriv
(ReadError)", "getaddrinfo failed" (the router's DNS), and one order with no confirmation within 10 s
(`OrderAckTimeoutError`: that 1.00 demo order may exist on Deriv). At the time the laptop was on battery and
Windows had logged 6 Wi-Fi "missed beacons" in 30 minutes, the same pattern as on 2026-11-18.

**With the fix, on the owner's other network (same day): 3 of 3 complete.**

| | trade 1 (won) | trade 2 (lost) | trade 3 (lost) |
|---|---|---|---|
| tick at the end second arrives | −1.29 s | −1.35 s | −1.36 s |
| **result used by the engine** | **−1.29 s** | **−1.35 s** | **−1.36 s** |
| Deriv's update "sold" | −0.09 s | +0.63 s | +0.81 s |
| saved | 1.2 s | 2.0 s | 2.2 s |
| Deriv's result = the engine's | yes (+0.88) | yes (−1.00) | yes (−1.00) |

The engine knew each result the moment the tick of the end second arrived, a median **2.0 s earlier** than
Deriv's "sold" update, and all three agreed with Deriv (no correction). Connected in 3.8 s, no failure.
**Verdict: the early result can be switched ON.**

## 8. Measurements

See section 4. The early result's own effect can only be measured on your demo (section 7).

## 9. New dependencies / files of note

No new dependencies.
- New file: `backend/tests/integration/test_engine_early_result.py`.
- New tests in: `test_deriv_adapter.py` (5), `test_deriv_protocol.py` (4), `test_latency_report.py` (1) and
  `test_deriv_check_script.py` (2).

## 10. Suggestions and open questions

- If the timeline shows Deriv's contract updates carry the exit tick before the next price tick arrives,
  the early result could use whichever comes first. That is a small addition.
- A VPS close to Deriv would also cut the ~0.5 s order confirmation (median 527 ms in your data).

## 11. Git state

Committed with your standing permission ("commit every major milestone, after testing"): see STATUS for the
hash.
