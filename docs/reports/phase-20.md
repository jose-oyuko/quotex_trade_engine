# Phase 20 — Two brokers in the engine (backend) — Report

**Date:** 2026-11-17
**Status:** Done, tested on fakes. Not yet run live with both brokers (section 7): that needs `npm start` with
your logins, which I do not run.

## 1. Summary
Quotex and Deriv now trade side by side in one engine:
- Every group and every trading session has a **broker** (`quotex` or `deriv`; everything that existed is
  Quotex). Its chains and trades go to that broker and carry its name in the database.
- The engine starts **whichever brokers have logins** (at least one). The demo/real switch and the real-money
  permission cover both.
- Results, **daily limits** and figures are **kept apart per broker**: a Deriv loss never counts towards a
  Quotex stop-loss.
- **One broker down does not stop the other.** A signal for a broker that is down, or that does not offer the
  asset or the trade length, is skipped before anything starts, with the reason in the inbox (for example
  "Deriv does not offer 1 min Rise/Fall on EURUSD: it offers 15 min to 365 days").
- A Deriv session on a synthetic index (R_75 at 1 minute) sends **both legs of a pair together**: Deriv does
  not make the second order wait for the first's confirmation.
- **Stopping can no longer hang** on a broker that does not answer (the Ctrl+C problem of 2026-11-13).

The dashboard does not show the broker yet (no picker in the forms, one balance on the Live page): that is
Phase 21. Until then a Deriv group or session is created through the API (section 7).

## 2. What was done
- **Database (migration `0007`):** a `broker` column on groups, trading sessions, chains, trades and balance
  snapshots; existing rows read `quotex`. New indexes by broker and account type. The records carry the field,
  and the writer, repositories and recovery pick it up without other changes.
- **Broker interface:** one new method, `order_refusal(asset, length)`: why the broker would surely refuse the
  order, from memory. Deriv answers for `_otc` pairs, unknown or closed assets, and trade lengths the asset does
  not offer. Quotex answers nothing new (its closed assets are refused at the order, as before).
- **Deriv adapter:** after connecting, it learns the trade lengths of every open asset in the background, five
  assets a second, so the check above works from memory for any signal.
- **Executor:** one adapter per broker; each trade goes to its chain's broker. A broker without a login fails
  the order with that reason.
- **Chain manager:** each group's broker is kept with its settings. Before a chain starts (group signal or
  session leg) it asks the executor whether the broker can take it: no login, not connected, or the broker's
  refusal → the signal is ignored with the reason.
- **Risk guard:** the day's results are kept per (broker, account type) and per (broker, account type, group).
  Global stop-loss, profit target, open-trade count and exposure are checked per broker; messages say which
  ("the day's result on Deriv ..."). Group limits are unchanged.
- **Session scheduler:** checks connection, asset, trade length and payout on the session's own broker, and
  prepares the asset there.
- **Engine:**
  - `adapters` per broker; `account_type`; `brokers_in_use()` (enabled groups and sessions).
  - The switch moves every broker or none.
  - Stopping cancels every connect loop first, then closes each broker with a 10 s limit.
- **Factory and logins:** builds Quotex when its email and password exist, Deriv when its app id and demo
  token exist; with neither it refuses and says both. The engine page's login list shows Deriv's three items
  (from `backend/.env` for now); Quotex's are needed only when Deriv's are missing, and the other way round.
- **Sessions:** the API takes `broker`. A Deriv session takes Deriv's names (`R_75`, `1HZ100V`, `EURUSD`) and
  refuses `_otc`. When the engine is running and knows the asset, a trade length the asset does not offer is
  refused on saving. The hidden group gets the session's broker.
- **API:**
  - `broker` on groups (in and out), sessions (in and out), chains and trades.
  - Status: `balances`, one per broker for the account in use. `balance` stays (Quotex's, or the only broker's).
  - The day's result: `by_broker` next to `pnl` (now described as the total).
  - Health: a `deriv` connection, and "… is not connected" for each broker in use.
  - `openapi.json` and the dashboard's types regenerated. The dashboard forms keep a group's or session's
    broker unchanged when edited (new ones are Quotex) until Phase 21 adds the picker; the test fixtures have
    the new field.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| A Quotex group and a Deriv group trade at once; results, limits and figures stay apart | ✅ | `test_a_quotex_group_and_a_deriv_group_trade_at_once_and_their_results_stay_apart`, `test_the_daily_stop_loss_counts_each_broker_on_its_own` |
