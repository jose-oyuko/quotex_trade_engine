# Phase 19 — The Deriv adapter (backend, not yet in the engine) — Report

**Date:** 2026-11-17
**Status:** Done. Built and tested against a local fake Deriv over a real WebSocket, then checked by the owner on
the real Deriv demo account (section 8): login, balance, assets, trade lengths, payouts and one demo trade with its
result. Three fixes came out of that live check (challenges 5 and 6). Open: a lost trade has not been seen live yet.

## 1. Summary
The application can now talk to Deriv through a second adapter with the same interface as the Quotex one:
- It logs in with your token.
- It reads the balance and the assets (forex pairs and synthetic indices) and the Rise/Fall trade lengths each
  asset allows.
- It reads the payout and places a trade.
- It waits for the result, reconnecting if the line drops.

Unlike Quotex, orders are **not** sent one at a time: two orders sent together each get their own
confirmation, whichever comes back first. Nothing in the engine uses Deriv yet; that is Phase 20.

A new command, `npm run deriv:check`, shows you on the demo account which assets Deriv offers you, which trade
lengths it allows, and what it pays. With `--order` it places one demo trade.

## 2. What was done

**A shared home for both brokers (`app/brokers/`)**
- `base.py` holds the adapter interface, now called `BrokerAdapter`; Quotex keeps the name `QuotexAdapter` for
  the same thing.
- `errors.py` holds the adapter errors. `app/quotex/errors.py` keeps the old names, so `QuotexError` is
  `BrokerError`.
- Two new errors: `LoginRejectedError` (a refused login, never retried) and `DurationNotOfferedError` (the
  trade length is not offered on that asset).
- `fake.py` holds the fake broker. `FakeQuotexAdapter` and the new `FakeDerivAdapter` are this fake under each
  broker's name.
- `Broker` (`quotex` / `deriv`) is in `app/domain/enums.py`, unused until Phase 20.

**Deriv (`app/deriv/`)**
- `login.py` turns your token and app id into a **one-time link** to Deriv's trading socket (section 5,
  challenge 1). It picks your demo account, or your one real account, and asks for a new link at every
  connect.
- `connection.py` is one WebSocket. Every request carries its own number (`req_id`) and its reply is matched
  by it, so any number of requests can be in flight. Subscriptions (balance, contract results) are routed by
  number and by subscription id.
- `adapter.py` is the `DerivAdapter`:
  - On connect it checks the account: the demo login must open a demo account (`VR...` or the new `DOT...`),
    the real one a real account; otherwise nothing is used and it does not retry.
  - It subscribes to the balance and reads the assets.
  - The payout comes from a price quote per asset and trade length, made when the asset is prepared and asked
    again every 30 s.
  - It checks the trade length before sending, and sends `buy`.
  - It follows the result with a subscription, made again after a reconnect.
  - Reconnects use the same backoff as Quotex. A ping every 30 s keeps the line open, and the asset list is
    refreshed every 5 minutes.
- `protocol.py` holds the pure rules:
  - our names to Deriv's (`EURUSD` → `frxEURUSD`; `R_75` stays `R_75`; `_otc` pairs do not exist);
  - reading trade lengths (`"15m"` → 15 minutes; tick trades, Higher/Lower and the "equal wins" variant left out; touching ranges joined);
  - payout percent, rounded down;
  - the profit of a finished contract;
  - errors;
  - demo or real.
- `factory.py` builds the adapter from the settings. `fake.py` is the fake for the engine tests (Deriv's
  lengths, no `_otc`, no draws).

**Settings and command**
- `DERIV_APP_ID`, `DERIV_TOKEN_DEMO`, `DERIV_TOKEN_REAL` and `DERIV_API_URL` are read from `backend/.env`, and
  are listed in `.env.example`. The tokens are secrets: masked in logs like the passwords.
- `npm run deriv:check` (`backend/scripts/deriv_check.py`): demo only. It shows the account, the assets by
  market, Deriv's own Rise/Fall entries and the lengths read from them, and payouts for EURUSD at 15 minutes
  and Volatility 75 at 1 and 5 minutes. `--order` places one demo trade.

**Tests**
- `tests/deriv_server.py` is a fake Deriv: a real local WebSocket server that answers in the shapes of Deriv's
  published schemas.
