# Opposite pair for the flip strategies — Report

**Date:** 2026-11-06
**Status:** Done with open items: built and tested on the fake Quotex and fake Telegram. How close the two orders go
out, and whether Quotex treats them as a true hedge, can only be measured on the demo account (section 7).

## 1. Summary
A flip group (`flip_every_loss`, `two_step_flip`) can now run **two chains at once**: while one chain runs, a second
signal for the **opposite direction on the same asset** starts at once as its own chain. Each chain has its own
step, loss counter, stakes and owner controls, so the one that loses goes into its flip recovery while the other
ends on its win. It is a per-group switch, **off by default**, so every existing group behaves exactly as before.
The limit you asked for is built in: two chains at most, opposite direction, same asset. Anything else is still
ignored, and the signal inbox says which rule refused it.

## 2. What was done
- **Rule** (`engine/manager.py`): `_pair_refusal` replaces the one-line refusal of D-9. Same in-memory, synchronous
  check in `on_signal`; nothing was added to the fast path before an order.
- **Setting**: `allow_opposite_pair` on the group settings (record, table, migration `0004_opposite_pair.py` that
  adds it switched off for existing groups, group service, API schemas, views and router). The API answers 422
  (`invalid_group`) if it is switched on for martingale or no-martingale, which already run every signal as its own chain.
- **Dashboard**: the group form shows "Allow an opposite pair" for the two flip strategies only, with an
  explanation of the doubled risk. A strategy that cannot use it never sends it. `docs/openapi.json` and
  `frontend/src/api/schema.d.ts` were regenerated (`npm run api:check` passes).
- **Closeness of the orders**: the manager logs `opposite_pair_sent` with `gap_ms`, the time between the two
  first orders being sent, so it can be measured (see section 5, 7 and D-70 for why it is not smaller).
- **Docs**: D-70 (and a note on D-9), DOMAIN.md §3 and §5, API.md, README.
- Tests: `tests/integration/test_engine_pair.py` (8), plus new cases in `test_api_groups.py`,
  `test_repositories.py`, `test_migrations.py` and the frontend group tests.

## 3. Acceptance criteria (from the owner's request)
| Criterion | Result | Evidence |
|---|---|---|
| The restriction to wait for one chain to finish is removed for opposite signals | ✅ | `test_two_opposite_signals_on_one_asset_run_as_two_separate_chains` |
| The two trades are handled separately | ✅ | `test_each_chain_of_a_pair_follows_its_own_steps`, `test_ending_one_chain_of_a_pair_leaves_the_other_running` |
| Limited to two, opposite, same asset | ✅ | `test_a_third_signal_is_ignored_while_a_pair_runs`, `test_only_the_opposite_direction_on_the_same_asset_may_join`, `test_after_one_chain_ends_the_survivor_can_be_paired_again` |
| Nothing changes for groups that do not switch it on | ✅ | `test_a_group_without_the_pair_still_runs_one_chain_at_a_time`; the existing D-9 tests pass unchanged; migration test |
| Orders placed as close together as possible | ⚠️ | Serialised by design (D-27); the gap is logged. Not measured against the real service |

## 4. Checks run
```
$ ruff check . ; ruff format --check . ; mypy          (backend)
All checks passed; every file formatted; no issues in 129 source files
$ pytest                                                (backend, whole suite)
1245 passed, 2 failed in 773 s, then:
  - test_the_gap_between_the_two_orders_of_a_pair_is_logged: mine. structlog's capture missed a logger an
    earlier test had already bound. Rewritten to record through the manager's logger; passes (26 passed
    with the engine and task tests).
  - test_reports_performance: a timing bound of 4 s per report on 100,000 trades, missed on this PC with
    a different margin every run ('chain depth' 4.4-6.8 s, CSV export 8.0-8.9 s over two runs). It touches no group-settings code. It was already the slow, flaky test on this PC; not changed.
  Net of those: 1246 of 1247 pass; the whole suite had 1233 tests before, 14 are new (8 engine, 4 API,
  1 repository, 1 migration).
$ eslint src ; tsc --noEmit ; vitest run                (frontend)
clean; clean; 30 files, 388 tests passed (3 of them new)
$ npm run api:check
src/api/schema.d.ts is up to date; docs/openapi.json matches the backend
```

## 5. Challenges and how they were resolved
1. **Placing both orders at the same instant is not safe to attempt here.** The library keeps one shared "order
   confirmed" slot (D-27) and its confirmation carries only an order id, so two orders in flight could not be
   told apart; a mix-up would give one chain the other's result. Resolution: orders stay one at a time, the second
   goes out the moment the first is confirmed (about one round trip behind), and the gap is logged for
   measurement. Pipelining the two would need the real confirmation payloads and is listed under suggestions.
2. **The expiry can differ between the two orders.** In the default `TIME` mode the library picks each order's
   expiry from the clock when it is built (read in `pyquotex/expiration.py`): an order built after the half-way
   second of the period expires one period later than one built before it. For a 1-minute trade that line is
   second :30. A pair split by it is not a hedge. This is rare (a gap of ~0.2 s hits that second roughly one pair
   in 300) but real; `TIMER` mode avoids it in theory and is untested live. Recorded in D-70.
3. **A test failed for a reason that is not a bug:** re-sending the identical signal ("EURUSD PUT 1m") within five
   minutes is dropped by the duplicate filter before the pair rule is reached. The test now uses a different expiry.

## 6. Deviations from the plan
- The earlier proposal was a number, `max_concurrent_chains`. With the "opposite, same asset, two at most" limit
  the owner then set, a number would suggest 3 or 4 could work, so it is an on/off switch, `allow_opposite_pair`.
- Decision added: **D-70** (amends D-9).

## 7. Could not be verified
Everything needing the real Quotex. With the engine on the **demo** account, in a flip group with the pair switched on:
1. Send two opposite signals on one asset (for example `EURUSD CALL 1m` and `EURUSD PUT 1m`). Success: both appear
   in the Trades page as separate chains, and the log has `opposite_pair_sent` with a `gap_ms` (expect about one
   Quotex round trip, tens to a few hundred milliseconds).
2. Check on Quotex that the two trades have the **same expiry time**. If they differ by a minute, try
   `QUOTEX_TIME_MODE=TIMER` (Settings page, applied at the next engine start) and repeat.
3. Let one lose and watch its recovery go out as the flipped direction at the higher stake while the other ends.
4. Send a third signal and one on another asset: both should show "chain active …" in the signal inbox.
Not verified either: that Quotex accepts a call and a put on the same asset at the same moment, and how a draw is
handled across the pair.

## 8. Measurements
None against the real service. On the fake adapter the gap is about 0 ms (the fake confirms instantly), which says
nothing about the real one.

## 9. New dependencies / files of note
No new dependencies. New: `backend/alembic/versions/0004_opposite_pair.py`, `backend/tests/integration/test_engine_pair.py`,
this report.

## 10. Suggestions and open questions
- **Look-ahead exposure.** The exposure limit counts open trades only, so two chains each climbing their steps
  can stake up to twice a single chain's maximum. Set the group's max stake and daily stop-loss with that in
  mind. A limit that reserves the follow-ups would close this; it is not built.
- **Closer orders.** Sending both orders before waiting for either confirmation would shrink the gap to
  milliseconds, but needs the real confirmation payload (asset, direction, request id) to match them. A short
  demo-account capture would settle whether that is possible.
- **Expiry check.** A refusal (or a warning) when the two orders would get different expiries.
- The opposite signal is matched on the running chain's original signal direction, and its expiry is not compared.

## 11. Git state
No commits were made. Changed and new files are in `git status --short`.
