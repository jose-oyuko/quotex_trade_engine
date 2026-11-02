# Phase 7 — Dashboard v1 (React) — Report

**Date:** 2026-11-02
**Status:** Done with open items — the dashboard works end to end against the fake Quotex and fake
Telegram (I ran it and took the screenshots below); it has not run against the real services or in a
real desktop browser session of yours (section 7).

## 1. Summary
The dashboard is a working control room. **Live**: balance, today's result, chains running (with step
progress and their controls), trades open (with a countdown to expiry) and the signal-to-order speed,
all updating by themselves from the WebSocket. **Signals**: every message, what became of it and why.
**Groups**: add, edit, enable/disable, pause and delete groups; the form has exactly one multiplier
input per step and checks every one. **History**: all trades with filters and paging. The header of
every page shows DEMO or REAL MONEY unmistakably, Telegram/Quotex connection state, and the kill
switch. Everything that cannot be undone asks first and says which account it applies to. The built
dashboard is served by the backend itself (one process, one port), and `npm run demo` runs the whole
thing on simulators so you can try it with no accounts.

## 2. What was done

**Screens** (`frontend/src/features/`)
- `live/` — `LivePage`, `StatsPanel`, `ChainsPanel` (stop after current, skip to base), `OpenTradesPanel` (countdown).
- `signals/` — `SignalsPage` / `SignalsTable` (untrusted text shown as plain text).
- `groups/` — `GroupsPage`, `GroupFormPage`, `GroupForm` + `groupSchema` (React Hook Form + Zod), server errors shown on the matching field.
- `history/` — `HistoryPage` (filters: group, result, account; page sizes 25–200).
- `controls/` — `KillSwitch` (confirm to engage and to release), `AccountBadge`.

**Plumbing**
- `live/LiveProvider` + `live/applyEvent` — the WebSocket drives the TanStack Query cache (decision D-43): snapshots replace it, events patch it (batched once per animation frame), lists are marked stale only when an event concerns them. Reconnect and re-sync come from the Phase 6 `LiveSocket`.
- `app/` — shell (`Layout`), routes with lazy page loading, `ErrorBoundary`, providers.
- `components/` — `Modal` (focus trap, Escape, focus restore), `ConfirmDialog`, `DataState` (loading / error with retry / empty), `Pagination`, `Countdown`, `Badge`, `Money`, `Button`.
- `api/queries.ts` — the query hooks; money is only ever handled as text (`lib/format.ts`).

**Backend, in support**
- `app/api/static.py`: serves `frontend/dist` from the same port; unknown pages get `index.html`, the API and `/ws` are never answered with a page, files outside the folder are never served, a missing file is a 404 (7 tests).
- `scripts/demo_server.py` + `npm run demo`: the whole application on fakes with its own database; a test proves it imports no real adapter and never reads `.env` (decision D-46).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Component tests for the forms (multiplier-per-step validation) | ✅ | `GroupForm.test.tsx` (19 tests): one labelled input per step; steps up/down add/remove inputs and keep what was typed; `0`, `abc`, `-2`, `2,5`, empty are refused and the right step is marked; submit sends one value per step; "no martingale" has none; server complaints land on the right field. `groupSchema.test.ts` (46 tests) covers every rule |
| Component tests for the controls (confirmation flow) | ✅ | `KillSwitch.test.tsx` (11): nothing is sent before confirming; cancel / Escape send nothing; Cancel has the focus; the dialog names DEMO or REAL; "also end chains" is sent only when ticked; a failure keeps the dialog open with the reason; release asks too. `ChainsPanel.test.tsx` (9): "Skip to base" asks first and names group and account. `Modal.test.tsx`, `GroupsPage.test.tsx` (delete asks first) |
| Manual walkthrough script with the fake adapter in the report; screenshots if possible | ✅ | section 12; screenshots in `docs/reports/phase-7/` |
| `eslint`, `tsc`, `vitest` and a production `vite build` pass; the bundle is served by FastAPI | ✅ | section 4; `tests/integration/test_static_frontend.py`; I also fetched pages from a running `npm run demo` |
| Dashboard stays responsive with 500+ rows (virtualised or paginated) | ✅ | paginated (D-45). `HistoryPage.test.tsx`: with 600 trades only 50 rows are drawn; next/previous ask the server for exactly that page; 200 rows per page and the 200-row last page work; changing a filter returns to page 1 |
| Scope: app shell, routing, error boundaries, loading/empty/error states, accessible components | ✅ | `App.test.tsx` (navigation, current-page marking, 404 page, error boundary leaves the header and kill switch working), `DataState` states tested on every page; every table has a caption and column headers, every input a label, dialogs trap focus |
| Scope: DEMO/REAL indicator everywhere | ✅ | in the header of every page; real money adds a red banner (`App.test.tsx`); unknown shows "loading", never a guess |

