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
signal with the reason.

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

---

## Decisions to be made later (record here when decided)

- Chart library — Phase 8.
- (Decided in Phase 0: package manager = `uv`, pyquotex pin — see D-19 and D-5.)
- (Decided in Phase 1: money representation — see D-22.)
- Whether and how to support early close of single trades — after Phase 9.
