# Decision Log

Decisions already made with the owner. Do **not** re-open them without a concrete reason; if you think
one is wrong, record the evidence in the phase report under "Suggestions" and ask.

Format: ID — decision — why — consequences.

---

**D-1. Web app, local-first.** It runs on the owner's Windows PC; moving to a VPS later must need no
code change (only configuration). Why: keeps credentials on the owner's machine and lets the owner
learn the system before hosting it. Consequence: paths, ports and bind address come from settings;
no Windows-only code outside optional scripts.

**D-2. FastAPI + React (Vite) + TypeScript, one Python process.** Why: the engine is async Python
(Telethon + pyquotex); running it in the same event loop as the web server avoids inter-process
messaging on the hot path. Django/Next.js were rejected: Django's strengths (admin, accounts, ORM)
are not needed and a long-lived async engine fits it awkwardly; Next.js would add a second server for
no benefit. Framework overhead is irrelevant next to Telegram/Quotex network latency.

**D-3. SQLite (WAL) first, PostgreSQL-ready.** SQLAlchemy 2.x async + Alembic. Why: zero setup, enough
for this load, portable schema. Consequence: no SQLite-specific SQL in app code.

**D-4. The database is never on the hot path.** State lives in memory; changes are published as events
and persisted by a background `DBWriter`. Why: persistence must not add latency to trade execution.
Consequence: crash recovery loads open state from the DB at startup.

**D-5. pyquotex is pinned as a git dependency, not vendored.** Upstream:
`https://github.com/cleitonleonel/pyquotex` (version 1.1.0 at time of writing; requires Python ≥ 3.12;
default host `quotex.com`, configurable `host`; uses `curl_cffi`). Pin to a specific commit hash in
`pyproject.toml`; record the hash and date in this file when chosen. Why: easy upstream updates, no
copy to maintain. If a patch is unavoidable, fork the repo and pin the fork. The old local checkout
(commit 8706f2c, 2025-07-16, hard-coded `qxbroker.com`) must **not** be used.
**Pinned (Phase 0):** commit `a50a030b425937fec4595b1ff1c226e160c52943`, committed upstream on
2026-10-13, `pyproject.toml` version 1.1.0, chosen 2026-11-01. Installed and imported on Python
3.12.15 (import only). Phase 2 may change the pin if reading the source shows a problem.

**D-6. All Quotex access sits behind `QuotexAdapter`.** Why: the library is **unofficial** (no public
developer API exists as far as we could find), it breaks when Quotex changes, and automation may breach
Quotex's rules (accounts can be restricted). One adapter file means one place to fix, and a
`FakeQuotexAdapter` for tests. Consequence: no other module imports `pyquotex`.

**D-7. Reuse the existing signal parser first.** Phase 3 ports `parse_signal` from the old
`trading_bot_V2.py` (patterns: "ENTRY CONFIRMED", "MINUTES EXPIRY WITH TIME", "ASSET;TIME;DIRECTION",
"PAIR; TIME; DIRECTION", "PAIR CALL/PUT DURATION") behind a `SignalParser` interface so more parsers
can be added per group later. Fix known weaknesses while porting (see DOMAIN.md §4), add tests from
real example messages.

**D-8. Strategies (per group).** `no_martingale`, `martingale`, `flip_every_loss`, `two_step_flip`
(compounding is out of scope). Each group sets: base stake, **max steps**, and **one multiplier per
step**. "Max steps" = the original signal trade **plus that many follow-ups** (3 → up to 4 trades).
Exact rules in `docs/DOMAIN.md`.

**D-9. New signals are ignored while a flip-strategy chain is running for that group.** Why: stakes
must not stack. Other strategies open independent chains. The signal inbox still records the ignored
signal with the reason. (Amended by D-70: a group may now allow one opposite pair.)

**D-10. Concurrent chains.** State is per chain (`group_id`, `asset`), never global. Why: the old bot's
single global loss counter made parallel trades impossible.

**D-11. "Close early" means controlling the chain, not selling a trade.** Dashboard actions:
*stop after the current trade*, *skip to base stake / end chain*, *pause group*, *kill switch*.
Selling an individual open trade before expiry (`sell_option`) depends on Quotex allowing it; it is a
**later, separately tested** item.

**D-12. Payout filter.** Read the pair's payout (`get_payout_by_asset` / `get_payment`) from the
instrument data Quotex pushes (in memory, no extra request). Skip a signal when payout < the group's
minimum. The library reads fixed list positions (`i[-9]`, `i[-8]`); the adapter must sanity-check the
values (0–100) and fail loudly if they look wrong.

**D-13. Wait for results by event, never by fixed sleep.** The old bot slept `duration + 5` before
checking the result, delaying every follow-up. The adapter exposes an awaitable result with a timeout.

**D-14. No blocking calls in the event loop.** Lesson from the old bot: pyquotex's `buy()` triggered a
blocking HTTP profile request each time. Cache the server-time offset, warm up at startup, wrap any
remaining sync I/O in `asyncio.to_thread`. Re-measure on pyquotex 1.1.0 (its internals differ).

**D-15. Demo by default; demo and real are separated in all data.** `account_type` on trades/chains;
all reports filter by it. Real trading requires an explicit setting.

**D-16. No user accounts in v1, but the server binds to `127.0.0.1` by default** and refuses a public
bind without an explicit flag, because the API can place trades. Auth is a later item.

**D-17. Secrets never in git.** `.env` and `data/` are git-ignored; `.env.example` documents keys.
Encrypted credential storage is a later item.

**D-18. No commits by the agent** until the owner says so. Work stays in the working tree.

**D-19. Python 3.12, `uv` or `pip` + venv (decide in Phase 0 and record).** Backend tooling: ruff
(lint + format), mypy (strict on `app/`), pytest + pytest-asyncio. Frontend: ESLint, Prettier,
TypeScript strict, Vitest + React Testing Library.
**Decided (Phase 0, 2026-11-01): `uv`.** The backend lives in `backend/` with `pyproject.toml` and a
committed-later `uv.lock`; `uv` also provides Python 3.12 (the machine's system Python is 3.9 and its
registered 3.12 install is broken). Root `package.json` holds only convenience scripts.

**D-20. In production FastAPI serves the built frontend** (single process, single port); in
development Vite's dev server proxies `/api` and `/ws` to FastAPI.

**D-21. Frontend toolchain pinned to what runs on Node 20.15.** The newest releases (Vite 8,
`@vitejs/plugin-react` 6, Vitest 5, jest-dom 7) need Node ≥ 20.19/22 and failed on the owner's Node
20.15.1 (Vite 8's bundler could not load its native binding). Chosen instead: React 18.3, Vite 6,
plugin-react 4, Vitest 3, jest-dom 6.6, TypeScript 5.9, ESLint 9. Why: works on the machine as it is,
no system change needed. Consequence: when the owner upgrades Node to 22 LTS, these can be raised.
*Update 2026-11-02: the owner upgraded to Node 26.13 and approved the toolchain upgrade. Now:
Vite 8.3, @vitejs/plugin-react 6, Vitest 5, jest-dom 7, jsdom 30, eslint-plugin-react-hooks 7,
eslint-plugin-react-refresh 0.5, globals 17. Deliberately kept: React 18 (as in ARCHITECTURE.md),
TypeScript 5.9 and ESLint 9 (their newest majors are not yet safe with the lint plugins). The
dev server, proxy, tests and build were re-verified against the live backend.*

**D-22. Money is stored as integer cents and handled as `Decimal`.** Why: SQLite has no decimal
type, so `Numeric` would silently become a float there; integers are exact on every database.
Python code never sees the cents: the `Money` column type converts to and from `Decimal`.
Consequences: two decimal places only (Quotex stakes and balances are in cents); floats are refused
and so is a value with more than two decimals, so the strategy must round stakes explicitly
(Phase 4) instead of the storage layer rounding silently. Payout is a whole-number percentage.

**D-23. Chains, trades, signals and other event-created rows use UUIDs generated in memory;
only `groups` uses an auto-increment integer.** Why: an auto-increment id needs a round-trip to
the database, which D-4 forbids on the hot path. Groups are created from the dashboard, where that
round-trip is fine, and a short integer is friendlier there. Consequence: ids are unordered, so
lists sort by timestamp, never by id.

**D-24. Event bus and DBWriter overflow policy.** `publish` never waits. Each subscriber has a
bounded queue and chooses what to drop when it is full: the DBWriter drops the *newest* events
(keeps the stored history in order, counts every drop, logs an error, and shows it in `/health`);
live views may drop the oldest and re-sync. DBWriter queue: 100,000 events. A failed batch is
rolled back and retried event by event, so one bad record cannot lose its neighbours.

**D-25. Log exceptions as plain text, never with locals.** structlog's default "rich" traceback
took about 10 seconds to format one database error, which would freeze the event loop (and
trading) while logging, and it cannot be printed on Windows consoles using cp1252. `core/logging.py`
uses plain tracebacks (text) in development and `format_exc_info` in production.

**D-26. Adapter structure: protocol, thin library seam, fake, contract tests.** `QuotexAdapter`
(base.py) is the interface; `PyQuotexAdapter` holds all decisions (state, reconnect, safety checks)
and talks to the library only through the small `QuotexClient` interface, whose single real
implementation `PyQuotexClient` is the only module importing pyquotex (checked by a test).
`FakeQuotexAdapter` follows the same rules. One contract test-suite runs against the fake and the
real adapter. Why: the logic can be tested without the unofficial library, and the part that cannot
be tested without the live service is as small as possible.

**D-27. Orders bypass `Quotex.buy()` and are sent one at a time.** Reading pyquotex 1.1.0: `buy()`
downloads the profile over HTTP and polls for a price tick (0.2 s steps) on every order, and
waits `duration + 5` s for the confirmation; the server-time offset it fetches is not used by the
order message. The adapter subscribes to an asset's prices once (`prepare_asset`, on the first
order or ahead of time), sends via `api.buy`, and waits `ack_timeout` (10 s). pyquotex keeps ONE
shared "order confirmed" slot, so an `asyncio.Lock` covers send-to-confirmation (normally
milliseconds); results are awaited outside the lock. An order sent without a confirmation is
reported as `OrderAckTimeoutError` ("may have been placed"): the chain must become `unknown`, never
be retried blindly. Consequence: simultaneous signals queue for the confirmation round trip of the
orders ahead of them.

