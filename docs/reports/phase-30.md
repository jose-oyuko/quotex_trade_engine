# Phase 30 — The Market page — Report

**Date:** 2026-11-20
**Status:** Done. Checked on `npm run demo`. Your look at the chart in a browser is pending (section 7),
and so is your verdict on whether the consolidations are the ones you mean.

## 1. Summary

The dashboard has a **Market** page (menu: *Market*). It draws the stored Deriv prices as candles and
marks what the engine finds:
- **The chart:**
  - any stored asset, by name;
  - timeframes M1, M5, M15, M30, H1 or any number of seconds;
  - drag to scroll, wheel or pinch to zoom, more candles loading as you scroll;
  - *Go to* a date and time.
- **Find consolidations:**
  - the period (up to 31 days), the pattern (yours, *alternating 5*, by default, or one of the four
    others) with its settings, and the breakout rule;
  - then *Scan*.
- **On the chart:**
  - each consolidation is a box from its range's low to its high;
  - each breakout is an arrow;
  - the trend after it is shaded green (up) or red (down) until the next consolidation.
- **Below the chart:**
  - the statistics in words, including whether trends differ from any moment beyond noise;
  - the list of consolidations, where *Show* moves the chart to one and outlines it.

Everything marked comes from the server's scan (Phase 29), so the page shows exactly what a backtest or
a live session would use.

## 2. What was done

- **New:** `frontend/src/features/market/`:
  - `MarketPage.tsx`: the page, the candle loading in chunks of 1,000, the jumps;
  - `CandleChart.tsx`: the chart, wrapping TradingView Lightweight Charts;
  - `zones.ts`: drawing the boxes and the shaded trends, as a chart plugin whose geometry is plain
    functions;
  - `ScanForm.tsx`, `FoundList.tsx`;
  - `marketSchema.ts`: timeframes, chunks, UTC times, the form's checks, the statistics in words;
  - tests `marketSchema.test.ts` (7), `zones.test.ts` (3), `MarketPage.test.tsx` (6).
- **Changed:**
  - `api/client.ts` (`api.market`), `api/queries.ts` (`useMarketPatterns`), `api/types.ts`;
  - `app/router.tsx` (`/market`), `app/Layout.tsx` (menu item), `index.css` (`.candle-chart`);
  - `package.json` (the chart library).
- **Docs:** OPERATIONS ("Consolidations and trends": the page), STATUS.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| The timeframe switch | ✅ | `draws the newest stored candles, and other timeframes on request` (M1, M5, 90 s) |
| The date jump | ✅ | `jumps to a date and loads the candles around it` |
| The settings form and its checks | ✅ | `scans with the chosen definition and marks the chart from the answer`; `marketSchema.test.ts` |
| The list | ✅ | same test: rows, breakout, trend after |
| Clicking a row asks the chart to show and mark it | ✅ | `shows a consolidation on the chart when its row is chosen` |
| The marks are drawn from the API's answer, not recomputed | ✅ | same scan test: the boxes, bands and arrows equal the fixture's values |
| `eslint`, `tsc`, `vitest`, build, `api:check` | ✅ | Section 4 |
| Self-test on `npm run demo` | ✅ | Section 4 |
| Your check: a dozen consolidations on M1 and M5, "that is what I mean" | ⏸ | Section 7 |

## 4. Checks run

```
$ npm run lint ; npm run typecheck ; npm run format:check     clean
$ npx vitest run                         44 files: 505 passed, 2 failed (App.test, the known timing
                                         flake under a full run)
$ npx vitest run src/app/App.test.tsx    15 passed
$ npm run build                          built; the Market page is its own chunk (191 kB, 63 kB gzipped)
$ npm run api:check                      schema.d.ts is up to date
$ backend                                unchanged since the Phase 29 suite
```

**Demo self-test** (`npm run demo -- --port 8765`, made-up prices; port 8000 is your own app, left
alone):
- logged in; `/market` serves the page;
- a day of `1HZ75V` downloaded;
- the five patterns listed;
- 24 M5 candles for two hours;
- a day scanned on M1 in 0.22 s (32 consolidations, 31 trends);
- `R_75` without prices refused with `invalid_market`.

The demo was stopped afterwards.

## 5. Challenges and how they were resolved

1. **The chart cannot run in the test browser** (it draws on a canvas). The page tests use a stand-in
   chart that records what the page asks it to draw and show. The drawing geometry (`zoneRects`) is
   tested on its own. Whether the real chart draws it well needs a real browser: your check.
