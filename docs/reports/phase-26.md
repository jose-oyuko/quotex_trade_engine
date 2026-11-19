# Phase 26 — Price history: download and store — Report

**Date:** 2026-11-19
**Status:** Done; checked live against Deriv's real price service (section 7).

## 1. Summary

The engine can now download Deriv's past prices and keep them for backtests (decision D-84).
- **The source:** Deriv's public price socket (`wss://api.derivws.com/trading/v1/options/ws/public`). It
  needs **no token and no login**, and nothing is traded. Each download opens a connection of its own, so
  the trading engine's connection is never used or slowed.
- **The storage:** a separate file, `backend/data/history.db` (git-ignored). The trading database stays
  small.
- **Downloads:**
  - one at a time, in the background;
  - the parts already stored are skipped;
  - you can cancel one, and what it stored is kept;
  - a dropped connection is opened again (up to 5 times in a row) and the download goes on where it was;
  - progress is published live (`job.changed`), for the dashboard page of Phase 28.
- **From the terminal:** `npm run history:download -- --asset 1HZ75V --days 1`.
- **From the API:** `/api/v1/prices` (the dashboard page comes in Phase 28).

## 2. What was done

- **Shared types** (`app/brokers/history.py`): `PriceHistory` opens a `PriceFeed`, which answers one page
  of ticks; `PriceHistoryError` says whether trying again can help (`retryable`).
- **Deriv** (`app/deriv/history.py`): `DerivPriceHistory`, Deriv's `ticks_history` request over a
  `DerivConnection` of its own. The request and answer shapes are pure functions in `app/deriv/protocol.py`
  (`ticks_history_request`, `parse_ticks_history`). The engine factory builds it
  (`build_price_history`), so only `app/deriv/` talks to Deriv (D-74).
- **The fakes:** `FakePriceHistory` / `FakePriceFeed` make up prices (the same for the same asset and
  second), for tests and for `npm run demo`. The fake Deriv server of the tests gained the public socket
  and `ticks_history`, including a smaller page than asked, refusals and dropped connections.
- **The store** (`app/backtest/store.py`): plain SQLite in a worker thread.
  - `ticks` keyed by asset and second; `coverage` keeps the seconds already downloaded as ranges, because
    an index ticking every 2 s, or a closed market, has seconds without a price.
  - `downloads` records each download.
  - A download still marked running when the application starts was cut by a stop: it is marked failed,
    and what it stored is kept.
- **The service** (`app/services/price_history.py`):
  - it asks for pages from the newest to the oldest, each one ending just before the oldest price of the
    one before;
  - each page is stored and recorded at once;
  - it waits 0.3 s between requests (Deriv allows about 220 a minute);
  - it reports where Deriv's history starts when a long stretch has no price.
- **API:**
  - `GET /prices`, `GET /prices/downloads`, `POST /prices/downloads` (202);
  - `POST /prices/downloads/{id}/cancel`, `DELETE /prices/{asset}`;
  - errors `invalid_download`, `download_running`, `download_not_found`, `asset_downloading`;
  - the WebSocket gains `job.changed`, and the dashboard's live feed knows it (otherwise it would take
    each one for a gap and resync).
- **Setting:** `DERIV_PUBLIC_WS_URL` (in `.env.example`). **Script:** `npm run history:download`.
- **Guides:** API.md (the routes and `job.changed`). The how-to guides come with the page in Phase 28.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Paging over more than one page | ✅ | `test_more_than_one_page_is_downloaded_from_the_newest_to_the_oldest` (12,001 prices, 3 requests) |
| A smaller page than asked leaves no hole | ✅ | `test_a_page_smaller_than_asked_for_does_not_leave_a_hole` (live Deriv answers 1,000, below) |
| A partly held range downloads only the gap | ✅ | `test_only_the_part_not_yet_stored_is_downloaded` |
| Cancel stops it and keeps what was stored | ✅ | `test_cancel_stops_a_download_and_keeps_what_it_stored`, API test |
| A dropped connection | ✅ | `test_a_dropped_connection_is_opened_again_and_the_download_goes_on`, `test_a_connection_that_keeps_dropping_fails_and_keeps_what_was_stored` |
| The start of Deriv's history is reported | ✅ | `test_the_start_of_deriv_s_history_is_reported` |
| Deriv's refusal and an asset it does not have | ✅ | `test_deriv_s_refusal_and_an_asset_it_does_not_have_fail_with_the_reason` |
| Only `app/deriv/` asks Deriv for prices | ✅ | `test_only_the_deriv_package_asks_deriv_for_past_prices`, and the layer rule for `app/backtest` |
| API: start, 409, list, cancel, delete; progress events | ✅ | `test_api_prices.py` (2 tests), events checked in the download tests |
| 100,000 prices without holding the event loop over 100 ms | ✅ | `test_storing_many_prices_never_holds_the_event_loop` |
| `ruff`, `mypy`, the whole test suite | ✅ | Section 4 |
| Live: a day of `1HZ75V` and `R_75`; how far back the history goes | ✅ | Section 7 |

