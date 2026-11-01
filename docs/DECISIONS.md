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

**D-20. In production FastAPI serves the built frontend** (single process, single port); in
development Vite's dev server proxies `/api` and `/ws` to FastAPI.

---

## Decisions to be made later (record here when decided)

- Money representation (integer minor units vs `Numeric`) — Phase 1.
- Package manager for the backend (`uv` vs `pip`) — Phase 0.
- Chart library — Phase 8.
- pyquotex pinned commit hash — Phase 0/2.
- Whether and how to support early close of single trades — after Phase 9.