2. **Loading candles as you scroll.** The chart asks for candles in chunks of 1,000, around what is on
   screen plus one chunk each side. Older candles arriving do not move the view.
3. **A PowerShell edit damaged two test files' characters** ("↑" became "â†‘"). They were repaired, and
   no damaged character is left in the code.

## 6. Deviations from the plan

- **The library's size:** the plan said about 45 kB; the whole Market page with the library is 63 kB
  gzipped. It loads only when the page is opened.
- **"Where a backtest's pairs were opened"** on the Market page belongs to Phase 31, as planned.

## 7. Could not be verified (your check)

1. Start the app (`npm start`) and open **Market** in the menu.
2. Choose *Volatility 75 (1s) Index (1HZ75V)*: two weeks are stored (29 Oct to 5 Nov and 12 to
   19 Nov).
3. **The chart:**
   - drag it, zoom it, switch M1 / M5;
   - *Go to* `2026-11-15 10:00`.

   Expected: the candles follow, with no gaps where prices are stored.
4. **Scan** the default period (the last stored day) with your definition (*alternating*, 5 candles, 2
   breakout candles by close).
   - Expected: boxes over the consolidations, arrows at the breakouts, green or red shading after them.
5. **Click *Show*** on a dozen rows, on M1 and then M5 (scan again after switching).
   - Tell me for each whether it is a consolidation the way you mean it, and what you would mark
     differently.
   - Try the other patterns too: the boxes change at once.
6. **Your decision for Phase 31.** Phase 29's figures say the trends after a breakout are no calmer than
   any moment. Shall I build the trend backtests anyway (real trades replayed, to confirm), adjust the
   definition first, or stop here?

## 8. Measurements

- A day's M1 scan through the API: 0.22 s (demo).
- A chart chunk of 1,000 M1 candles reads about 60,000 prices of a 1-second index.

## 9. New dependencies / files of note

- **`lightweight-charts` 5.2.1** (TradingView, Apache 2.0): the candlestick chart, approved by you on
  2026-11-20.
  - Pinned exactly, released 12 Aug 2026; 5.3.0 is only ten days old, too new for the project's rule.
  - Its one dependency, `fancy-canvas` 2.1.0, is by the same authors.
  - The library shows a small TradingView logo on the chart, as its licence asks.
  - `npm audit` reports 7 moderate issues; all are in the lint tools, and none comes from this
    library.

## 10. Suggestions and open questions

- **Phase 31 or not** (section 7, step 6).
- **A faster chart:** building candles in SQLite instead of Python (Phase 29 suggestion) would help
  long M1 views if scrolling feels slow.

## 10b. Follow-up (owner's request, 2026-11-23): clear rectangles around consolidations

The owner asked for a rectangle showing where each consolidation is.

**A real bug was behind it: the boxes were never drawn.**
- A screenshot of the page in a real browser (headless Edge on the demo) showed only the breakout
  arrows: no boxes and no trend shading.
- Cause: the chart library converts only whole candle positions to pixels and quietly answers 0 for
  anything in between. The box edges sit half a candle before a candle (positions like 47.5), so every
  box came out 0 pixels wide and was skipped.
- The page tests had not caught it, because their stand-in chart accepted any position.

**Now:**
- **The fix:** the edges are worked out from whole candle positions (`edgeX` in `zones.ts`). A test now
  copies the library's rule (whole positions only), so this cannot slip by again.
- **Each consolidation is an amber outlined rectangle** (2 px), from its range's low to its high with a
  few pixels to spare, so the wick tips stay visible. It is labelled above "Consolidation · 18 candles"
  ("18 candles" when narrow). The one chosen with *Show* is outlined in blue.
- **The trend shading** is drawn under the rectangles.
- **The scan runs by itself** when the page opens (the last stored day, with the definition in the
  form) and again when the asset or timeframe changes. The rectangles are there without pressing
  *Scan*.
- **Checked in a real browser:** headless Edge screenshots of the demo before and after: none before;
  after, the rectangles with labels, and the blue one after *Show*.
- **Checks:** `vitest` 44 files, 508 passed (the page tests now expect the automatic scan and the
  labels); `eslint`, `tsc`, `format:check` and the build are clean.
- **Committed** with your word ("you can commit it", 2026-11-24).

## 11. Git state

Committed with your permission ("commit the plan phases and get to work"): see STATUS for the hash.