## 4. Checks run

```
$ uv run ruff check . ; ruff format --check . ; mypy      clean
$ uv run pytest --deselect tests/integration/test_reports_performance.py
                                      1574 passed (the performance test deselected, as before)
$ npx vitest run                      38 files, 475 tests passed
$ npm run lint ; npm run typecheck    clean
$ npm run api:generate                openapi.json and schema.d.ts regenerated
```

## 5. Challenges and how they were resolved

1. **The public socket's limits are not documented.** A probe showed Deriv answers **at most 1,000 prices
   per request**, whatever `count` asks for. The downloader never relies on the page size: it always asks
   again from just before the oldest price it got, until a request comes back empty.
2. **Deriv sends *today's* prices for a period older than its history** (asked for 365 days ago, it
   answered with prices from today), with no error. Every page is filtered to the period asked for, so
   those prices are never stored, and the empty stretch is reported as "Deriv has no prices from … (its
   history starts later)".
3. **The first live download lost its connection after 13 requests** (the same network as on the
   18th). A 30-request probe right after had no drop. A dropped connection is now opened again up to 5
   times in a row (2, 4, 8… s apart), and the download goes on from the last stored page. The second run
   then fetched only the part still missing.
4. **Only `app/deriv` may talk to Deriv, and only the engine factory may name it** (rule 6). So the
   download service sees the broker-neutral `PriceHistory` type, and `build_price_history` lives in
   `app/engine/factory.py`.

## 6. Deviations from the plan

- **The routes are `/prices`, not `/history`.** "History" already means the trade history on the
  dashboard.
- **The terminal command does not mark the dashboard's running download as failed** at its start
  (`prepare(cut_running=False)`): both can use the file at the same time.

## 7. Live check (run by the agent; no login, nothing traded)

| | `1HZ75V` | `R_75` |
|---|---|---|
| one day downloaded | 86,244 prices (13,000 in the first, cut, run + 73,244 in the second) | 43,122 prices (one every 2 s) |
| time | 2 min (the missing part) | 1 min 23 s |
| history reaches back | 364 days | 364 days |

`frxEURUSD` also answered for 7, 30 and 90 days ago (none on a Saturday 180 days ago, as expected for
forex). The prices are in your `backend/data/history.db`.

**How to try it yourself:** `npm run history:download -- --asset 1HZ75V --days 1`. It prints progress, then
`done: N new prices stored`. Run it again: it says `0 new prices` almost at once (everything is held).

## 8. Measurements

- About 0.75 s per request of 1,000 prices on this connection (with the 0.3 s pause), so **a day of a
  1-tick-a-second index takes about a minute** and a 31-day download about half an hour. A day of `R_75`
  (one tick every 2 s) takes half that.
- The store holds a day of a 1-tick-a-second index (86,400 prices) in about 2.5 MB.

## 9. New dependencies / files of note

No new dependencies.
- New files: `app/brokers/history.py`, `app/deriv/history.py`, `app/backtest/store.py`,
  `app/services/price_history.py`, `app/api/routers/prices.py`, `app/api/schemas/prices.py`,
  `scripts/history_download.py`.
- New tests: `tests/unit/test_price_store.py`, `tests/integration/test_price_downloads.py`,
  `tests/integration/test_api_prices.py`.

## 10. Suggestions and open questions

- Deriv's history is about a year deep. Downloading a few weeks of the indices you trade is enough for
  the backtests of Phase 27.

## 11. Git state

Committed with your permission ("commit and start the phases, till the end"): see STATUS for the hash.