**D-28. The adapter owns reconnecting; session file stays in `data/`.** pyquotex's own websocket
auto-reconnect is turned off so there is one owner with backoff (1 s doubling to 30 s, +-10 %
jitter), events and a fresh client per attempt. The library writes `session.json` (cookies and
token) into the current directory; the wrapper redirects it to `data/` (git-ignored). A rejected
token is cleared from the file, because the library only forgets it in memory and would otherwise
load the same dead token on every retry. Login PIN prompts never use `input()` inside the app
(it would freeze the loop): unattended runs fail with an explanation, the diagnostic script asks
in the terminal.

**D-29. Result semantics.** pyquotex labels every profit <= 0 as "loss" and cannot report a draw.
The adapter follows it: profit > 0 is WON, otherwise LOST (`classify_profit`). The fake can script
a DRAW so the engine can handle one. `check_win()` is not used (it answers "loss" after a fixed 300 s,
wrong for long expiries); the adapter waits on the library's per-order result slot and raises
`ResultTimeoutError` instead. Default expiry mode is `TIME` (library default; clock-aligned expiry);
`TIMER` (countdown) is a setting. Both are to be confirmed with the live diagnostic.

**D-30. The parser never guesses, and the OTC suffix is the group's choice.** `legacy_v1` is the old
parser's formats, tightened: no direction means "not a signal" (the old code defaulted to CALL),
words match whole (`PUT` inside `INPUT` no longer counts), a pair without a slash must be two known
currency codes (so `SIGNAL` after "expiry" is not an asset), and channel "gale" lines are dropped.
The parser only reports that the message said OTC; `asset_suffix_mode` (otc / none / auto) decides
the Quotex name (`EURUSD` vs `EURUSD_otc`). A message listing several signals uses the first and the
inbox row says how many were left out. A missing expiry is assumed to be 60 s (the old default) and
the inbox row says so. Why: a wrong guess is a wrong trade with money behind it. Consequence: some
messages the old bot half-understood are now `not_parsed`; each has a reason in the inbox, and new
formats are added as new parsers or patterns with tests from real messages.

**D-31. Entry times are wall-clock times in a known zone, resolved to the nearest occurrence.** The
zone is the one the message states ("Time Zone: UTC -3"), otherwise the group's. The pipeline picks
the occurrence of that time closest to now among yesterday, today and tomorrow, so midnight, month
ends and daylight-saving changes need no special cases. Up to 30 s late: trade at once; later:
ignored as "already passed", never moved to tomorrow. Up to 1 h ahead: scheduled for that exact
moment on a supervised timer; further: ignored as "too far". A time that does not exist (the hour
skipped by a clock change) is ignored. The limits are `PipelineConfig` values, not group settings.
Why: a stale signal must not trade 23 hours later, and a list of the whole day's signals must not
be mistaken for one instruction. Consequence: scheduled signals live only in memory; a restart
before their entry time loses them (Phase 5 may want to recover them).

**D-32. The pipeline's guards and the hand-over order.** Before parsing, a message that reached us
more than 120 s after Telegram stamped it is ignored as stale (after a reconnect Telegram may
replay old messages, and a signal without an entry time would otherwise trade late). The same
Telegram message seen again (an edit, a replay) is processed at most once: an edit can turn a
non-signal into a signal, but once a message was a signal no edit trades again. The same signal
(group, asset, direction, expiry, entry) within 5 minutes is a duplicate. The engine gets the
signal first (`on_signal`), then the inbox event is published, so the order never waits for
bookkeeping. `Signal.id` equals the inbox row's id, so a later stage can re-publish that id with a
new status ("ignored: chain active", D-9). Every message of a routed group is recorded exactly once
as `SignalReceived`; messages from chats without a route are dropped and counted. A clock that runs
more than 2 minutes ahead of Telegram's would make every message look stale: that is visible in the
inbox, and the fix is the PC's clock.

**D-33. Telegram: one thin seam, our own chat filter, and a login that never blocks.** `TelegramSource`
is the interface; `TelethonSource` is the only Telethon importer (checked by a test); `FakeTelegramSource`
drives the tests. Messages are filtered by chat id in our code, so chats are added and removed while
running without touching Telethon's handlers. Chat ids are Telethon's "marked" ids (`-100…` for
channels and supergroups), the same value `get_dialogs` shows and `GroupRecord.telegram_chat_id`
stores. Telethon reconnects by itself after a drop; if it gives up, the listener reconnects with the
same backoff as Quotex (1 s doubling to 30 s) and publishes `connection.changed`. A saved session
that is not logged in stops the listener with the instruction to run `npm run telegram:login`:
retrying cannot fix it. The login runs from a terminal script and never uses `input()` inside the
app. `catch_up` (replaying messages missed while offline) is left off until it can be checked
against the live service. The session file lives in `data/` (git-ignored). The backoff helper moved
from `app/quotex/` to `app/core/backoff.py` because both integrations use it.