| One broker down does not stop the other | ✅ | `test_one_broker_down_does_not_stop_the_other` |
| A Deriv session on a synthetic index at M1 sends both legs of a pair together | ✅ | `test_a_deriv_session_on_a_synthetic_index_sends_both_legs_of_a_pair_together` |
| A Deriv group's 1-minute forex signal is skipped with the minimum-length reason | ✅ | `test_a_deriv_groups_one_minute_forex_signal_is_skipped_with_the_minimum_length` |
| Migration up and down; existing data reads as Quotex | ✅ | `test_existing_rows_read_as_quotex_when_the_brokers_arrive`, `test_models_and_migrations_agree` |
| `ruff`, `mypy`, the whole test suite pass | ✅ | §4: backend 1473 passed; frontend 443 passed |

Also tested:
- the switch, all or nothing: `test_the_demo_real_switch_moves_every_broker_or_none`;
- stopping never hangs: `test_stopping_gives_up_on_a_broker_that_does_not_close`,
  `test_stopping_ends_a_login_that_is_still_retrying`;
- a broker with no login: `test_a_group_on_a_broker_without_a_login_is_skipped_and_says_so`;
- a Deriv session whose length the asset does not offer: rounds skipped with the reason, and refused on saving
  (`tests/unit/test_session_broker_checks.py`);
- Deriv's trade lengths learned in the background, and `_otc`, unknown and closed assets refused from memory
  (`tests/integration/test_deriv_adapter.py`, last two tests);
- the engine built from logins, Quotex, Deriv, both or neither (`tests/unit/test_engine_factory.py`);
- the API: a group's broker (`test_a_group_trades_on_quotex_unless_deriv_is_chosen`), Deriv sessions
  (`test_a_deriv_session_takes_deriv_names_and_its_hidden_group_trades_there`,
  `test_a_deriv_session_refuses_otc_pairs_and_quotex_refuses_deriv_names`);
- the health banner per broker (`test_a_broker_that_is_down_is_named_and_one_that_is_up_is_not`).

## 4. Checks run
```
$ uv run ruff check . ; uv run ruff format --check . ; uv run mypy        (backend)
All checks passed!   281 files already formatted   Success: no issues found in 147 source files
$ pytest (backend, whole suite)
1473 passed in 584 s (9 min 44 s)
  (an earlier run had 2 failures: test_connection_loss, which expected the old "chain fails" behaviour
   and was updated (section 6); and the report-speed test, 4.4 s against a 4 s limit while the PC was
   busy. Run alone on the last commit it took 5.2 s, so the PC was slow, not this change; run alone on
   this phase it passed at 3.6 s)
$ npm run api:check ; npm run lint ; npm run typecheck ; npm run build   (frontend)
up to date ; clean ; clean ; built
$ npx vitest run   (frontend, from C:\...)
443 tests: 442 passed, 1 failed (App.test "marks the current page", the known flaky one);
App.test.tsx run alone: 14 passed
```

## 5. Challenges and how they were resolved
1. **Many existing tests build the engine with one adapter.** The engine still accepts `adapter=` (taken as
   Quotex) next to the new `adapters=`, so those tests did not change. Five lines that read
   `engine.adapter` now read `engine.adapters[Broker.QUOTEX]`.
2. **Knowing Deriv's trade lengths before a signal arrives.** A group signal can name any asset, and asking
   Deriv at that moment would put a round trip on the order path. The adapter now asks for every open asset in
   the background after connecting (paced, five a second), so the check is a dictionary lookup.
3. **The test settings must never read your `.env`,** which now holds your Deriv token. Checked: the test
   settings are built with `_env_file=None`, and the new factory tests use made-up values.
4. **The dashboard's types became stricter** once the API had `broker`; the forms now send the broker the item
   already has, so editing a Deriv group from today's dashboard does not move it back to Quotex.
5. **Vitest would not start at all** ("Cannot read properties of undefined (reading 'config')" in every file).
   Running the same tests on the last commit worked, which ruled out my changes. The cause: my shell had opened
   the folder as `c:\...` (small drive letter), which makes vitest load itself twice on Windows. Run from
   `C:\...` it works. Nothing to change in the project.
