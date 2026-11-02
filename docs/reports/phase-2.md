# Phase 2 — Quotex adapter — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes; the **live checks
(real Quotex, demo account) have not been run** and are yours to do (section 7).

## 1. Summary
There is now one clean interface to Quotex (`QuotexAdapter`), a real implementation on pyquotex 1.1.0,
and a scriptable fake for everything else. The real adapter connects, watches the connection and
re-connects with backoff, answers balance/payout/open-or-closed questions from memory, sends orders
one at a time, and waits for results by event. I read the library's source first, which showed that its
normal `buy()` would repeat the old bot's latency problem (a network call and up to 0.2 s of polling on
every order), so the adapter sends orders its own way. The same behavioural tests pass against the fake
and the real adapter, and the real library was exercised end to end against a local fake Quotex
server. **What I could not do is talk to the real Quotex**: I have no account and did not use yours.

## 2. What was done
- **Interface** (`app/quotex/base.py`): `QuotexAdapter` with `connect`, `disconnect`, `state`,
  `account_type`/`set_account_type`, `balance()`/`refresh_balance()`, `payout(asset, minutes)`,
  `is_open(asset)`, `prepare_asset`, `place_order(asset, direction, duration_s, amount) -> OrderAck`,
  `await_result(order_id, timeout_s) -> TradeResult`. Connection-state changes are published on the
  event bus as `connection.changed`; balance changes as `balance.updated` (so Phase 1's
  `balance_snapshots` table fills itself). Money is `Decimal` throughout.
- **Real adapter** (`pyquotex_adapter.py`): connection life cycle, reconnect with exponential backoff
  (1 s doubling to 30 s, ±10 % jitter), safety checks, one-at-a-time order sending.
- **The only library-facing module** (`pyquotex_client.py`): small, no decisions. Behind a seam
  (`client.py`) so the adapter's logic is tested without the library.
- **Fake** (`fake.py`): same rules and errors as the real one; scriptable results (win/loss/draw or an
  exact profit), delays, held orders, failures, connection loss, wrong-account simulation; keeps a
  balance and an order log.
- **Safety:** demo by default; REAL needs `QUOTEX_ALLOW_REAL=true` **and** an explicit switch; an order
  is refused if the connection is on a different account than the adapter believes; closed/unknown
  assets and malformed stakes are refused before anything is sent; payout data is checked (0–100,
  expected row layout) and fails loudly (D-12).
- **Settings:** `QUOTEX_EMAIL`, `QUOTEX_PASSWORD` (secret strings, never printed), `QUOTEX_HOST`
  (default `quotex.com`, validated as a bare domain), `QUOTEX_ALLOW_REAL`, `QUOTEX_TIME_MODE`.
- **Diagnostic** (`backend/scripts/quotex_diagnose.py`, `npm run quotex:diagnose`): demo only; shows
  balance and payout; `--order` places one demo order and prints the measured latency and result.
- **Docs:** decisions D-26…D-29, README section "Quotex connection", `.env.example`.