## 4. Checks run
```
$ npm run check
api:check  up to date (docs/openapi.json, src/api/schema.d.ts)
ruff check: All checks passed!    ruff format: 166 files already formatted
eslint + prettier: clean          mypy (strict): no issues in 94 source files     tsc --noEmit: clean
pytest: 753 passed                vitest: 226 passed (17 files)                   vite build: built in 566 ms
```
Production bundle: main chunk 286 kB (92 kB gzipped); each page is its own chunk; the form libraries
(React Hook Form, Zod) are only downloaded with the group form (88 kB + 50 kB).

Mutation checks (broken on purpose, a test must fail): **25 dashboard breakages** — confirmation
bypassed or Enter-confirms, kill switch ignoring "end chains", cache not updated, dialog not closing,
account not named, progress off by one, finished chains staying live, other account's balance shown,
no batching, snapshot keeping stale events, lists not refreshed, unmounted provider still updating,
multipliers not shrinking, no-martingale keeping steps, zero multiplier allowed, one-per-step rule
off, next page past the end, filter keeping the page, no real-money banner, real looking like demo,
Escape ignored, countdown never settling, loss not coloured, toggle sending the old flag: **all 25
caught.** (The backend mutation results of Phase 6 stand; nothing in those files changed.)

## 5. Challenges and how they were resolved
1. **A test that depended on whether you had built the frontend.** Once `frontend/dist` existed the
   backend mounted the dashboard in every test too, and its catch-all route swallowed a route a test
   added afterwards. Tests now point at a folder that does not exist unless they ask otherwise.
2. **Accessible names for the row buttons.** Hidden helper text inside the buttons ("Edit" + hidden
   "Alpha signals") did not produce the name I expected; the buttons now carry an `aria-label` that
   starts with the visible word ("Edit Alpha signals"), which is also what voice control needs.
3. **Lint rules about fast refresh** (a file that exports components must export only components)
   made me split helpers out (`lib/errors.ts`, `live/liveStatus.ts`, `app/queryClient.ts`,
   `components/pageSizes.ts`). More files, but each does one thing.
4. **Lazy pages in tests.** Routes load their code on demand, so a test must wait for the shell before
   asserting; the shared `renderApp` helper does.
5. **The shell command line again**: a large here-document failed to parse; I used file writes.

## 6. Deviations from the plan
- **No risk-limits screen.** `PHASES.md` lists groups, controls, live, signals and history for Phase 7;
  limits and the risk-event list are in the API (and `/docs`) but have no screen. See section 10.
- **"Skip to base" is the API's "end chain"** (D-39): same effect, since the group starts again at base
  with the next signal.
- **Pagination instead of virtualisation** (one of the two options the plan allows): D-45.
- **A demo server** was added (D-46): the plan asks for a walkthrough "using the fake adapter" and
  there was no way to run the whole application on it.
- New decisions: **D-43, D-44, D-45, D-46.** New dependencies in section 9.

## 7. Could not be verified
- **A real browser session of yours.** I drove the dashboard with automated tests and looked at
  screenshots from a headless Edge against the demo, but I did not click through it in a window.
  *Manual check:* section 12.
- **Real Quotex / Telegram**, as in every earlier phase: the dashboard only shows what the engine
  reports, and the engine has only run on the fakes. The Phase 2–5 live checks still apply.
- **Screen readers and keyboard-only use** were checked by tests (labels, roles, focus trap, Escape,
  focus restore) and by reading the markup, not with an actual screen reader.
- **Very small phones**: the layout reflows (header wraps, tables scroll sideways) but I could only
  screenshot down to about 500 px wide with the headless browser.