6. **I damaged `frontend/node_modules` and repaired it.** To compare with the last commit I made a temporary
   copy of the repository that linked to the real `frontend/node_modules`. Removing that copy with git deleted
   `node_modules/.bin` through the link before it stopped on a too-long path. I removed the link to the project
   root inside `node_modules` (so nothing could reach the repository) and ran `npm ci`, which reinstalled the
   packages exactly as `package-lock.json` lists them. Afterwards: `git status` unchanged, `backend/.env` in
   place, lint, typecheck, tests and build pass. `npm ci` also reports "7 moderate severity vulnerabilities" in
   the dev packages: the same lockfile as before, nothing new was added.

## 6. Deviations from the plan
- **Quotex signals while Quotex is down** are now skipped with "Quotex is not connected" instead of starting a
  chain that fails at once. Same outcome (nothing is sent), clearer reason, and the rule is the same for both
  brokers.
- **The old account-type indexes stay** next to the new broker ones, because today's reports still filter by
  account type only. They can go in Phase 21, when the reports filter by broker.
- **Only one session runs at a time, across both brokers** (as D-71 says). Running a Quotex and a Deriv session
  at the same time would be a change to the scheduler: see Suggestions.
- All of these are written under "D-75 settled in Phase 20" in `DECISIONS.md`.

## 7. Could not be verified — how to test it yourself

**A. Without any account (I ran these):** the whole suite, and the new tests alone:
`uv run --directory backend pytest tests/integration/test_engine_brokers.py -v` → `11 passed`.

**B. Both brokers on the demo accounts (not run: it needs your logins and starts the real application):**
1. Keep your Quotex login (dashboard or `.env`) and add Deriv's to `backend/.env` (you already have
   `DERIV_APP_ID` and `DERIV_TOKEN_DEMO`).
2. `npm start`, open the dashboard and start the engine. Settings should list the Deriv items as `.env`.
3. Open `http://127.0.0.1:8000/api/v1/health` (use your own port if it is different): `quotex` and `deriv`
   both show `"connected": true`.
4. Open `/api/v1/status`: `balances` lists two demo balances, Quotex's and Deriv's (about 9998 USD).
5. Make a Deriv session through the API page `/docs` (logged in on the same browser), **POST /api/v1/sessions**
   with your usual session body plus `"broker": "deriv"`, `"asset": "R_75"`, `"duration_s": 60`, a window that
   is open now, and a small stake. Then **POST /api/v1/sessions/{id}/start**.
6. On the Live page the pair's two chains appear. Both orders went to Deriv (they are on your Deriv demo
   statement). Then `npm run latency`: the two legs of each pair should be within a few hundred milliseconds of
   each other.
7. Try the length rule: the same session with `"asset": "EURUSD"` and `"duration_s": 300` is refused on saving
   with "it offers 15 min to 365 days".
8. Ctrl+C: the application stops within seconds, even if Quotex is stuck logging in.

## 8. Measurements
None live. On the fakes, a Deriv pair's second order goes out without waiting for the first one's confirmation
(test above); the real gap is step 6 of section 7.

## 9. New dependencies / files of note
- **No new dependencies.**
- **New:** `backend/alembic/versions/0007_brokers.py`, `tests/integration/test_engine_brokers.py`,
  `tests/unit/test_session_broker_checks.py`, this report.
- **Changed (main ones):** `app/engine/{engine,executor,manager,risk,factory,logins,chain,controller}.py`,
  `app/sessions/scheduler.py`, `app/services/{sessions,groups,live}.py`, `app/api/{health,snapshot,views}.py`,
  the group, session, record, status and risk schemas, `app/db/models.py`, `app/domain/{records,enums}.py`,
  `app/brokers/{base,fake}.py`, `app/deriv/{adapter,fake,protocol}.py`, `app/quotex/pyquotex_adapter.py`,
  `docs/openapi.json`, `frontend/src/api/schema.d.ts`, the group and session form schemas and test fixtures.

## 10. Suggestions and open questions
- **Reports add up both brokers' money today** if both are used, because they filter by account type only.
  Phase 21 adds the broker filter (planned); until then, read the reports with that in mind.
- **Two sessions at once on different brokers** (a Quotex one and a Deriv one in the same hours) is not possible
  yet; tell me if you want it, it is a scheduler change.
- **Deriv's tokens in the dashboard** (stored encrypted, like the Quotex login) are Phase 21.

## 11. Git state
**No commit was made for Phase 20.** Committing waits for you. The changes are in the working tree
(`git status`).
