# Phase 4 — Strategy and chain engine — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes. Nothing here has been
run against the real Quotex or Telegram (the engine is off by default, section 7).

## 1. Summary
The system now trades, on fakes. A message from the (fake) Telegram goes through the parser and the
pipeline into a `ChainManager`, which opens a chain for the signal; each chain runs in its own task and
places its trades through an `Executor` onto the Quotex adapter; a loss produces the next step at once,
by the rules of the four strategies; and everything is recorded through events, never through the hot
path. Three groups with different strategies and overlapping chains run correctly side by side, a new
signal during a flip-strategy chain is ignored and the inbox says why, and a restart in the middle of a
chain marks what was in flight `unknown` instead of guessing. The engine's own delay between a signal
and the `place_order` call is about **75 microseconds** (median).

## 2. What was done
- **Strategies** (`app/engine/strategies.py`): pure functions for direction and stake at each step, for
  `no_martingale`, `martingale`, `flip_every_loss`, `two_step_flip`. Stakes are rounded to the cent,
  half up, explicitly (D-22). A missing multiplier is an error, never reused.
- **Chain state machine** (`chain.py`): `pending → open → completed / exhausted / stopped / failed /
  unknown`, with the settings copied in when the chain starts so editing the group mid-chain changes
  nothing. It never awaits, so state cannot be interleaved with another task.
- **Executor** (`executor.py`): the hot path. Records a `pending` trade, sends the order, records it
  `open` with the broker id and the latency stamps, then awaits the result as an event with a timeout of
  expiry + 60 s. Refused → `failed`; sent but unconfirmed, no result, or an unexpected error →
  `unknown`; never retried. Refuses to trade if the account changed since the chain started.
- **ChainManager** (`manager.py`): creates chains from signals, applies decision D-9, drives each chain
  in a supervised task, publishes `chain.started/advanced/ended`, and does start-up recovery (D-35).
- **Engine** (`engine.py`, `factory.py`): the wiring Telegram → pipeline → manager → executor → adapter;
  `set_group` for when groups are created or edited; start/stop in the right order.
- **Application wiring** (`app/main.py`): the engine starts with the application **only if
  `ENGINE_ENABLED=true`** (default off, D-36).
- **Small changes elsewhere:** `Signal` now also carries the message text and id (so the manager can
  update the inbox row); `Settings.engine_enabled`.
- **Docs:** D-34, D-35, D-36, ARCHITECTURE layout, README "Running the trading engine", `.env.example`.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Strategy tables match `docs/DOMAIN.md` examples exactly, tests named after the examples | ✅ | `tests/unit/test_strategies.py`: `test_worked_example_flip_every_loss`, `…_two_step_flip`, `…_two_step_flip_with_n_4_the_next_would_be_call`, `…_martingale`, `test_win_at_step_2_of_flip_every_loss_matches_the_document` (in `test_chain.py`) |
| Integration: three groups, mixed strategies, overlapping chains, scripted wins/losses → correct directions, stakes, independence, final states | ✅ | `tests/integration/test_engine.py::test_three_groups_with_mixed_strategies_and_overlapping_chains` (4 chains at once, two of them in one group; exact order list per asset; final status, step and loss count of each chain) |
| New signal during an active flip chain is ignored and recorded with a reason | ✅ | `test_a_new_signal_during_an_active_flip_chain_is_ignored_and_says_why`, and the same row ends as `ignored` in the database: `test_a_run_ends_up_in_the_database_exactly_as_it_happened` |
| Restart mid-chain recovers and continues correctly, or marks `unknown` safely | ✅ (the "unknown" option, D-35) | `tests/integration/test_engine_persistence.py::test_restart_mid_chain_marks_everything_in_flight_unknown_and_frees_the_group` |
| Latency test shows the engine's own overhead (signal → `place_order`) in µs/ms | ✅ | section 8; `tests/integration/test_engine_latency.py` |
| No `sleep(duration + N)` or equivalent anywhere | ✅ | section 4 (grep) and `test_the_engine_never_sleeps_or_waits_a_fixed_time` |

## 4. Checks run
```
$ npm run check
ruff check: All checks passed!      ruff format: 120 files already formatted
mypy (strict): Success: no issues found in 67 source files
pytest: 529 passed in 19.64 s       vitest: 3 passed       vite build: built in 259 ms

$ grep -rn "sleep" backend/app/engine
engine.py: `sleep: Sleeper = asyncio.sleep` (passed to the pipeline: the wait until a signal's ENTRY
           TIME, not a wait for a result) and two docstring mentions
$ grep -rnE "sleep\(.*(duration|expir)" backend/app        ->  (no matches)
```
Mutation checks: I broke the engine on purpose in 15 ways (wrong flip parity, wrong rounding, one
follow-up too many, D-9 off, draw treated as a loss, ack timeout counted as "refused", chain row
published too early, group never released, recovery skipping chains / trades, no `pending` record,
no account check, settings not copied, …). All 15 are caught by a test.

## 5. Challenges and how they were resolved
1. **Two ordering bugs, found by tests, one of them silently corrupting.** The pipeline hands a signal
   to the engine *before* publishing the signal's inbox row (so orders never wait for bookkeeping).
   (a) The manager's "ignored: chain active" update therefore reached the database *before* the
   "parsed" row and was overwritten by it: the stored status would have been `parsed` for a signal that
   was in fact ignored. (b) `chain.started` also arrived first, and the chain row has a foreign key to
   the signal row, so the chain and then every one of its trades failed to save. The unit-level
   event-list test did not show (b); the test with the real database did. Fix: both events are published
   one event-loop turn later, still before the chain's first order (D-34).