**D-34. How the engine runs a chain.** Each chain is its own supervised task holding its own state
(step, loss counter, direction), so chains never share anything (D-10). Independence is by chain id;
the `(group, asset)` pair identifies what a chain trades, and non-flip groups may have several chains
on the same pair at once. A follow-up is placed the moment the loss is known: the only work between
is in-memory bookkeeping. A trade is published as `pending` just *before* its order is sent and as
`open` once confirmed, so a crash between the two leaves a trace for recovery. A **draw** ends the
chain as `completed` (Quotex refunds it, so nothing needs recovering; pyquotex cannot report draws
anyway, D-29). A refused order ends the chain `failed`; an order sent without confirmation, a missing
result, an unexpected error, or a changed account ends it `unknown` / `failed` and is **never
retried**. Waiting for a result is by the adapter's event with a timeout of expiry + 60 s. Because
the pipeline hands a signal over *before* it publishes the signal's inbox row (so orders never wait
for bookkeeping), anything that points at or replaces that row (`chain.started`, an "ignored: chain
active" update) is published one event-loop turn later; otherwise the chain insert would break its
foreign key and the "ignored" status would be overwritten by "parsed".

**D-35. Restart recovery marks everything in flight `unknown`; it never continues.** We cannot see
Quotex's history, and a follow-up placed minutes late is not the trade the strategy asked for. At
start-up every unsettled trade and every active chain is marked `unknown` (reason stored on the row),
a `risk.tripped` event of kind `restart_unknown` is published per affected group, and the groups are
free for new signals at once. Known results (a trade already `lost`) are left as they are. Consequence:
the owner must look at those trades on Quotex; the dashboard (Phase 7) will list them.

**D-36. The engine starts with the application only if `ENGINE_ENABLED=true`.** Default off, so
`npm run backend` never logs in to Quotex or Telegram by surprise (a login can trigger an e-mail PIN).
Start-up order: load groups and recover, start the Quotex connection (in the background, with
backoff), start the Telegram listener. Shutdown order: listener, chains, Quotex, then the DB writer
drains what they published. A missing login with the flag on stops start-up with a clear message.

**D-37. RiskGuard: what each limit means.** The guard is consulted synchronously, from memory, just
before every order (`admit`); an allowed order is reserved at once so two chains cannot both take the
last free slot. **Reaching** max stake, max exposure, max concurrent trades, max chain length or the
minimum payout is allowed; **exceeding** it is blocked. **Reaching** the daily stop-loss or the daily
profit target blocks (a day that has lost exactly the stop-loss, or won exactly the target, is over).
The daily limits exist globally and per group; the max stake also per group. Everything except the
minimum payout applies to follow-ups too (a stop-loss that let a chain keep doubling would be no
stop-loss); the minimum payout filters only the signal's own first trade (D-12). The "day" starts at
`reset_time` in `reset_timezone` (default 00:00 UTC) and totals are kept per account type, so demo
results never count against real limits (D-15). Only trades with a known result count: `unknown`
trades do not move the total. An unknown payout figure never blocks (the adapter refuses an unknown
asset itself). A trade whose result will never be known is released from the open count, since it
cannot be tracked forever. Limits, per-group limits, the kill switch and paused groups are stored as
app settings through the event bus and restored at start-up; today's totals are rebuilt from the
last 48 hours of settled trades. **A stored setting that cannot be read engages the kill switch**
instead of silently becoming "no limit". A blocked order ends its chain (`failed`, or `stopped` for
the kill switch), is recorded as a `failed` trade whose error says why, and publishes a `risk.tripped`
event naming the group, asset, step and stake.

**D-38. The owner's controls.** *Kill switch*: no order leaves, follow-ups included; running chains
end as `stopped` when their next order is refused, or immediately with `stop_chains`; new signals are
ignored with a reason. *Pause group*: new signals of that group are ignored; its running chains
finish. *Stop after current trade*: the chain ends when the open trade settles, without a further step
(a win ends it anyway). *End chain*: the chain ends at once and the group is free for new signals; an
open trade still settles and is recorded. Switching between demo and real is refused while any chain
or trade is running; real also needs `QUOTEX_ALLOW_REAL`. Known limit: an order already being sent
(a few milliseconds between the guard's check and the adapter's send) cannot be recalled by a kill
switch engaged in that instant.

**D-39. The shape of the API.** REST under `/api/v1` plus one WebSocket at `/ws`. Every error has the
body `{"error": {"code", "message", "details"}}` (stable code, readable message, field problems for
validation errors, never the rejected values, never a trace). Lists are always paged with a total.
Money is a string in every response, never a float. Reads come from the database (a moment behind the
engine); `/status` and the WebSocket snapshot are the live picture, rebuilt from events by `LiveState`.
Commands that need the running engine (pause, kill switch, chain commands, account switch) answer 503
`engine_not_running` without it; **creating groups and setting risk limits work without it**, because
limits must be settable *before* the engine is first enabled. The description of the API
(`docs/openapi.json`, including the WebSocket messages) is generated from the code and committed; the
frontend's types are generated from it, and `npm run check` fails if either is stale. "Skip to base"
is `POST /chains/{id}/end`: ending the chain frees the group, so the next signal starts at base stake.

**D-40. The WebSocket protocol.** First a `snapshot` (the whole picture), then events numbered 1 apart,
plus heartbeats that carry the latest number. Only events that produce a message use up a number, so
the numbers a client sees are consecutive and any jump is a real gap. A client that sees a gap sends
`resync` and gets a new snapshot. Each connection has its own bounded queue; when it overflows, that
client's queue is dropped and it is sent a fresh snapshot (`slow_consumer`): a slow dashboard loses
its own events and never delays the engine (which only ever calls the non-blocking `bus.publish`) or
other dashboards. One hub task turns bus events into messages and updates `LiveState` in the same
synchronous step, which is what makes "snapshot at N, then N+1, N+2..." exact. The day's profit and loss
is not pushed event by event: it is in every snapshot and in `GET /risk`, and a dashboard refetches it
when a trade settles.

**D-41. The API protects itself from the owner's own browser.** Binding to loopback keeps other
computers out, but any web page the owner opens can make their browser send requests to `127.0.0.1`.
So: only loopback host names are served (against DNS rebinding; off only with `ALLOW_PUBLIC_BIND`);
any request that changes something, and every WebSocket, is refused if its `Origin` is another site
(allowed: the same host, and the dev server's origin in development); bodies over 64 KiB are refused;
commands are rate limited (burst 40, 10/s). Programs without an `Origin` header (curl, scripts) are
unaffected, since a web page cannot make them send one.

**D-42. Today's result survives editing the limits (a correction to D-37).** `RiskGuard.set_limits`
used to start the day's totals from zero, so saving the limits again after a stop-loss had been
reached would have lifted it. The guard now keeps a 48-hour in-memory ledger of settled results and
rebuilds the day's totals from it, so editing limits, or even moving the reset time or zone, never
loses results that belong to the day. Found while building the API that exposes this.

**D-43. How the dashboard keeps its data (Phase 7).** TanStack Query holds everything from the server.
The `status` query (the same shape as the WebSocket snapshot) is special: it never refetches by itself;
the live feed replaces it with each snapshot and patches it with events through one pure, tested
function (`applyEvent`). Events are collected and applied once per animation frame, so a burst costs
one render. Lists (signals, trades, groups, risk) are ordinary queries that the relevant events and
every new snapshot mark stale, so they refetch only what is on screen. No separate client store
(Zustand) was needed. Pages are separate chunks (React Router lazy routes); the form libraries
(React Hook Form, Zod) load only with the group form. Styling is plain CSS with design tokens and
automatic dark mode; no UI framework.

**D-44. Safety in the interface.** The account in use is in the header of every page and is never
guessed: DEMO is a blue outlined badge, REAL is a solid red badge **and** a red banner across every page;
until the status is known the header says "loading", not "DEMO". The kill switch is always in the
header. Engaging it, releasing it, and "skip to base" (ending a chain) each open a confirmation that
says what will happen and on which account; **Cancel has the focus**, so Enter alone never confirms; a
failed request keeps the dialog open and shows the server's reason. A state is always written in words
as well as colour ("Quotex: disconnected"). Telegram message text is shown as plain text only.

**D-45. Long lists are paginated by the server, not virtualised.** History and the signal inbox ask
for one page at a time (25/50/100/200 rows) with the total, so what is drawn is bounded however much
history exists (tested with 600 trades). The live panels (running chains, open trades) are not paged:
they are bounded by the concurrency limits and by the number of groups.

**D-46. A demo mode that cannot touch anything real.** `npm run demo` runs the whole application
(API, WebSocket, engine, database) on the fake Quotex and fake Telegram, with its own database in
`backend/data/demo/`, and posts made-up signals. It never reads `.env`, and a test checks that the
script imports nothing from the real adapters. It exists so the dashboard can be shown and walked
through without any account.

**D-47. What the reports measure (Phase 8).** Demo and real are never mixed: every report is for one
account (default demo). Only **resolved** trades (won, lost, draw) count in any profit or rate;
failed, unknown and open trades are listed separately as "not counted", so a missing result is
visible instead of silently lowering or raising the figures. **Profit** is the figure stored on the
trade; **win rate** = wins / resolved trades; **ROI** = profit / money staked. Trades are placed in a
date range by the time they **settled**; chains (depth report) by the time they started; the CSV of
all trades by the time each was **created** (a trade that never settled has no settle time). Hour of
day, weekday and daily results use the owner's clock as a fixed offset from UTC (`utc_offset_minutes`;
daylight saving is not followed, and the dashboard says so by sending the browser's current offset).
The money is summed by the database as integer cents and converted once at the edge: no report ever
adds floats. A figure always travels with its **sample size** and a plain label: fewer than 10
trades is "too few", fewer than 30 "small sample". **Expected against actual**: a trade at payout *p*
breaks even at a win rate of 1/(1+*p*), and no staking scheme changes that, so the report compares the
actual win rate with break-even and says how many standard errors apart they are (beyond 2 is unlikely
to be luck); below 30 trades the verdict is always "not enough data". That is the honest answer to
"is this really working?". Draws are rare (the library cannot report them, D-29) and count as a
result of zero. Streaks, the largest drawdown and the daily series come from one streamed pass in
settle order.

**D-48. Charts: no chart library, small SVG components.** The dashboard needs two shapes: bars
(profit by group, asset, strategy, hour, weekday; share of chains by step) and one line (the running
total). A library (Recharts, Chart.js, visx) would add 60-100 kB and, for the SVG ones, a size
measurement that does not exist in the test environment, for something about 150 lines draw. The
components (`BarChart`, `LineChart`) are tested for geometry, carry a one-sentence description for
screen readers, and are always accompanied by a table of the same numbers, which is the accessible
version. If charts later need zoom, brushing or many series, adopt a library then; the pages only
pass plain `{label, value}` lists, so swapping is local.

**D-49. CSV that opens correctly in Excel.** UTF-8 **with a byte-order mark** (without it Excel
guesses a legacy code page and garbles accents), comma by default and **semicolon on request** (Excel
in many locales shows a comma file as one column), CRLF line endings, a dot as the decimal
separator, times as `YYYY-MM-DD HH:MM:SS` in UTC. Text cells starting with `=`, `+`, `-`, `@`, tab or
carriage return get a leading apostrophe so a spreadsheet cannot run them as formulas; numbers are
never touched. The trades file is streamed in batches from its own database session so a long
history does not sit in memory.

**D-50. The database writer waits out an outage; it does not give up at the first error.** A locked
or unreachable database (`OperationalError`, `InterfaceError`: another program holding the file, a
full disk, a dropped connection) is retried with backoff (0.2 s growing to 5 s) for up to ten minutes
while the queue keeps filling, so a short outage loses nothing. After ten minutes that batch is
dropped, counted and reported. Any other error (a record the database refuses) is not waited out: the
batch is retried record by record so one bad record cannot take the rest with it. At shutdown the
writer gives up after three attempts so a dead database cannot hold the process. Why: the execution
path must never wait for the database (D-4), so the writer is the only place to absorb outages.

**D-51. Logs: a rotating JSON file, secrets masked.** Besides the console, logs go to
`DATA_DIR/logs/engine.log` as JSON lines, rotated at 10 MB with 5 files kept (`LOG_TO_FILE`,
`LOG_MAX_MB`, `LOG_BACKUPS`). A processor replaces the Quotex password and the Telegram API hash with
`***` anywhere they occur in a log line, including inside tracebacks (values shorter than 4 characters
are not masked: they would mangle ordinary words). Why: the owner needs history when something went
wrong overnight, and a log that is pasted into a chat for help must be safe.

**D-52. `/health` says `degraded`, in sentences.** `status` is `ok` or `degraded`, with a `problems`
list the owner can act on: database unreachable, writer retrying, events dropped, records that could
not be stored, and (when the engine runs) Quotex or Telegram disconnected. The dashboard polls it
every 15 s and shows the sentences in a banner. A disconnected service while the engine is off is not a
problem (it is not supposed to be connected). Why: every failure in `docs/FAILURE_MODES.md` must be
visible without reading a log.

**D-53. VPS deployment: systemd and an SSH tunnel; no Docker, no login.** The application keeps its
loopback bind and the owner reaches the dashboard through an SSH tunnel, so nothing but SSH is exposed.
A systemd unit runs it with an orderly stop (the "no Docker" part is superseded by D-69). Docker is not provided: the application needs interactive
logins and a persistent data folder, and on a single-user setup a container adds volumes and terminal
handling for nothing. A reverse proxy is documented only with authentication in front of every path.
Adding a dashboard login stayed in the "Later" backlog then; D-58 and D-59 brought it forward and replace the "no login" part of this decision (the loopback bind and the tunnel stay). Not verified on a real server.

**D-54. Chain events reach the bus in order.** The chain manager used to be able to publish `chain.ended`
before `chain.started` when a chain was stopped in the very moment it was created (kill switch or "skip
to base" while its first step was being set up). Found by the chaos test. The start event is now held
until the chain is driven, and whoever ends a chain first publishes any start that is still waiting.
Why: the database stores events in the order they arrive, and an end without a start is a wrong
history.

**D-55. A signal posted while Telegram was down is not fetched afterwards.** On reconnect the listener
only hears what is posted from then on. Acting minutes late on a time-critical signal would enter at a
worse price than the group intended, and fetching history would add a second path into the engine. The
gap is visible (banner, connection events) and the owner can trade it by hand. Revisit if the owner
wants late signals handled.

**D-56. Backups use SQLite's online-backup call and never overwrite.** `npm run backup` copies the
database with `Connection.backup`, which is consistent while the application writes (copying the file
is not, in WAL mode), checks the copy's integrity and refuses to back up a damaged database. A restore
keeps the replaced database as `quotex.db.before-restore-<time>`. Session files are included unless
`--no-secrets`, and the command says so. Only folders it made (with a manifest) are ever pruned.
`npm start` and `npm run latency` follow the same rule: they only read or create, never delete the
owner's data.

**D-57. The Telegram chat picker goes through the running engine.** `GET /telegram/chats` asks the
engine's existing Telegram connection for the account's chats (groups and channels, not private
chats) and marks the ones that already have a group. It does not open a second Telegram connection:
two programs sharing one `.session` file can lock each other out or log the account out. The cost is
that the picker needs `ENGINE_ENABLED=true` and a connected Telegram; otherwise it says why and the
owner types the id as before. The list is fetched only when the owner presses the button (never when
the form opens), with a 30 s limit, and nothing it returns is stored.

**D-58. What the owner types moves from `.env` into the dashboard (Phases 10-15).** Telegram and Quotex
logins are entered on the dashboard and stored encrypted in the database; settings such as "engine on"
live in the database. `.env` keeps only the bootstrap values (bind address, data folder, environment,
log files) and the master key that encrypts the logins. The key stays in `.env` (owner's choice): that
protects database copies and backups, not a machine that is itself compromised. The command-line logins
stay as a fallback. Why: the owner is not meant to edit files or run commands to change a setting.
This supersedes D-53's "no login" and the "Later" item "encrypted credential storage and dashboard login".

**D-59. Login before secrets; one owner now, room for more later.** The dashboard can place trades and,
from Phase 11, will hold the logins, so Phase 10 puts a login in front of everything first. There is one
account, the admin. `users` has a role and every session belongs to a user, so invitations can be added
later without redoing the login. An owner column on groups, chains, trades and the stored logins is
**not** added now: it would touch every table and query for a feature that does not exist yet; adding it
when invitations are built is a known, bounded job. The first account is created with a one-time setup
code printed in the log (a stranger who finds the page first cannot claim it), and a command on the
machine resets the password (there is no email to send a reset link).

**D-60. Passwords: scrypt from the standard library; sessions: random tokens, stored hashed.** Parameters
N=2^14, r=8, p=1 (RFC 7914's interactive-login setting, 16 MB), run in a worker thread so a login
never stalls the event loop. OWASP's table lists costlier settings; they measured 2 s and more on the
owner's PC and would hold a one-core server for seconds on every login, which the execution path
must not feel. The cost is stored in each hash, so it can be raised later without locking anyone out;
the password minimum (10 characters), the throttle and the command rate limit make up for the rest. No new dependency: the
standard library's scrypt is memory-hard and already installed on Windows and Linux. A session is 32
random bytes in an HttpOnly, SameSite=Strict cookie; the database holds only its SHA-256, so a copied
database cannot be turned into logged-in sessions. Failed logins are throttled in memory (per username
and overall), and an unknown user costs the same time as a wrong password.

**D-61. Stored secrets: AES-256-GCM, the key in `.env`, the name bound to the value.** Secrets typed into
the dashboard are encrypted with AES-256-GCM (the `cryptography` package, a new dependency) and stored
in the `secrets` table as `v1.<nonce + ciphertext + tag>`. The key is `SECRET_KEY` in `backend/.env`
(the owner's choice, D-58): 32 random bytes as text, created by `npm start` or `npm run key:create`,
and never replaced if one exists. Each value has its own random nonce and its **name is bound to it**
(authenticated data), so a value copied into another row does not decrypt, and a wrong key or damaged
value is always an error, never a wrong answer. The API can set, remove and list (set / readable) but
has no way to return a value; only code inside the process can read one. What this protects: a copied
database or backup. What it does not: someone who can read both the database and `.env` on the
machine. `backup --no-secrets` empties the `secrets` and `auth_sessions` tables in the copy and
VACUUMs it. A missing or malformed key is reported when a secret is stored or read, not at start-up,
so the dashboard can open and explain it.

**D-62. Dashboard settings are read once, at start.** `log_level`, `quotex_host` and `quotex_time_mode`
can be saved in the database (`app_settings`, keys `config.*`) and win over `.env`, which wins over the
default. They are read when the application starts; saving takes effect at the next start (the page
says so). Why: the engine is built once from its settings; applying a change to a running engine is
Phase 12's job (restart the engine without restarting the application). A stored value that no longer
passes its check is ignored with a log line, never a reason to refuse to start. `engine_enabled`,
`quotex_allow_real`, the logins and the other settings are deliberately not editable yet.

**D-63. The owner starts and stops the engine from the dashboard; the application remembers.** One class,
`EngineController`, builds, starts, stops and restarts the engine while the application runs. One request
at a time (a second is refused with 409, never queued), always the same order, always ending in a state the
dashboard can describe (`stopped`, `starting`, `running`, `stopping`, `failed` with the reason). Every
start builds a **new** engine, so nothing of the old one (guard, chains, connections) is reused, and it is
rebuilt from the database like after a restart (D-35) once the writer has stored everything the old one
said. Stopping marks what was in flight `unknown` at once, which is what the next start would have done.
A failed start never stops the application (before, a missing login did): the reason is shown. What the
owner left (running or not) is stored in the database and decides at the next start of the application;
`ENGINE_ENABLED` in `.env` is only the starting value for an installation that never decided, and
`QUOTEX_ALLOW_REAL` likewise (both are removed in Phase 15). The engine is built with the stored logins
first, `.env` second; a stored login that cannot be read stops the start instead of being replaced by an
older `.env` one. The path from a signal to an order is unchanged: this is all about the engine's life
cycle, not what it does.

**D-64. Real money: permission and the switch each need the password; both are on the record.** Switching
to the REAL account needs (1) the owner's permission, given on the dashboard with the password and stored
(`PUT /account/real-trading`), and (2) the password again with the switch itself. Both write a risk event
(`real_trading_allowed`, `switched_to_real`, and `real_trading_disallowed` when taken back). Guessing the
password here shares the lock with the login's other password attempts. The permission cannot be taken
away while REAL is in use. The engine always starts on DEMO (D-15), also after a restart. Why: a stolen
session cookie alone must not be enough to make trades use real money.

**D-65. The Telegram login is made on the dashboard and kept as an encrypted string session.** The login
(phone, code, two-step password) is a state machine in memory, `TelegramLoginService`: one at a time, only
while the engine is stopped (the engine and a login would both be connections of one account), forgotten
after ten minutes or at a restart, and not saved anywhere until it succeeds. The page can be reloaded or
opened elsewhere and shows the step it is at. A successful login stores a Telethon *string session*
(encrypted, D-61) instead of a `.session` file, together with the phone number (also encrypted); both are
the application's own entries, which the secrets API can neither set nor list. The API id and hash are
stored the same way (the id must be a number). The engine is built with the stored login, falling back to
`TELEGRAM_SESSION` in `.env`, then to the old `.session` file; with none of them it does not start and says
so. Logging out ends the session on Telegram's side if it can be reached, and removes the local copy
(and the old file) either way. Telegram's refusals are told apart (wrong code, expired code, wrong password,
flood wait with its seconds, bad phone, bad API id) so the page can say what to do. Not done: re-saving the
session if Telegram moves the account to another data centre (rare; the owner would log in again).

**D-66. The Quotex login is made on the dashboard, with the PIN, and never touches the disk.** The library
only understands a session *file*, so the application gives it one in a private temporary folder: for a
dashboard login the folder is made, the library logs in (asking for the e-mailed PIN through a callback the
dashboard answers), the saved session is read back as text and stored encrypted (D-61), and the folder is
removed whatever the outcome. For the engine, a stored session is written into a fresh private folder, the
file is deleted the moment the connection is made, and the folder is removed on close. The login is one long
call into the library that *waits* for the PIN, so it runs as a background task and the PIN is handed to it
through a future (a page reload shows the step; five minutes without a PIN end it). The service never needs
the engine running (it must be stopped, as for Telegram) and always logs in on the demo account. A refused
login (wrong password, wrong PIN, Quotex unavailable) is a normal answer with the reason in `message`. The
library's crash on a refused sign-in page (`'Response' object has no attribute 'reason_phrase'`, a non-2xx
answer such as Cloudflare's 403) is translated into a sentence saying exactly that and that it is not a wrong
password; the application does not try to get around the check. The Quotex session is optional for the engine
(without it the email and password are used, which only fails if Quotex asks for a PIN). Known limit: a token
the library refreshes while the engine runs is not saved back; the next start uses the stored one and the
library logs in again if it was refused.

**D-67. The old `.env` switches are gone, and the old logins can be moved; the tools share the store.**
`ENGINE_ENABLED` and `QUOTEX_ALLOW_REAL` no longer exist (D-63 said they would go): the engine's "left
running" and the real-money permission live in the database and change only on the dashboard (the latter
with the password). `QUOTEX_ALLOW_REAL` is still a field of the settings object because the adapter
factories read it, but it has an environment name nobody would write, so an old line cannot allow real
money (tested). A new installation never starts the engine by itself. The logins that `.env` used to hold
(`QUOTEX_EMAIL`, `QUOTEX_PASSWORD`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`) still work until moved, and a
stored one always wins; they are moved by `POST /settings/env-logins/import` (a button on the Settings
page; it never overwrites a stored login, never shows a value, never edits the file) or by `npm run
env:import`, which also replaces each moved line by a comment, retires the two switches, leaves the engine
running if `ENGINE_ENABLED=true` was set and the dashboard never decided, and never carries real money
over. The command-line tools (`telegram_cli`, `quotex_diagnose`) open the same store: `telegram_cli login`
stores its session there, both use the stored API id/hash/login, and both fall back to `.env` and the old
session file when there is no usable store (a new installation, no `SECRET_KEY`). Kept deliberately: the
old `.env` logins keep working (removing them would break installations that have not moved), and the
`quotex_diagnose` PIN login is not stored by the script (the dashboard's is the one the engine uses).

**D-68. A refused Quotex login says what Quotex really answered.** The library reports a login it cannot
read as "Login failed. Unknown error" (or crashes on a non-2xx sign-in page) and keeps no trace of the page,
so the owner was left guessing (Cloudflare? a captcha? a wrong password?). While the library logs in, the two
methods that receive the pages (`Login.get_sign_page`, `Login.success_login`) are wrapped, only inside
`pyquotex_client.py` (the library-facing module, D-6) and only for the length of one login: the wrappers pass
every response on unchanged and the originals are restored whatever happens. The last page is described in
the error (status, address without its query, title, a short piece of its visible text; a Cloudflare or captcha
label only when the page's own markers say so) and saved, with the owner's email and password replaced, under
`backend/data/diagnostics/` (newest five kept) to open in a browser. Applies to the dashboard login and to the
engine's own login. Nothing is added when no page was seen (a saved token was used), and the old generic
explanations remain for that case. Not done: reading the page's own error box with a smarter parser; the page's
words are shown as they are.

**D-69. Docker, as an optional way to run it (supersedes the "no Docker" part of D-53).** D-53 declined Docker
because the logins needed a terminal; since they moved to the dashboard (D-58 to D-66) that reason is gone. The
image is built in three stages (the dashboard with Node, the packages with `uv` and git, and a slim runtime that
holds neither), runs as an ordinary user, and keeps everything it writes in one volume (`/data`: database, logs
and, by default, the key to the stored logins). Choices and why:
- **`CONTAINER=true`** is a new setting, set by the image, that lets the application listen on all addresses
  *inside* the container (which Docker needs) without touching the localhost-only host-name check; the older
  `ALLOW_PUBLIC_BIND` also switches that check off, which would have been the wrong tool. `compose.yaml`
  publishes the port to the host's `127.0.0.1` only, so the SSH-tunnel rule of D-53 still holds.
- **The key** is taken from `SECRET_KEY` if given, else made once into `/data/secret_key` (mode 600, never printed,
  never in the image). That puts it beside the database by default, which D-61 warns against; the guide says
  so and shows how to keep it apart.
- **A start script** (`docker/entrypoint.sh`) makes the key if needed and runs the migrations before the
  application starts (the application refuses a database that is behind), so an upgrade is a new image; a failed
  migration stops the container.
- **Hardening:** read-only root filesystem (plus a small `/tmp`), all capabilities dropped, no new privileges,
  a memory limit of 512 MB, `SIGINT` as the stop signal (the same orderly shutdown as Ctrl+C), the data on a
  named volume (SQLite is unreliable on folders shared with macOS or Windows).
- `.dockerignore` keeps `.env`, session files, databases and backups out of the build; `.gitattributes` keeps
  the script's Unix line endings on a Windows checkout and the Dockerfile also strips a stray carriage return.
- Not changed: `npm start` and the systemd guide stay (Windows; the leanest 1 GB setup). Not verified: a real
  Mac (including Apple Silicon) or a real server; the Docker service's memory cost on the 1 GB VPS is an estimate.

**D-70. An opposite pair for the flip strategies (amends D-9).** The owner wanted two opposite signals on one
asset, arriving together, to run as two separate chains: the one that loses recovers by flipping, the other ends
on its win. D-9 refused the second signal. Now each flip group has a switch, `allow_opposite_pair` (off by
default, so every existing group behaves as before; a migration adds it switched off). Rules:
- With the switch on and **one** chain running, a new signal is accepted only if it is the **opposite direction
  on the same asset** (compared with the running chain's *original* signal direction). Anything else, and any
  signal while two chains run, is ignored as before, and the inbox says which rule refused it (every reason
  still starts with "chain active").
- **Two chains at most** in the group. When one ends, the survivor can be paired again.
- The two are plain chains: own step, own loss counter, own stakes, own controls (*stop after current*, *end
  chain*); nothing is shared, and nothing in the engine's fast path changed (the check is the same in-memory,
  synchronous test in `on_signal`). The setting is refused (422) for martingale and no-martingale groups, which
  already run every signal as its own chain. Expiry is not compared: an opposite signal on the same asset joins
  even with a different expiry (then it is not a hedge).
- **Orders still go out one at a time (D-27).** The library keeps one shared slot for "order confirmed", so two
  orders cannot be in flight together without being able to tell their confirmations apart; that could not be
  checked against the live service here, so it was not attempted. The second order goes out the moment the
  first is confirmed. The gap is logged (`opposite_pair_sent`, `gap_ms`) so it can be measured on the demo
  account. In the default `TIME` mode the library picks the expiry from the clock when each order is built
  (`get_expiration_time_quotex`): an order built in the first half of the period expires at the next
  boundary, one built in the second half at the boundary after it. For a 1-minute trade the dividing line is
  second :30 of each minute, so a pair split by that second (a few in a thousand, at a gap of ~0.2 s) gets
  expiries a minute apart and is not a hedge. `QUOTEX_TIME_MODE=TIMER` (a countdown of the exact length from
  each order) has no such line, but it was not verified live either; try it on the demo account first.
- **Risk:** the exposure limit counts open trades only, so two chains each climbing the steps can stake up to
  twice a single chain's maximum; the group's max stake and daily stop-loss still apply to each order.

**D-71. Trading sessions: automatic trading from the dashboard, with no signal (Phases 16-18).** The owner wants
trades placed by a schedule, not by a Telegram message. A **trading session** is set up once on the dashboard:
one asset (the Quotex name, `EURUSD` or `EURUSD_otc`), the trade length (M5 = 300 s), a minimum payout, a
strategy (any of the four, with its stakes), a time window with a time zone and a repeat rule, and optional
profit and loss targets. While its window is open it opens **pairs**: a CALL and a PUT on the asset at the same
moment. Each leg is an ordinary chain (own step, stakes and controls, D-10): the winner ends on its win, the
loser follows the strategy (the flip, for the flip strategies). Telegram signals are **not affected** in any way
and keep their rules (D-9, D-70). How it fits the engine:
- A **session scheduler** inside the engine decides *when*; it hands the two legs to `ChainManager` as plain
  signals. The order path (`RiskGuard.admit`, executor, adapter) is the same code as for a Telegram signal, so
  every limit, the kill switch and the demo/real switch apply as before, and nothing was added to the fast path
  (the scheduler works before it, on a timer).
- The strategy part lives in an ordinary group-settings row of a **hidden group** that belongs to the session
  (`groups.source = 'session'`, no Telegram chat), so chains, trades, reports and the per-group limits work
  unchanged. The hidden group is not on the Groups page and is never listened to.
- Chains of a session are exempt from D-9: the scheduler is their gatekeeper (it opens a pair only if fewer than
  the allowed number of pairs are open). D-9 and D-70 stay as they are for Telegram groups.
- A session needs **Quotex only**. The Telegram login becomes optional for starting the engine; without it the
  engine starts with the signal source off and says so on the Settings page.
- Both legs are checked **before** either is sent (engine running, Quotex connected, asset open, payout at least
  the minimum). If a check fails the round is skipped, the reason is recorded, and nothing is sent, so a pair is
  never opened as a single, unhedged trade on purpose. Orders still go out one at a time (D-27): if the second
  leg is refused by a limit after the first was sent, the first runs on and the run records a "lopsided pair".

**D-72. A session stops softly, and a limit is not a cap on the loss.** When a session ends (the window closes, a
target is hit, the maximum number of pairs is reached, or the owner presses *Stop*) it **opens no more pairs, and
the chains already running finish** their steps. The run is `ended` when the last of its chains has ended.
- The session's **profit** is the sum of the `profit` of its settled trades (a draw counts 0; unknown and failed
  trades count nothing), per account type. A target is checked when a trade settles and again before each pair:
  profit at or above the profit target, or loss at or beyond the loss limit, stops the session.
- Because running chains finish, a loss that is *already in recovery* keeps climbing after the limit is hit. The
  loss limit therefore stops **new** pairs; it does **not** cap the total loss: the worst case is the limit plus
  the rest of every running chain's steps. The session form shows that worst case in figures (Phase 18). The
  global limits (max stake, exposure, daily stop-loss, kill switch) still apply to every order, and a chain
  blocked by them ends as before; the kill switch also ends the run (`kill_switch`).
- Each run records why it ended: `window_ended`, `profit_target`, `loss_limit`, `max_pairs`, `stopped`,
  `kill_switch`, `engine_stopped`, `interrupted`, `error`.

**D-73. Session schedule: one at a time, no catch-up, no resume.**
- **Repeat:** *once* (the next window only, never again) or chosen *weekdays* (every day, Monday to Friday, or any
  selection), in a time zone picked per session (daylight saving handled with `zoneinfo`, as in
  `signals/scheduling.py`). The window is `[start, end)`; it may cross midnight (a 23:00-01:00 window belongs to
  the day it started).
- **One session at a time.** Windows of enabled sessions may not overlap (checked when saving, over the whole
  week), and *Start now* is refused while a run is active. If a window nevertheless opens while another run is
  active, it is skipped and the reason is logged.
- **The first pair goes out at the start time** (23:00:00 for a 23:00 session). A check starts a minute before
  so the connection, the asset and the payout are known. If a check fails at the start time, the first pair waits
  for the next round (below).
- **Alignment.** Later pairs are placed at **candle boundaries**: multiples of the trade length counted from
  00:00 UTC (for M5: :00, :05, :10 ...). In the default `TIME` expiry mode the library picks the expiry from the
  clock when the order is built (see D-70): a trade built just after a boundary expires at the next one (a full
  M5); one built mid-candle may get a shorter or longer trade. So the form **warns** when the start time is not
  on a boundary of the trade length (it does not forbid it), and the sequential mode (below) places its next pair
  on the first boundary at or after the wait.
- **Two ways to space pairs** (one mechanism, two settings: how many pairs may be open at once, and when the next
  one is released):
  - *Sequential* (Phase 16): one pair at a time; when both of its chains have ended, wait a preset time (may be
    0), then open the next pair at the first candle boundary at or after the wait.
  - *Every candle* (Phase 17): a pair at every boundary, whatever is still running, up to a chosen **maximum of
    open pairs** (a pair is open while at least one of its chains runs). At a boundary with the maximum already
    open, that boundary is skipped and the skip is recorded.
- **Restart (D-35 applies).** A run that was still going when the application died is found at the next start and
  ends as `interrupted` (its chains are already marked `unknown` by recovery) and is **not resumed**. (A run that
  is open when the engine is stopped normally, the application's shutdown included, ends as `engine_stopped`.) A session whose window is open at start
  is **not started on its own** (that would be a resume); the next scheduled window starts normally, and *Start
  now* is available. A *once* session whose only run was interrupted is finished, not rescheduled.
- **Missed windows are skipped.** If the application, or the engine, was off when a window opened, that run does
  not happen and nothing is made up later.
- **Start now** runs a window of the session's usual length, beginning at once (the first pair at once, not at a
  boundary). It follows the same stop rules.
- A session trades on whichever account the engine is on (demo by default, D-15); it has no switch of its own.

**D-74. Deriv as a second broker, through its official WebSocket API (Phases 19-21).** Connecting to Quotex keeps
breaking (a Cloudflare check on the sign-in page, an unofficial library), and Quotex confirms orders one at a time
(D-27). Deriv publishes an official, documented API with demo accounts and API tokens. The adapter talks to
`wss://ws.derivws.com/websockets/v3?app_id=<the owner's app id>` with the `websockets` library already in use (no
Deriv SDK), and uses only `authorize`, `balance` (subscribed), `active_symbols`, `contracts_for`, `proposal`
(subscribed), `buy`, `proposal_open_contract` (subscribed) and `ping`. Only `app/deriv/` talks to Deriv (an
architecture test, as for pyquotex in D-6). The engine reaches both brokers through one protocol,
`BrokerAdapter` (`app/brokers/base.py`); `QuotexAdapter` stays as its name in the Quotex package.

**D-75. Both brokers at once.** The owner chose to run Quotex and Deriv side by side: `Broker` = `quotex | deriv`;
every group and every trading session has a broker (default `quotex`, so nothing changes for an owner who never
adds Deriv); chains, trades and balance snapshots record it. One demo/real switch and one real-money permission
cover all brokers (D-15 unchanged). The daily figures, the global limits and the exposure are kept per
`(broker, account type)`, because they are different accounts with different money; group limits are unchanged.
Reports never add two brokers' money together unless "all brokers" is chosen, and then they say so. The engine
starts with whichever brokers have logins and needs at least one; a signal or a session round for a broker that
is not connected is skipped with that reason. Orders on one broker never wait for the other.

**D-76. Deriv tokens: one per account, Read and Trade only.** Deriv's demo and real accounts each have their own
API token; both are stored encrypted (D-58), with the owner's registered app id. On connect the adapter checks
that the demo token belongs to a virtual account and refuses it otherwise, and refuses any token with the
`payments` or `admin` scope (the guide tells the owner to create tokens with **Read** and **Trade** only). The
real token is not used unless real money is allowed and chosen.

**D-77. Deriv order rules.** Trades are Rise/Fall (`CALL`/`PUT`) on the stake, with the trade length counted from
the purchase (like Quotex's `TIMER` mode, so the candle-boundary warning of D-73 still applies to the start time
only). An exit equal to the entry is a loss: Deriv has no draw on Rise/Fall. The payout percent the hot path
reads from memory comes from kept-alive `proposal` subscriptions per asset and trade length, started by
`prepare_asset` (for sessions) and for the assets of enabled Deriv groups; an unknown payout skips the signal
with that reason. Two kinds of assets are traded: **forex pairs**, named as on Quotex and mapped (`EURUSD` →
`frxEURUSD`; `_otc` pairs do not exist on Deriv and count as closed there), and **synthetic indices** (the
Volatility indices, the 1-second Volatility indices, Jump, Step and the others Deriv lists for Rise/Fall), named by
Deriv's own symbol (`R_75`, `1HZ100V`) and shown with Deriv's display name ("Volatility 75 Index"). Synthetic
indices trade around the clock. The trade lengths allowed for an asset come from `contracts_for`, never from a
fixed list: the owner reports (2026-11-17) that forex Rise/Fall starts at 15 minutes while synthetic indices allow
1 and 5 minutes; a signal, a session round or a form with a length the asset does not offer is skipped or refused
with that reason. Orders are **not** serialised: every request carries a unique `req_id` and its reply is matched
by it, so the two legs of a pair go out together. D-27 stays a Quotex rule. An order without a confirmation is
still `OrderAckTimeoutError` ("may have been placed", never retried).

**D-74, D-76, D-77 amended in Phase 19 (Deriv's current API, read from developers.deriv.com and its JSON
schemas on 2026-11-17).** Deriv has replaced the API these decisions were written for:
- **Login (D-74, D-76).** There is no `authorize` call and no fixed socket address any more. The owner's
  Personal Access Token and the app id go in the headers (`Authorization: Bearer ...`, `Deriv-App-ID`) of two
  REST calls to `https://api.derivws.com/trading/v1/`: `GET options/accounts` lists the token's accounts, and
  `POST options/accounts/{id}/otp` returns a one-time link, `wss://.../options/ws/demo?otp=...` or
  `.../ws/real?otp=...`, valid once and for 120 s. Every (re)connect asks for a new link (`app/deriv/login.py`).
- **The account check (D-76)** is made three times: the account picked from the list (Deriv's `account_type`
  / `group` field decides; the account number only when that field is missing), the link's own path
  (`/ws/demo` or `/ws/real`), and the `loginid` of the first balance on the socket. Demo numbers start `VR`
  (old API) or `DOT` (new Options API, e.g. `DOT90004580`); real ones `CR`, `MF`, `MLT`, `MX`. A number with
  any other prefix is not read as either kind (the new real numbering is undocumented), so the first two checks
  decide for it. Any disagreement refuses the login and is never retried. A token that reaches several real accounts is refused rather than guessed.
- **Scopes (D-76).** The API does not tell an application which permissions a token has, so the adapter cannot
  refuse a token with the `payment` permission itself; the guide tells the owner to create tokens with
  **Trade** only. A missing Trade permission shows as Deriv refusing the calls.
- **Message names (D-77).** A symbol is `underlying_symbol` (in `active_symbols`, `contracts_for`, `proposal`
  and in the `parameters` of `buy`), its name `underlying_symbol_name`; `buy` is `"1"` with `parameters`; the
  result's `profit` is text. `req_id` is used as before.
- **Payouts (D-77).** Deriv does not stream quotes for under-24-hour Rise/Fall on the Volatility indices, so the
  payout comes from a one-off `proposal` per prepared asset and trade length, asked again every 30 s (well
  inside the 360-a-minute limit shared with `buy`); a quote that fails removes the figure, so nothing trades
  on a stale payout.
- **Trade lengths (D-77).** `contracts_for` may write a length without a unit (its example says `"5"`); a
  length that cannot be read is never guessed: Deriv's own refusal of the order decides, and nothing is placed.
- **Rise/Fall entries (D-77), seen on the live demo.** Deriv marks Rise/Fall (`callput`, `CALL`/`PUT`) with
  `barriers: 1` (the entry price); Higher/Lower has its own `higherlower` category, and `callputequal` (an
  equal exit wins) is a different contract. Rise/Fall is recognised by category and type only.

**D-75 settled in Phase 20 (how the two brokers share the engine).**
- **One switch, all or nothing.** The demo/real switch moves every broker or none: a broker that cannot go to
  REAL (no permission, no Deriv real token) refuses the switch, and the brokers already moved go back.
- **A signal the broker cannot take is skipped, before a chain starts**, with the reason in the inbox: the
  broker has no login ("Deriv is not set up"), is not connected ("Quotex is not connected"), does not trade the
  asset (`_otc` on Deriv), or does not offer the trade length on it (Deriv: "it offers 15 min to 365 days").
  All read from memory: the Deriv adapter learns every open asset's trade lengths in the background after it
  connects (a few assets a second). For Quotex this replaces "the chain starts and fails" when Quotex is
  down; Quotex's closed assets are still refused when the order is placed, as before.
- **Limits per broker.** The day's result, the daily stop-loss and profit target, the open-trade count and the
  exposure limit are counted per broker and account type; a group's own limits are unchanged (a group has
  one broker). The day's figure for the dashboard is given per broker and as a labelled total.
- **One session at a time stays**, across both brokers (D-71): two sessions' windows may not overlap even if
  they are on different brokers.
- **Indexes.** The broker indexes are added next to the account-type ones the reports use today; the old
  ones go when the reports filter by broker (Phase 21).
- **Stopping** cancels every broker's connect loop first, then closes each broker with a 10 s limit, so a
  broker that does not answer can no longer keep the application from stopping (the hang of 2026-11-13).

**D-75, D-76 settled in Phase 21 (Deriv on the dashboard and in the reports).**
- **Deriv's logins are stored like the others** (D-60, D-67): `deriv_app_id`, `deriv_token_demo` and
  `deriv_token_real` in the encrypted store, under their own part of the Settings page; a stored value wins
  over `.env`, and "move the logins out of `.env`" covers them. `npm run deriv:check` reads the stored ones too.
- **Check without trading.** The *Check* button reads Deriv's account list only (the REST call that comes before
  the one-time link): the account number, its kind, currency and balance. No socket is opened, nothing is
  traded, and the engine need not be stopped.
- **Reports show one broker unless "all" is asked for.** The API's `broker` filter is `quotex` by default (the
  answers of earlier dashboards stay what they were), `deriv`, or `all`; the dashboard starts on the engine's
  only broker when it has one, else Quotex, and puts a note above the figures when "All brokers" is chosen.
  The trades CSV gains a `broker` column (after `account`). The old account-type indexes stay: queries
  without a broker filter ("all") still use them, and the broker ones serve the rest.
- **Deriv's asset list comes from the running engine** (`GET /deriv/assets`), never from a call of its own:
  with the engine stopped or Deriv not connected the form says why and the asset is typed. The trade lengths
  an asset does not offer are shown but cannot be chosen, and the server still refuses them (D-75).

**D-78. A dropped broker connection never stops the engine (Phase 22).** Seen twice on 2026-11-18:
a Deriv drop with trades open froze the whole engine. No retry loop in an adapter may run again without waiting
(for the drop to be seen, for the next connection, or a backoff). A trade waiting for its result follows its
contract again after a reconnect, within its time limit. A Deriv trade left `open` or `unknown` by a drop, a crash
or a stop is settled from Deriv by its contract id (Deriv keeps every contract), so `unknown` is only for what
Deriv itself cannot report. **Amends D-35 for Deriv**; Quotex trades keep D-35.

**D-79. A chain continues unless a trade time was missed; no margin (Phase 22; owner's rule).** A
chain's next trade is due when its open trade expires (a step goes out as soon as the result is known); a
session pair is due at its candle. If the connection, or on Deriv the program, is back before that, the chain
continues as if nothing happened. If not, the open trade still gets its real result, but the chain ends with
the reason "a step was due while the connection was down"; a due step is never sent late. After a restart, a
session run whose window is still open resumes with its counters read back, and the rounds missed meanwhile
count as skipped. **Amends D-73** ("no resume"); one run at a time and no catch-up still hold.

**D-80. A stall watchdog (Phase 22).** A thread outside the event loop checks every second that the
loop still turns. After 10 s without a turn it logs `engine_stalled` with the loop's stack trace (then every 60
s while stalled). Ctrl+C asks for a normal stop; if the loop has not stopped 15 s later, the process ends
anyway, and the next start settles what was in flight (D-78). It never restarts the engine by itself: the
owner, or a service manager on the VPS, does that.

**D-81. A switch per broker (Phase 23).** Each broker can be switched off and on from the dashboard
while the engine runs; the choice is stored. Off closes its connection and stops its login attempts; on
connects at once; nothing else is touched. Switching off is refused while that broker has open trades, active
chains or a running session. Signals and sessions on an off broker are skipped with that reason. A login
failure that more attempts cannot fix (an email PIN, a refused password or token) stops the retries and waits
for the owner ("needs you"); network and Cloudflare errors keep the backoff.

**D-82. Deriv results as soon as they are certain (Phase 24).** Deriv marks a contract sold about
3.6 s after its expiry, and each martingale step waits for that. The engine may act on the result as soon as
the exit price is known (from the contract update that carries it, or from the asset's price stream, chosen
after the owner's live measurement), by Deriv's Rise/Fall rule (equal is a loss). Deriv's own result is the one
stored; a disagreement is marked on the trade and logged. The early path can be switched off in the settings.

**D-78 to D-80 settled in Phase 22.**
- **How "missed" is decided.** Each adapter says when the connection in use was made
  (`connected_since`). A settled loss whose trade expired before that moment had its next step due while
  the connection was down: the chain ends (`failed`, "missed: ..."). A step that comes due while the broker
  is not connected is not sent ("missed: step N was due while Deriv was not connected"). No new chain
  status: `failed` with that reason.
- **Ctrl+C is not Stop.** The application closing (Ctrl+C, a service stop, a crash) leaves chains, trades
  and a session run as they are, so the next start carries them on (Deriv chains, session runs) or looks
  them up (Deriv trades). The owner pressing *Stop* on the dashboard ends the run (`engine_stopped`) and
  marks what was in flight `unknown` at once, as before; the next start still reads the Deriv results of
  those trades.
- **Where a run carries on.** A run carries on only when it was `running` (not `stopping`), its window is
  still open, its session exists and is switched on, the kill switch is off and the account is the same.
  Missed rounds are counted on the every-candle mode (each candle is a round); a one-pair-at-a-time run
  first lets a pair it carried on finish.
- **Quotex** keeps D-35 after a restart. During a reconnect inside a running engine the same "missed"
  rule applies, but its open trade usually ends `unknown`, because our Quotex adapter waits for a result
  on the connection that placed the order, and that connection is gone.
- **Payout before the first round.** Every run asks the broker for the asset's payout before its first
  round (a no-op when a scheduled start did it a minute ahead), and a round that finds no payout asks for
  it in the background. The fake Deriv now knows a payout only after it was asked for, like Deriv.
- **The watchdog** checks every second and reports after 10 s without a turn; Ctrl+C (SIGINT, and SIGBREAK
  and SIGTERM where they exist) also starts its 15 s exit clock. The brokers now close at the same time
  when the engine stops, so a normal stop takes at most 10 s.

**D-81 settled in Phase 23.**
- **Where the switch is.** On the Settings page (*Brokers*), with each broker's state in words; the top-bar badge
  shows "off" or "needs you" (the reason as its tooltip) but has no menu of its own.
- **Stored** as `broker.<name>.enabled` next to the engine's other remembered choices (D-63). It can be set with
  the engine stopped; a started engine never connects an off broker.
- **"Needs you"** is a login error the adapter marks as one more attempts cannot fix (`LoginRejectedError`):
  Quotex's e-mailed PIN, Deriv's refused token. Switching the broker off and on (or restarting the engine)
  tries again. Network and Cloudflare errors keep the backoff, as before.
- **A session on an off broker:** *Start now* is refused (409 `broker_off`); a scheduled run starts and every
  round is skipped with "Deriv is switched off", so the run's history says why nothing traded.

**D-82 settled in Phase 24.**
- **From the price stream, not from the contract updates.** Deriv's schema says what the exit tick is but
  not when it appears in `proposal_open_contract`; the price stream (`ticks`) says it the moment a tick at
  or after the end time arrives. The engine follows the ticks of an asset while it has a contract on it;
  the exit price is the latest tick at or before `date_expiry`, certain once a tick at or after it has
  come. If the ticks before the end time were not seen (the stream started too late), there is no early
  result: Deriv's own is awaited.
- **Off by default** (`deriv_early_result`, Settings): the owner switches it on after
  `deriv:check --order --timeline` showed the early result and Deriv's agree on the demo.
- **A correction** (Deriv's own result differs): the trade is stored with Deriv's result and a note, the
  risk guard books the difference on the trade's day, and a `risk.tripped` event
  `early_result_corrected` is published. The chain is not touched (it already acted).
- **The latency report** gains `expiry -> result` and `expiry -> next`, measured on the wall clock from the
  times stored on each trade.

**D-83. The growing flip strategy (Phase 25, proposed; owner's design).**
- **The rule:** a fifth strategy, `growing_flip` ("Growing flip"). Step k goes in the first trade's direction
  or the opposite, in blocks of 1, 1, 2, 2, 3: same, flipped, same, same, flipped, flipped, same, same, same.
  From Buy: Buy, Sell, Buy, Buy, Sell, Sell, Buy, Buy, Buy; from Sell, the mirror.
- **How a chain runs:** at most 9 trades (8 follow-ups, 8 multipliers). A win ends the chain; the ninth loss
  ends it `exhausted`, like the other strategies.
- **In a session** each leg follows the pattern from its own first direction, so the CALL and PUT legs are
  mirrors of each other.
- **It is a flip strategy for D-9 and D-70:** in a Telegram group, one chain at a time, or the opposite pair
  if allowed.

---

## Decisions to be made later (record here when decided)

- (Decided in Phase 8: charts — see D-48.)
- (Decided in Phase 0: package manager = `uv`, pyquotex pin — see D-19 and D-5.)
- (Decided in Phase 1: money representation — see D-22.)
- Whether and how to support early close of single trades — after Phase 9.