- `tests/integration/test_deriv_adapter.py` has 37 tests.
- `tests/unit/test_deriv_protocol.py`, `test_deriv_login.py` (Deriv's REST answers mocked),
  `test_deriv_factory_and_fake.py` and `test_deriv_check_script.py` hold the rest.
- Two new architecture rules: only `app/deriv/` talks to Deriv, and the two brokers do not import each other.

**Docs**
- DECISIONS.md: D-74, D-76 and D-77 amended for Deriv's current API (section 6).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Authorize and its refusal | ✅ | `test_a_refused_token_is_a_login_problem_not_a_network_one`, `test_the_built_adapter_asks_deriv_for_a_link_with_the_stored_token`, `test_connects_on_the_demo_account_and_reads_balance_and_assets` (there is no `authorize` call any more; see §6) |
| A real token in the demo slot refused | ✅ | `test_a_demo_token_that_opens_a_real_account_is_refused`, `test_a_link_to_the_wrong_kind_of_account_is_never_used`, `test_demo_and_real_accounts_are_told_apart` |
| A token with too many scopes refused | ⚠️ not possible | Deriv's API does not tell an application a token's permissions (§6); the guide will say "Trade only" (Phase 21) |
| A buy and its result: won, lost, equal exit = lost | ✅ | `test_a_synthetic_index_trade_at_one_minute_wins`, `test_a_loss_and_an_equal_exit_are_negative_and_lost`, `test_a_contract_is_settled_by_status_or_by_being_sold` |
| **Two orders in flight answered in reverse order, matched correctly** | ✅ | `test_two_orders_in_flight_answered_in_reverse_get_their_own_confirmation`, `test_many_concurrent_orders_all_get_their_own_id` |
| No confirmation = `OrderAckTimeoutError` | ✅ | `test_no_confirmation_means_the_order_may_have_been_placed`, `test_a_connection_lost_before_the_confirmation_may_have_placed_the_order` |
| A lost connection and reconnect | ✅ | `test_reconnects_with_backoff_after_a_drop`, `test_every_connection_uses_a_fresh_one_time_link`, `test_a_result_that_comes_during_a_reconnect_is_still_reported` |
| An unknown or `_otc` asset refused before sending | ✅ | `test_closed_unknown_or_otc_assets_are_refused_before_sending[AUDUSD/NOPE/EURUSD_otc]` |
| A synthetic index (`R_75`) bought and settled at 1 minute | ✅ | `test_a_synthetic_index_trade_at_one_minute_wins` |
| A forex pair at a length below its minimum refused before sending, with the reason | ✅ | `test_a_trade_length_the_asset_does_not_offer_is_refused_before_sending` ("it offers 15 min to 365 days") |
| Architecture test: only `app/deriv/` talks to Deriv | ✅ | `test_only_the_deriv_package_talks_to_deriv`, `test_the_two_brokers_know_nothing_of_each_other` |
| `ruff`, `mypy`, the whole test suite pass | ✅ | §4: 1442 passed (after the live fixes) |
| The owner's `npm run deriv:check` output in the report | ✅ | §8: run by the owner on the demo account, with `--order` |

## 4. Checks run
```
$ uv run ruff check . ; uv run ruff format --check . ; uv run mypy     (backend)
All checks passed!   278 files already formatted   Success: no issues found in 147 source files
$ pytest (the five Deriv test files, five times in a row)
87 passed (x5), about 8 s each
$ pytest (backend, whole suite)
1438 passed in 497 s (8 min 17 s): no failures (the report-speed test that is sometimes slow on this PC passed this time)
$ DERIV_APP_ID= DERIV_TOKEN_DEMO= npm run deriv:check
Cannot start: The Deriv app id and demo token are not set (DERIV_APP_ID and DERIV_TOKEN_DEMO in backend/.env).
$ pytest (backend, whole suite, after the live-check fixes in challenges 5 and 6)
1442 passed in 450 s (7 min 30 s): no failures
```

## 5. Challenges and how they were resolved
1. **Deriv changed its API.**
   - **Cause:** the plan (and D-74, D-76) assumed the long-standing `wss://ws.derivws.com/websockets/v3` socket
     with an `authorize` call. Before writing the code I read Deriv's current developer site and its JSON
     schemas. Authentication is now REST: the token and the app id fetch a one-time socket link for a chosen
     account. Several fields are renamed (`underlying_symbol`, `underlying_symbol_name`).
   - **Resolution:** built to the documented shapes, and recorded the changes as an amendment to the decisions.
   - **Remaining risk:** the schemas leave a few things unsaid, so the code is defensive about them:
     - whether stream updates repeat `req_id`: updates are also matched by subscription id, and there is a test
       for that;
     - the exact unit of `min_contract_duration`: an unreadable length is not guessed, and Deriv's own refusal
       decides;
     - the field that marks an account as demo: three checks, see D-76 amended.
2. **No quote stream on the Volatility indices.**
   - **Cause:** Deriv's schema says quotes are not streamed for under-24-hour Rise/Fall on R_10 to R_100.
   - **Resolution:** the payout comes from one-off quotes refreshed every 30 s. A quote that fails removes the
     figure, so nothing is ever traded on a stale payout.
3. **A test that failed only sometimes.**
   - **Cause:** the fake server handed out scripted results as each contract settled. On Windows the clock
     behind its timers moves in 15 ms steps, so two contracts settling "at the same time" could take each
     other's result. A debug run against the server showed the adapter itself matched results correctly.
   - **Resolution:** the server now fixes each contract's result when it is bought. The Deriv tests then
     passed five runs in a row.
4. **Moving the shared code without disturbing Quotex.**
   - **Resolution:** the interface, the errors and the fake moved to `app/brokers/`, and `app/quotex/` re-exports
     them under the old names, so no Quotex file or test needed a change. The only visible difference: an error
     raised as the plain base class (`QuotexConnectionError`) now shows its class name as
     `BrokerConnectionError` in a trade's reason text.
5. **Deriv's new demo account numbers.** Deriv's documentation shows a demo Options account as
   `DOT90004580`, but the account check only knew the old `VR...` numbering, so a real demo account would have
   been refused as "a real account" (found while helping the owner create a token).
   - **Resolution:** the account list is decided by Deriv's own `account_type` field first; account numbers
     are read as demo (`VR`, `DOT`), real (`CR`, `MF`, `MLT`, `MX`) or unknown. An unknown number is not
     refused on its own, because the list and the link have already said which kind the account is. A known
     number of the wrong kind is still refused. New tests: `test_a_new_style_demo_account_number_is_accepted`,
     `test_an_unknown_account_number_relies_on_the_list_and_the_link`, and more cases in
     `test_demo_and_real_accounts_are_told_apart`.
6. **No Rise/Fall found on the live demo.** The owner's first live `deriv:check` listed 95 assets but "none"
   for the trade lengths of EURUSD and R_75. The script was extended to print Deriv's unfiltered
   `contracts_for` answer, which showed that Deriv marks Rise/Fall (`callput`, `CALL`/`PUT`) with
   `barriers: 1` (the entry price), while the code expected 0. Higher/Lower has its own `higherlower` category.
   - **Resolution:** Rise/Fall is now recognised by category and type only. `callputequal` (an equal exit wins)
     stays out. Touching ranges are joined, so EURUSD reads "15 min to 365 days" and R_75 "15 s to 365 days".
     The fake Deriv server now sends the live shape; new test `test_the_live_eurusd_offer_reads_as_15_minutes_to_365_days`.

## 6. Deviations from the plan
- **Login:** a token fetches a one-time link; there is no `authorize` call. D-74 and D-76 are amended (see
  "D-74, D-76, D-77 amended in Phase 19" in DECISIONS.md).
- **Scopes:** "refuse a token with payments or admin scope" is not possible, because the API does not reveal a
  token's permissions. The guide will tell you to choose **Trade** only.
- **Payouts:** quotes are refreshed one-off instead of subscribed (challenge 2).
- **Where the tokens come from:** they are read from `backend/.env` for now. The plan said "filled from the
  encrypted store", but storing them there adds them to the dashboard's Settings page, which is Phase 21. Doing
  it now would have changed the dashboard early.
- No new decision numbers; the amendments are to D-74, D-76 and D-77.

## 7. Could not be verified — how to test it yourself

**A. Without any Deriv account (I ran these myself):**
1. Run `npm run deriv:check` with no Deriv lines in `backend/.env`. It prints
   `Cannot start: The Deriv app id and demo token are not set (DERIV_APP_ID and DERIV_TOKEN_DEMO in backend/.env).`
2. Run
   `uv run --directory backend pytest tests/integration/test_deriv_adapter.py tests/unit/test_deriv_protocol.py tests/unit/test_deriv_login.py tests/unit/test_deriv_factory_and_fake.py tests/unit/test_deriv_check_script.py -v`.
   It shows `87 passed`. The test names read as sentences: each one is a behaviour that holds.

**B. On your Deriv demo account (done by the owner on 2026-11-17, results in §8):**
1. On Deriv's developer site (developers.deriv.com), register an app; this gives you an **app id**.
2. In your Deriv account, create a **Personal Access Token** for your **demo** account with the **Trade**
   permission only.
3. Add two lines to `backend/.env`:
   ```
   DERIV_APP_ID=<your app id>
   DERIV_TOKEN_DEMO=<your token>
   ```
   Keep that file private: the token is as secret as a password.
4. Run `npm run deriv:check`. Success looks like this:
   - `[ok] connected`
   - `demo balance: ... USD`
   - the list of forex and synthetic assets
   - for EURUSD and R_75, `Deriv says: CALL intraday from '...' to '...'` and the trade lengths read from it
   - the payouts.

   If the lengths say `not readable`, Deriv writes them differently from the schema example. Send me those
   `Deriv says` lines and I will adjust the reading.
5. Run `npm run deriv:check -- --order`. It places one 1.00 demo trade on R_75 for 1 minute, then prints
   `contract ... confirmed`, the confirmation time, and after about a minute the result and balance. A lost
   trade must show a negative profit.
6. Send me the output of steps 4 and 5 (it contains no secrets), especially the payouts and the confirmation
   time.

## 8. Measurements
**Live, the owner's demo account, 2026-11-17** (`npm run deriv:check`, then `-- --order`, after the fixes in
challenges 5 and 6):
- Connected in 4.2 to 6.8 s (token → one-time link → socket → balance → assets). Demo balance 9997.16 USD.
- 95 assets: 25 forex pairs, 52 synthetic indices, 12 stock indices, 4 commodities, 2 crypto.
- Rise/Fall lengths: EURUSD **15 min to 365 days**; R_75 **15 s to 365 days** (tick trades left out).
- Payouts: EURUSD 15 min **81 %**; R_75 1 min **88 %**; R_75 5 min **88 %**.
- Demo trade: CALL R_75, 60 s, stake 1.00. Contract `20904571619` confirmed in **510 ms** (send → confirmation).
  Result **won, profit 0.88** (matches the 88 % payout); balance 9997.16 → 9998.04.