2. **Test order of shutdown:** my first rig cancelled the DB writer before it had drained. The
   application's order (engine → writer → other tasks) is now used in the tests as well.
3. **Wrong test setups, not engine bugs:** stored group settings default to the OTC suffix, so my
   database tests traded `EURUSD_otc`, which the fake does not list; a clock earlier than the fixture
   dates. Fixed in the tests.
4. **Heredoc quoting in my shell** again; used file edits instead.

## 6. Deviations from the plan
- **Restart recovery marks everything `unknown` rather than continuing** (the criteria allow either).
  D-35 explains why; the owner can ask for the continuing variant later.
- **`ENGINE_ENABLED` flag** (D-36) is an addition: the scope says "wire … end to end using the fake
  adapter", which the tests do; wiring the real components into the application is behind a default-off
  switch so that starting the backend never logs in anywhere.
- **No payout or known-asset filter yet.** The minimum-payout rule and max-stake style limits are
  Phase 5 (`RiskGuard`); until then a closed or unknown asset simply ends the chain `failed`.
- **New decisions:** D-34, D-35, D-36.

## 7. Could not be verified
Everything real. The engine has only ever run on the fake Quotex and fake Telegram.
- A real order from a real signal, end to end, on the demo account (needs the Phase 2 and Phase 3 live
  checks first, then `ENGINE_ENABLED=true`).
- That a real lost trade arrives with a negative profit (open from Phase 2): the chain logic only depends
  on the won/lost label, but the profit shown in the trade rows depends on it.
- That Quotex's results arrive within expiry + 60 s in practice.
- The group list: groups cannot be created until the Phase 6 API, so the engine started by the
  application has no groups to listen to yet (the database could be filled by hand for a trial).

## 8. Measurements
Measured by `tests/engine_support.py::measure_latency`: one signal at a time into an engine on the fake
adapter, real clock, 3,000 samples each. "Signal → place_order" starts when the signal is handed to the
chain manager; "message → place_order" starts when the fake Telegram delivers the raw text (parser and
pipeline included). The fake adapter answers instantly, so Quotex's own network time is *not* included.

| | median | 99th percentile | 99.9th | worst |
|---|---|---|---|---|
| signal → `place_order` | 75 µs | 221 µs | 1.0 ms | 12 ms (one outlier) |
| message → `place_order` | 142 µs | 330 µs | 0.4 ms | 0.5 ms |

The test itself asserts only loose bounds (median < 2 ms, 99th percentile < 10 ms) so it cannot be
flaky; the numbers above are from this PC. A follow-up after a loss goes through the same code with no
parsing, so it is at or below the first figure plus the cost of bookkeeping the result.

## 9. New dependencies / files of note
No new dependencies. New: `app/engine/` (`strategies.py`, `chain.py`, `executor.py`, `manager.py`,
`engine.py`, `factory.py`); tests `test_strategies.py`, `test_chain.py`, `test_engine.py`,
`test_engine_persistence.py`, `test_engine_latency.py`, `engine_support.py`; three architecture rules
(no sleeping in the engine, no database access on its hot path, no knowledge of the API/Telethon).

## 10. Suggestions and open questions
- **Open trades after a restart** are only flagged. Quotex's history could settle them for real; the
  adapter would need a "closed orders" call (not in Phase 2). Worth doing before real money.
- **Draw:** I end the chain. If you would rather repeat the same step after a draw, say so.
- **Default expiry of 60 s** for signals without one is inherited from the old bot (Phase 3 §10).
- Several chains on the same asset in a non-flip group are allowed (they are independent); if you want
  at most one per asset and group, that is a small rule to add in Phase 5.

## 11. Git state
Before this phase you had committed Phase 3 (`607c145`). **At the owner's instruction for this session,
Phase 4 is committed and pushed**; nothing of Phase 5 is committed.

## 12. How to test it yourself
No account is needed for 1-3; I ran them before writing this.

**1. Everything**
```
npm run check
```
Expect `529 passed` (backend), `3 passed` (frontend), lint, types and build clean.

**2. The strategy tables and the end-to-end scenarios, readable**
```
cd backend
uv run pytest tests/unit/test_strategies.py tests/unit/test_chain.py tests/integration/test_engine.py -v
```
Every line `PASSED`; the names are the document's examples and the situations (for example
`test_three_groups_with_mixed_strategies_and_overlapping_chains`, `test_an_order_without_confirmation_is_unknown_and_never_retried`).

**3. The speed figure**
```
uv run pytest tests/integration/test_engine_latency.py -s
```
Prints `signal -> place_order … median … us`. Expect tens to a few hundred microseconds.

**4. LIVE (when you are ready; demo account only)**
1. Do the Phase 2 and 3 live steps first (Quotex demo diagnose, Telegram login).
2. A group must exist in the database (Phase 6 adds the screen for that); until then there is nothing
   to listen to.
3. Set `ENGINE_ENABLED=true` in `backend/.env`, run `npm run backend`, and watch the log lines
   `engine_started` and (per signal) the trades appear in `backend/data/quotex.db`.
Because the group screen does not exist yet, I suggest waiting for Phase 6 for this step.