### What reading pyquotex 1.1.0 showed (facts that shaped the design)
| Finding in the library | What the adapter does |
|---|---|
| `Quotex.buy()` first calls `start_realtime_price()` (polls for a price tick every 0.2 s) and `get_server_time()` (an HTTP download of the profile) **on every order**. That is the old bot's D-14 problem, now async but still a network round trip per order. | Subscribes to an asset's prices once (`prepare_asset`), then sends via `api.buy`. The server-time offset it fetches is not part of the order message anyway (expiry comes from the local clock). |
| One shared "order confirmed" slot. Two orders in flight could receive each other's confirmation. | A lock covers *send → confirmation* only (about a millisecond on loopback); waiting for results is outside it. |
| `buy()` waits `duration + 5` s for the confirmation. | We wait `ack_timeout` (10 s) and report "may have been placed". |
| `check_win()` answers **"loss" after a fixed 300 s**. Wrong for long expiries. | Not used; the adapter waits on the library's per-order result slot and raises `ResultTimeoutError`. |
| `session.json` (cookies + token) is written into the **current directory**, whatever `root_path` says. | Redirected into `backend/data/` (git-ignored). A test proves nothing is written to the working directory. |
| After a rejected login the dead token stays on disk; every later attempt would load it again. | The wrapper clears it so the next attempt logs in afresh. |
| A login that needs an email PIN calls `input()` — that would freeze the whole app. | Unattended: fails with an explanation. The diagnostic asks in the terminal. |
| pyquotex's own websocket auto-reconnect competes with ours. | Turned off; the adapter is the single owner of reconnecting. |
| Every profit ≤ 0 is labelled "loss"; there is no draw. | Same rule (`classify_profit`), see open item 7.2. |

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Contract tests run against the fake and define the behaviour the real adapter must match | ✅ | `tests/contract/test_adapter_contract.py`: 27 tests × 2 implementations (fake, real-adapter-with-scripted-library) = 54 |
| Unit tests: reconnect/backoff | ✅ | `test_pyquotex_adapter.py::test_a_lost_connection_is_re_established_with_backoff` (delays `[1, 2]`), `…retry_forever_backs_off_exponentially…` (`[1, 2, 4, 8]`), `test_quotex_parsing.py::TestBackoff` (cap 30 s, jitter ±10 %), account survives reconnect |
| Unit tests: timeout on missing result | ✅ | contract `…waiting_for_a_result_times_out_without_pretending_a_loss`; replay `…unsettled_order_times_out…` (real library) |
| Unit tests: payout sanity check | ✅ | `test_quotex_parsing.py::TestInstrumentPayout` (−1, 100.5, 101, 8700, None, "85", True, NaN, wrong layout), `…bad_payout_data_stops_the_payout_read_loudly` |
| No module outside `app/quotex/` imports `pyquotex` | ✅ | `test_architecture_rules.py` (also: inside the package only `pyquotex_client.py` does; the check is shown not to be vacuous) |
| *(live)* Diagnostic connects to demo, shows balance and payout | ⏸ not verifiable by me | steps in section 12 |
| *(live)* One demo order placed and settled; `place_order` latency recorded and compared to the old bot's problem | ⏸ not verifiable by me | steps in section 12. Offline figure in section 8 |

## 4. Checks run

```
$ npm run check                      (repo root)
ruff check                           All checks passed
ruff format --check                  77 files already formatted
eslint / prettier --check            clean
mypy (strict, 43 source files)       Success: no issues found
tsc --noEmit                         clean
pytest                               259 passed in 17.5 s (no warnings)
vitest                               3 passed
vite build                           built
```
Extra checks of the tests themselves: I deliberately broke the adapter three ways (dropped the
wrong-account guard; removed the order lock; counted any profit as a win) and the suite failed each
time; the code was restored and passes.

## 5. Challenges and how they were resolved
1. **The obvious implementation (`Quotex.buy()`) reintroduces the old latency problem** — found by
   reading the source, not by measuring. Resolution: send orders via the lower-level `api.buy` and move
   the one-time price subscription out of the order path (D-27).
2. **A shared confirmation slot makes simultaneous orders unsafe**, which matters because several
   groups can signal in the same second. Resolution: serialise send→confirmation with a lock; a test
   (`max_in_flight == 1`) and a mutation check prove it. Cost: simultaneous orders queue for each
   other's confirmation round trip.
3. **The library cannot be tested offline as shipped.** Resolution: a local websocket server speaking
   the frames pyquotex itself parses (including its "placeholder" flow) lets the *real* library run
   through connect, order, result, rejected login and a dropped connection with no network or account.
4. **Running the diagnostic for real found a bug the tests could not**: `python scripts/x.py` does not
   put `backend/` on the import path, so `app` was not found. Now run as a module
   (`python -m scripts.quotex_diagnose`).
5. **The first draft of two tests had wrong expectations** (an event list that forgot the "connecting"
   event; a balance sum that forgot the stake is returned with the winnings). The code was right; the
   tests were corrected. A third test queued failures before the first connect and so tested the wrong
   thing; restructured.
6. **No `websockets` dependency declared** although the replay server uses it (it only came in through
   uvicorn). Added as an explicit dev dependency.
7. **Windows event loop:** curl_cffi (used by pyquotex) does not support the default Windows
   `ProactorEventLoop` natively; version 0.17 compensates with a helper thread and prints a warning.
   Everything works under it (all replay tests run on it). Remaining risk: unverified on the live service.

## 6. Deviations from the plan
- **Account guard in the adapter (`allow_real`, `QUOTEX_ALLOW_REAL`)** is a small piece of Phase 5's
  "account-type guard", added because rule 4 (default to demo, never trade real by accident) applies
  to the adapter from its first line. Phase 5 still owns refusing a switch while chains are open.
