# Phase 28 — The Backtest page — Report

**Date:** 2026-11-19
**Status:** Done. Checked on `npm run demo`; your look at the page in a browser is pending (section 7).

## 1. Summary

The dashboard has a **Backtest** page (menu: *Backtest*), which brings Phases 26 and 27 together.
- **Price history:**
  - what is stored per asset (prices, oldest and newest, periods downloaded) with *Delete*;
  - a download form (asset, from, to) whose progress shows live, with *Cancel*;
  - the recent downloads with their notes and errors.
- **New backtest:**
  - the session fields, or *Copy the setup of a session*;
  - up to six strategies, each with its multipliers ("2, 4, 8" = three steps);
  - the assumptions (payout %, order delay, step delay);
  - a warning when the chosen days are not (fully) downloaded.
  The form checks what the server checks, including the 8-step limit of growing flip.
- **Results:**
  - a table comparing the strategies (profit, worst drawdown, largest stake, most money in play, chains
    won and lost, most lost in a row, trades, skipped rounds, how the windows ended);
  - for each strategy, its running profit and how its chains ended (won at step k / lost every step);
  - the chain list, filtered by strategy and result, with every trade's entry and exit price;
  - the past backtests, which you can open, cancel or delete;
  - every result states its assumptions and that "a backtest is not a prediction".
- **Live updates:** progress arrives over the WebSocket (`job.changed`); the page also polls while
  something runs.
- **Guides:** OPERATIONS ("Backtests"), DOMAIN (§7 Deriv's past prices, §8 the replay rules),
  ARCHITECTURE (§6 the history file), DECISIONS (D-84 settled), API (Phases 26–27).

## 2. What was done

- **New:** `frontend/src/features/backtest/`:
  - `BacktestPage.tsx`, `PricesPanel.tsx`, `BacktestForm.tsx`, `BacktestResult.tsx`, `backtestSchema.ts`;
  - tests `backtestSchema.test.ts` (6) and `BacktestPage.test.tsx` (6).
- **Changed:**
  - `api/client.ts` (`api.prices`, `api.backtests`), `api/queries.ts` (5 hooks), `api/types.ts`;
  - `app/router.tsx` (`/backtest`), `app/Layout.tsx` (the menu item);
  - `index.css` (`.plain-list`);
  - `api/live.test.ts` (a `job.changed` message is passed on, not taken for a gap).
- **The charts** are the ones the Reports page already uses (`LineChart`, `BarChart`): no new library.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| The download form, its progress and Cancel | ✅ | `lists the stored prices and starts a download`, `shows a running download with its progress and cancels it` |
| The backtest form: validation, the 8-step limit, several strategies | ✅ | `runs a backtest with several strategies and opens it`, `refuses a 9th growing flip step before sending anything`, `backtestSchema.test.ts` |
| The server's refusal shown in words | ✅ | `shows the server's refusal in words` |
| The results table and charts from a fixture; the chain list | ✅ | `shows a finished backtest: the comparison, the assumptions and the chains` |
| `eslint`, `tsc`, `vitest`, build, `api:check`, the backend suite | ✅ | Section 4 |
| Self-test on `npm run demo` | ✅ | Section 4 |
| Owner: download a week, run your session's setup with all five strategies | ⏸ | Section 7 |

## 4. Checks run

```
$ npx vitest run                      40 files, 488 tests passed
$ npm run lint ; typecheck ; format:check ; build      clean
$ npm run api:check                   schema.d.ts is up to date
$ backend                             no backend code changed since the Phase 27 suite
                                      (1602 passed + the fixed file, 29 passed)
```

**Demo self-test** (`npm run demo -- --port 8765`, fake brokers and made-up prices):
- logged in; `/backtest` serves the page;
- a day of `1HZ75V` downloaded (86,401 made-up prices);
- 9 growing flip steps refused (422);
- a 12-hour backtest with all five strategies, a pair at every candle (3 open at most), done in 0.4 s;
- a growing flip chain that lost every step went, on its PUT leg, Sell, Buy, Sell, Sell, Buy, Buy, Sell,
  Sell, Sell.

The demo ran on port 8765 because port 8000 was in use (your own app, which I left alone).

## 5. Challenges and how they were resolved

1. **The setup is both what the page sends and what it reads back,** so the API schema has two versions
   of it (`BacktestIn-Input` and `-Output`). The form's type uses the input one.
2. **Two live-feed files edited in Phase 26 were not run through the format check then;** only their
   line endings differed. They are formatted now, and the check is clean.

## 6. Deviations from the plan

- None. "Copy from a session" is a choice in the form, as planned for this phase.

## 7. Could not be verified (your check)

1. Start the app (`npm start`) and open **Backtest** in the menu.
2. **Price history:** download a week of `1HZ75V` (about 7 minutes). Expected: the bar fills, and the
   table then shows the asset with its period.
3. **New backtest:**
   - *Copy the setup of a session* (your Deriv session), or fill it in;
   - add the strategies you want to compare;
   - *Run the backtest*.
   Expected: the run shows in the list, then its comparison, charts and chains.
4. **Tell me** if anything reads wrongly or a figure looks off.

## 8. Measurements

The page's code adds its own chunk, loaded only when the page is opened. The replay timings are in the
Phase 27 report (a month of 1-second prices with five strategies: 23 s).

## 9. New dependencies / files of note

No new dependencies. Files in section 2.

## 10. Suggestions and open questions

- **Replaying stored Telegram signals** (the "backtester over stored messages" in the backlog) could
  reuse the same replay for groups, on the signals of Deriv assets.
- **Optimising the multipliers automatically** was left out as planned. Comparing a few choices side
  by side (up to six per run) covers most of it.

## 11. Git state

Committed with your permission ("commit and start the phases, till the end"): see STATUS for the hash.