- Not seen live: a **lost** trade. The test with a scripted loss passes; the next live run that loses should show
  a negative profit (about -1.00).

Against the local fake, two orders sent together are both confirmed without waiting for each other; the real
gap between the two legs of a pair is measured in Phase 20 with `npm run latency`.

## 9. New dependencies / files of note
- **No new dependencies.** `websockets` and `httpx` were already installed.
- **New:**
  - `backend/app/brokers/` (`base.py`, `errors.py`, `fake.py`)
  - `backend/app/deriv/` (`login.py`, `connection.py`, `adapter.py`, `protocol.py`, `factory.py`, `fake.py`)
  - `backend/scripts/deriv_check.py`
  - `backend/tests/deriv_server.py`
  - the five test files above
- **Changed:**
  - `app/quotex/base.py`, `errors.py`, `fake.py` (now thin names over `app/brokers/`)
  - `app/core/config.py`
  - `app/domain/enums.py`
  - `.env.example`, `package.json`
  - `tests/unit/test_architecture_rules.py`
  - `docs/DECISIONS.md`

## 10. Suggestions and open questions
- **The payout depends on the stake a little on Deriv;** it is read at a 10.00 reference stake. If your stakes
  are far from that, we can read it at your base stake instead.
- **One open point for Phase 20:** your Deriv real account's currency is what stakes are in; a real account in
  another currency than USD would need its own limits.
- **The concurrent-order design here** (each request matched by its own number) is what Quotex would need too,
  if its library ever allows it.

## 11. Git state
**No commit was made for Phase 19.** You asked me to commit the plan (done: `3470a2f`) and then implement
Phase 19; committing Phase 19 itself waits for you. The changes are in the working tree (`git status`).