- **`timeout` parameters are named `timeout_s`** (lint rule + consistency with `duration_s`).
- **Server-time offset:** the plan says "cached and warmed at startup". The library's offset (from the
  profile download) is fetched once at warm-up and kept in the client, but nothing uses it: the order
  message does not carry it. I did not build clock-skew measurement on top. See Suggestions.
- `payout(asset, minutes)` supports Quotex's two published figures (1-minute and 5-minute): expiries
  under 5 minutes use the first, 5 and longer the second. That mapping is a judgement; the diagnostic
  prints both so you can compare with the website.
- New decisions: **D-26, D-27, D-28, D-29** in `docs/DECISIONS.md`. New dependency: `websockets`
  (dev only, tests).

## 7. Could not be verified
Everything below needs your Quotex account (demo) — I did not use credentials and sent nothing to the
real service. See section 12 for the exact steps.
1. **That the adapter works against the real Quotex at all** (login, websocket, the exact frames).
   The local server follows how pyquotex *parses* messages, not a recording of real traffic.
2. **Loss vs. draw.** pyquotex labels profit ≤ 0 as "loss". If Quotex reports a lost trade as profit
   `0` (not `−stake`) or a refunded trade as `0`, the adapter cannot tell them apart. The diagnostic
   prints the raw profit: after a **losing** demo trade it should read about `−stake`. If it reads
   `0`, tell me; this affects martingale follow-ups (Phase 4).
3. **Real latency of `place_order`** and the comparison with the old bot (section 8).
4. **The payout mapping** (1-minute and 5-minute figures from fixed list positions) and whether the
   price-subscription step is actually required by Quotex before an order (the library's own wrapper
   does it, so we do too, once per asset).
5. **Expiry mode.** `TIME` (library default, clock-aligned: a "60 s" order placed at second 45
   expires at the end of the *next* minute) vs `TIMER` (true countdown). Which one matches how your
   signals are meant to be traded needs your confirmation; `QUOTEX_TIME_MODE` switches it.
6. **Login with an emailed PIN** and Cloudflare behaviour: only visible live.

## 8. Measurements
| What | Result | How |
|---|---|---|
| `place_order` send → confirmation, adapter + real library, **loopback** (server answers instantly) | median **1.6–1.8 ms**, max 2.1–2.8 ms (20 orders) | `npm run test:backend -- tests/integration/test_quotex_library_replay.py -s` |
| Same on the real service | **not measured** (needs live) | `npm run quotex:diagnose -- --order` prints it |
| Old `Quotex.buy()` path | **not measured.** By reading the source it adds one HTTP request plus ≥ one 0.2 s polling step per order; the adapter avoids both | source: `pyquotex/_api/trading.py`, `account.py`, `realtime.py` |

