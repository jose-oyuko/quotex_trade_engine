# Phase 8 — Reports — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes, on fakes and on a
generated database of 100,000 trades. The reports have never seen a real trade and the CSV has not
been opened in a real Excel (section 7).

## 1. Summary
A **Reports** page answers "is this really working?". It shows profit, win rate, return on stakes,
the biggest drawdown, streaks, a profit curve, the result split by group, asset, strategy, hour of
day and weekday, how deep chains go and what each step costs, and a plain-language comparison of the
win rate with the **break-even line** that refuses to draw conclusions from too few trades. Demo and
real money are never mixed. Every figure shows its sample size and a label ("too few trades", "small
sample"), and trades whose result is unknown are listed as "not counted" instead of quietly
disappearing. Everything can be downloaded as CSV for Excel. The numbers come from SQL aggregations
and were checked against hand-computed values and against a second, independent implementation on
random data; they stay between about 0.2 and 2.6 seconds on 100,000 trades.

## 2. What was done

**Backend** (`backend/app/reports/`, `app/api/routers/reports.py`, `app/api/schemas/reports.py`)
- `models.py` — the definitions (D-47): resolved trades, profit, win rate, ROI, the sample-size labels,
  `expectation_of` (break-even win rate, z-score, verdict).
- `queries.py` — `summary` (totals, not-counted, streaks, drawdown), `breakdown` (group, asset, strategy,
  hour, weekday), `equity` (daily running total), `depth` (chain depth and cost), `export_trades` (streamed).
  Money is summed by the database as integer cents.
- `sql.py` — the hour / weekday / day of a stored UTC time on the owner's clock, written for SQLite
  with a PostgreSQL branch (not run: no PostgreSQL yet).
- `csvout.py` — Excel-safe CSV (D-49).
- Endpoints: `GET /reports/summary | breakdown | equity | depth` and `GET /reports/export/trades.csv |
  breakdown.csv`, all with the same filters (account, from/to, group, strategy, asset, utc offset).
  The Phase 6 placeholder (501) is gone.

**Dashboard** (`frontend/src/features/reports/`, `components/charts/`)
- `ReportsPage` with a filter bar (account, period presets and custom dates, group, strategy, asset),
  `SummaryPanel`, `EquityPanel` (line chart + numbers), `BreakdownPanel` (five tabs, bar chart + table,
  faded rows for tiny samples), `DepthPanel`, downloads with a comma/semicolon choice.
- `BarChart` and `LineChart`: plain SVG (D-48, the chart-library decision), each with a spoken
  description and an accompanying table.
- `lib/dates.ts` (calendar days on the owner's clock → UTC instants), `lib/reportText.ts` (the wording).

**Docs:** D-47, D-48, D-49; `docs/API.md` "Reports"; README; ARCHITECTURE.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Aggregation tests against a seeded database with hand-computed expected values | ✅ | `tests/integration/test_reports.py` (33 tests) on the 13-trade history in `tests/reports_support.py`, whose table lists every trade and whose comments show each calculation (e.g. "drawdown: highest point 1.40 (Mon), lowest after it -7.60 -> 9.00"). Also `test_reports_reference.py` (22): every report against a plain-Python reimplementation on 2,500 random chains across 8 filter combinations |
| Report queries stay fast on a seeded database of 100k trades (record the timings) | ✅ | section 8 (`test_reports_performance.py`) |
| CSV export opens correctly in Excel (UTF-8 BOM / delimiters verified) | ⚠️ verified by bytes, not by Excel | `test_api_reports.py`: file starts with `EF BB BF`; CRLF line ends; comma and semicolon versions parse back to the same rows; accents (`Señales Ñandú €`) survive; dot decimals; formula text defused; checked on the byte stream of the running demo too. I could not open it in Excel (section 7) |
| Date range filters | ✅ | inclusive start / exclusive end at the second (`test_the_range_is_inclusive…`), zones written as `+03:00` (`test_the_filters_narrow_the_numbers`), naive times and backwards ranges refused (422) |
| Demo and real reported separately | ✅ | `test_real_money_is_reported_on_its_own`; every endpoint and the page take one account; mutation "demo and real mixed" caught |
| Aggregations: P/L, win rate, average payout, drawdown, by group/asset/strategy/hour/weekday, chain depth, streaks, expected-vs-actual | ✅ | each has hand-computed tests above |
| Report pages with charts; sample size clearly labelled | ✅ | `ReportsPage.test.tsx` (22), `Charts.test.tsx` (14); screenshot `phase-8/reports.png` |

## 4. Checks run
```
$ npm run check
api:check  up to date                ruff: All checks passed!   ruff format: 180 files already formatted
mypy (strict): no issues in 101 source files            tsc --noEmit + eslint + prettier: clean
pytest: 881 passed in 135 s (includes the 100,000-trade test)   vitest: 290 passed (21 files)   vite build: built
```
Mutation checks (broken on purpose, a test must fail): **35 backend breakages** (range ends, unresolved
trades counted, demo/real mixed, group/strategy filters, wins/profit columns, drawdown peak, streak
reset on a draw, hour/day/weekday offsets and formula, hour padding, sort order, the SQL cache key,
depth reaching/open chains/account, pending counted as open, break-even formula, the z threshold both
ways, small-sample guard, sample thresholds, CSV BOM/formula defusing/separator/line ends/step
numbering/money format/created-time range, API default account, naive times, backwards range) and
**25 dashboard breakages** (day arithmetic, plural, charts' zero line and signs, label thinning,
faded rows, quiet hours, filters not sent, offset ignored, CSV link options, percent): **all caught.**
The first pass left 14 un-applied, 2 survivors and later 4 survivors; each exposed a missing test
(pending trade as "open", the 1-to-2 standard-error band, the CSV range being the creation time, an
all-negative chart, the browser's offset) or dead code (a redundant day check, removed). Details in
section 5.

## 5. Challenges and how they were resolved
1. **A real bug, found by the random test on its first run.** SQLAlchemy caches the SQL of a statement
   by its structure, and my "hour / weekday / day" element did not include which part and offset it
   was, so the hour query's cached SQL was served to the weekday query (a weekday of "7"). The hand-made
   tests, which ran one report each, did not trigger it; comparing every breakdown in one session
   against the reference did. Fixed by making `part` and the offset part of the cache key, with a test
   that asserts nine different statements have nine different keys.
2. **A broken Phase 5/6-style placeholder test** (`/reports/summary` → 501) became wrong when the
   endpoint became real: removed, and the endpoint inventory test now lists the five new routes.
3. **My own hand-calculation slipped once** (a daily total of -6.60 instead of -5.60); the code was
   right and the literal wrong. Worth saying: that is why the daily/offset cases also run in the
   differential test.
4. **Speed.** First measurements: CSV 6.1 s, summary 1.4 s. Reading raw column values instead of
   converting every cell through the ORM types, and one CSV writer per batch instead of per row, took
   the 85,000-row export to about 3 s. The chain-depth report (about 2.5 s) is two joins of 58,000
   chains with their trades; left as is (section 8).
5. **Test environment dependence (again).** A test counted on `frontend/dist` not existing; fixed in
   Phase 7. Here: the mutation tool had to cope with Windows line endings in files written by scripts.
6. **The shell's quoting problems** (large here-documents) made me move to file writes for scripts.

## 6. Deviations from the plan
- **Charts without a library** (D-48), where the plan said "choose and record the chart library". It is
  a recorded choice (two simple chart types, tiny, testable, accessible) that you can overturn.
- **Hour/weekday use a fixed UTC offset**, not a zone with daylight saving (D-47): an hour is off by one
  for part of the year in such zones.
- **The expected-vs-actual comparison is against the break-even win rate** (D-47), because the groups'
  claimed win rates are not stored anywhere; it is the one benchmark that needs no assumption.
- New decisions: **D-47, D-48, D-49.**

## 7. Could not be verified
- **Excel itself.** I verified the file's bytes (BOM, CRLF, delimiters, encoding) and that it parses
  back, not that your Excel shows it correctly. *Manual check:* run `npm run demo`, open Reports,
  press "Download all trades (CSV)", double-click the file: you should see one column per field and
  correct text. If everything is in one column, use "Semicolon (;)" instead.
- **Real trades.** The reports have run on fakes and on generated data only. In particular they rely on
  a lost trade being stored with a **negative profit** (Phase 2 §7); if Quotex reports a loss as 0 the
  profit figures will be too high. The first demo-account trades on the real Quotex will show it.
- **PostgreSQL.** `sql.py` has a PostgreSQL branch written to the same contract; it is checked only by
  reading the SQL it produces (a test), not by running it.
- **Browser time zone / daylight saving:** the offset is read from the browser; tested with a mocked
  offset, not on a machine in another zone.

## 8. Measurements
`tests/integration/test_reports_performance.py`, run with `-s`: 100,000 trades in 58,244 chains
(about 82,000 resolved demo trades), 120 days, on this PC; two runs on an otherwise idle machine
(the figures move by up to 2x with machine load):

| Report | run 1 | run 2 |
|---|---|---|
| summary (totals + streaks + drawdown) | 1,812 ms | 1,294 ms |
| breakdown by group / asset | 476 / 234 ms | 234 / 241 ms |
| breakdown by strategy | 1,200 ms | 642 ms |
| breakdown by hour / weekday | 612 / 618 ms | 381 / 351 ms |
| daily profit curve | 975 ms | 980 ms |
| chain depth | 2,545 ms | 2,646 ms |
| summary, filtered (one group, a range) | 169 ms | 170 ms |
| chain depth, filtered | 498 ms | 570 ms |
| trades CSV, every demo trade (15.3 MB) | 3,542 ms | 2,948 ms |

Seeding the 100,000 trades takes about 18 s (not part of the figures). The test fails only if a report
takes over 4 s. These are comfortable for a page opened now and then; the heaviest ones scale with
the number of trades (the summary and the curve are one pass over every resolved trade). If a record
ever grows to millions of trades, the first optimisation is a daily summary table, kept up to date
as trades settle.

## 9. New dependencies / files of note
No new dependencies (SVG charts, D-48). New: `backend/app/reports/{models,queries,sql,csvout}.py`,
`app/api/{routers,schemas}/reports.py`, tests `test_reports*.py`, `test_api_reports.py`,
`test_reports_sql.py`, `test_reports_expectation.py`, `reports_support.py`;
`frontend/src/features/reports/`, `components/charts/`, `lib/{dates,reportText}.ts`.

## 10. Suggestions and open questions
- **A daily summary table** if the history ever becomes huge (section 8).
- **Per-group "claimed win rate"** so the report can compare a group's promise with its result.
- **Real-account report warning** when profit figures rely on the unconfirmed loss sign (section 7).
- **Excel file (.xlsx)** with formatting instead of CSV, if you prefer.
- **Alert** when a strategy goes significantly below break-even (needs the engine to read the report).

## 11. Git state
Committed as `feat: reports (Phase 8)` once the checks passed (see `git log`).

## 12. How to test it yourself
No accounts needed. I ran 1–3 myself (the screenshot came from it).

**1. All checks:** `npm run check`.

**2. See reports on a database with activity:**
```
npm run build
npm run demo -- --reset --interval 1
```
Leave it for two or three minutes (it posts a signal a second, trades settle after 15 s), then open
<http://127.0.0.1:8000/reports>.

**3. Things to try**
| Step | Expected |
|---|---|
| Top of the page | "Summary": a label such as "small sample" or "enough trades" with the trade count; before 30 trades a yellow note says to treat figures as a hint |
| "Is it really working?" box | With few trades "Not enough trades to tell"; with more, a sentence comparing the win rate with the break-even line (for example "At the average payout of 85.0%, a trade has to win 54.1% of the time...") |
| Tabs under "Where the result comes from" | Bars green for profit, red for loss; groups with few trades are faded and labelled "too few trades" |
| Period → "Today", then "Custom dates" with the end before the start | Today narrows everything; the backwards range shows a message and asks nothing |
| Account → "Real money" | Empty ("No trades in this period for this account"): the demo has no real trades. Demo and real are never added together |
| Group / Strategy / Asset | Every panel narrows together |
| Download all trades (CSV) → open in Excel | One column per field, `1.00`-style numbers, correct text. If everything is in one cell, choose "Semicolon" and download again |
| Dev tools (F12) → Network → `summary` | Money is text (`"-2.50"`); filters you set appear in the address |

**4. The numbers, checked by someone else:** `cd backend` then
`uv run pytest tests/integration/test_reports.py -v` prints each hand-computed case by name; open
`backend/tests/reports_support.py` to see the table of trades they are computed from.

**5. Timings:** `uv run pytest tests/integration/test_reports_performance.py -s` (takes about a minute).

Screenshot: [phase-8/reports.png](phase-8/reports.png).
