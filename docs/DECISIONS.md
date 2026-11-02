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

---

## Decisions to be made later (record here when decided)

- Chart library — Phase 8.
- (Decided in Phase 0: package manager = `uv`, pyquotex pin — see D-19 and D-5.)
- (Decided in Phase 1: money representation — see D-22.)
- Whether and how to support early close of single trades — after Phase 9.