The loopback figure is the *software overhead only*. Real latency = this + the round trip to Quotex,
which only the live run can show. The first order for each asset also pays for the price subscription
(`prepare_asset`); call it ahead of time (Phase 4 can do so when a signal's entry time is in the future).

## 9. New dependencies / files of note
- Dependency: `websockets` (dev only; the test server). No new runtime dependencies (`pyquotex` was
  pinned in Phase 0).
- `backend/app/quotex/` — `base.py`, `errors.py`, `parsing.py`, `backoff.py`, `client.py`,
  `pyquotex_client.py`, `pyquotex_adapter.py`, `fake.py`, `factory.py`
- `backend/app/core/errors.py` (`DomainError`), `backend/app/core/config.py` (Quotex settings)
- `backend/scripts/quotex_diagnose.py`
- `backend/tests/` — `contract/`, `quotex_support.py`, `quotex_replay_server.py`, 7 new test files

## 10. Suggestions and open questions
- **Clock skew:** the order's expiry comes from the PC clock (library behaviour). A PC clock that is
  seconds off could put an order on the wrong expiry. Worth a check in the diagnostic and, in Phase 9,
  a warning at startup (compare with the server timestamps that arrive with price ticks).
- **Pre-warm assets:** Phase 4 should call `prepare_asset` as soon as a signal is parsed (before its
  entry time) so no order pays for it.
- **History lookup for recovery:** the library can list past trades, which would let Phase 4 settle
  trades that expired while the app was down. Not built (it is recovery logic, Phase 4).
- **Windows loop policy:** setting the selector loop policy at startup would remove curl_cffi's helper
  thread and warning. Not done: it changes the whole app's event loop and needs live testing with
  Telegram too. Decide in Phase 9.
- **Open question for you:** `TIME` or `TIMER` expiry (item 7.5).

## 11. Git state
**I made no commits and staged nothing.** Your latest commit is `310c3f5` (Phase 1 and the toolchain
upgrade are in it); everything in this phase is uncommitted in the working tree. Changed:
`.env.example`, `README.md`, `package.json`, `backend/app/core/config.py`, `backend/pyproject.toml`,
`backend/uv.lock`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/STATUS.md`. New:
`backend/app/core/errors.py`, `backend/app/quotex/`, `backend/scripts/`, `backend/tests/contract/`,
and the test files listed above. No secrets in the tree (the only credential-looking strings are
obviously fake values inside tests); `backend/data/` was removed after my manual runs.

---

## 12. How to test it yourself

All commands from the repository root. Steps 1–4 need no account; I ran each of them first and the
output below is what I saw. Steps 5–7 are the live checks I could not do.

**1. Everything at once**
```
npm run check
```
Expect: `259 passed` (backend), `3 passed` (frontend), no lint/type errors, build OK.

**2. The shared behaviour tests, both implementations, readable**
```
npm run test:backend -- tests/contract -v
```
Expect 54 `PASSED`, each test name twice: `[fake]` and `[real]`, e.g.
`test_an_order_on_the_wrong_account_is_never_sent[real]`.

**3. The real library against the local fake Quotex (reconnect, orders, results)**
```
npm run test:backend -- tests/integration/test_quotex_library_replay.py -v -s
```
Expect 13 `PASSED` including `test_a_dropped_websocket_is_noticed_and_re_established` and
`test_a_rejected_session_fails_and_forgets_the_stored_token`, plus one line
`[benchmark] place_order send->ack on loopback ...` (a couple of milliseconds).

**4. The diagnostic's error handling (safe: nothing is sent to Quotex)**
```
npm run quotex:diagnose
```
Expect: `Cannot start: QUOTEX_EMAIL and QUOTEX_PASSWORD must be set (in backend/.env)`.
Then, in PowerShell, with a name that cannot exist:
```
$env:QUOTEX_EMAIL="x@example.invalid"; $env:QUOTEX_PASSWORD="x"; $env:QUOTEX_HOST="quotex-does-not-exist.invalid"; npm run quotex:diagnose; Remove-Item Env:QUOTEX_*
```
Expect in about 3 s: `[FAILED] QuotexConnectionError: DNSError … Could not resolve host`, followed by the
hint to set `QUOTEX_HOST`. (It leaves a harmless `backend/data/session.json`; delete `backend/data`.)

**5. LIVE — connect and read (demo account, no money at stake)**
Create `backend/.env` containing (use your own values; the file is git-ignored):
```
QUOTEX_EMAIL=you@example.com
QUOTEX_PASSWORD=your-password
QUOTEX_HOST=quotex.com
```
```
npm run quotex:diagnose
```
Success looks like:
```
Host: quotex.com   Account: DEMO (this script never uses real)
[ok] connected and warmed up in N.NN s
[ok] demo balance: <your demo balance>
[ok] EURUSD is open
[ok] payout EURUSD 1m: NN%
[ok] payout EURUSD 5m: NN%
```
If Quotex emails you a PIN, type it at the `PIN>` prompt. Compare the payout figures with the Quotex
website. If the market is closed (weekend) use an OTC asset: `npm run quotex:diagnose -- --asset EURUSD_otc`.

**6. LIVE — one demo trade, with timing**
```
npm run quotex:diagnose -- --order --asset EURUSD_otc --amount 1 --duration 60
```
Success looks like `[ok] order … confirmed: place_order took NNN ms total`, then, after about 1–2 minutes,
`[ok] result: won|lost, profit …`. **Please send me the two timing lines and the result line.**
Run it until you have seen **one losing trade** and check its profit reads about **−1.00** (item 7.2).

**7. LIVE — check the domain/session handling**
Run step 5 a second time: it should connect noticeably faster and not ask for a PIN (stored session in
`backend/data/session.json`). Never share that file.

**Clean-up:** delete `backend/data/` to forget the stored session.

---

_After writing this report: update `docs/STATUS.md`, give the owner a short summary, and stop._