## 8. Measurements
- Test run: 226 component/unit tests in about 15 s.
- With 600 trades the History page draws 50 rows (a test asserts it), and the live feed costs one
  render per animation frame however many events arrive (a test sends 10 events and counts one write).
- Bundle sizes in section 4. No browser timing numbers were taken.

## 9. New dependencies / files of note
Frontend runtime: `@tanstack/react-query` 5 (server state, as the conventions require), `react-router-dom` 7
(pages and lazy loading), `react-hook-form` 7 + `@hookform/resolvers` 7 + `zod` 4 (forms and validation, as
the conventions require). No new backend dependencies. `npm audit` still reports the moderate dev-tooling
advisories noted in Phase 6; none of it is in the bundle.
Notable files: `frontend/src/{app,live,features,components,lib,test}/`, `backend/app/api/static.py`,
`backend/scripts/demo_server.py`, `docs/reports/phase-7/*.png`.

## 10. Suggestions and open questions
- **A Risk page**: set and see the global and per-group limits, today's result against them, and the
  list of blocked orders (`/risk`, `/risk/limits`, `/risk/events` exist already). I would build it
  next, before real money: right now limits can only be set from `/docs` or `curl`.
- **A chat picker for the group form** (list your Telegram chats instead of typing the id).
- **Browser notifications / sound** when a chain ends or a risk limit trips (not built).
- The Telegram badge says "listening to 0 chat(s)" in the demo when the engine starts before any
  group exists; it corrects itself when the first group is added. Cosmetic.

## 11. Git state
Committed as `feat: dashboard v1 (Phase 7)` once the checks passed (see `git log`).

## 12. How to test it yourself
No accounts needed. I ran 1–3 myself first (screenshots below came from it).

**1. All automatic checks:** `npm run check`.

**2. Start the demo** (simulated Quotex and Telegram, its own database):
```
npm run build
npm run demo
```
Open <http://127.0.0.1:8000>. Expected: a **DEMO** badge, "Telegram: connected", "Quotex: connected",
"Feed: live". Every ~7 seconds a signal arrives; chains and trades appear on **Live** and finish
after about 15 seconds.

**3. Walk through it**
| Step | Expected |
|---|---|
| Live page, wait 30 s | Chains running and Trades open fill up; "Time left" counts down then says "settling…"; "Today" and the balance change as trades settle; "Signal to order" shows a fraction of a millisecond |
| Signals | Every message is listed; every fifth is plain chat and shows "Not parsed" with the reason; a flip-strategy group's signals during a running chain show "Ignored" |
| History | Trades with Won/Lost and signed profit; filter Result = Lost; "Rows per page" |
| Groups → Edit "Alpha signals" | The form shows 3 multiplier inputs. Set Steps to 5: two more appear. Type `0` in one and press Save: "Must be greater than 0" appears under that input and nothing is saved |
| Groups → Add a group | Leave it empty and press Create: each problem is named. Chat id `-1004`, a name, the rest as it is → Create: the new group appears and starts listening |
| Groups → Pause "Beta" | A "Paused" badge appears; its new signals show "Ignored: group is paused" in Signals |
| Live → "Skip to base…" on a chain | A window asks first and names the group and DEMO; Cancel changes nothing; "Skip to base" ends the chain |
| **Kill switch…** (top right) | A window explains the effect and names DEMO; Cancel does nothing; engage it → a red "KILL SWITCH ON" badge; new signals are "Ignored: kill switch engaged"; "Release…" asks again |
| Stop the demo (Ctrl+C) and reload | "Backend not reachable" in the header |

**4. The REAL-money look** can be seen without real money: in the tests
(`npm --prefix frontend test -- App.test`), or open the page, F12 → Network → find `status` and
compare with `"account_type": "demo"`. It turns the badge red and adds a banner when that value is
`"real"`.

**5. One-process mode:** stop the demo, run `npm run backend` (engine off, nothing contacted) and open
<http://127.0.0.1:8000>: the same dashboard, with "not running" on both connections and a notice on
the Live page explaining how to start the engine.

Screenshots (from the demo): [Live](phase-7/live.png), [Groups](phase-7/groups.png),
[Add a group](phase-7/new-group.png), [History](phase-7/history.png).
