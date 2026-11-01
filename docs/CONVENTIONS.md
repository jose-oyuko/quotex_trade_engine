# Engineering Conventions

Standards for all code in this repository. When a rule here conflicts with convenience, the rule wins;
if a rule is genuinely wrong, say so in the phase report instead of silently breaking it.

## 1. General

- Small, focused modules and functions; names say what things *are* (`ChainManager`, `place_order`).
- Prefer explicit over clever. No dead code, no commented-out code, no TODOs without a tracked entry
  in the phase report.
- Comments explain **why**, not what. Public functions/classes get short docstrings.
- Dependencies: add only what is needed, pin versions (lock file committed once the owner allows commits),
  and mention every new dependency and why in the phase report.
- Decisions that change the architecture go to `docs/DECISIONS.md` (new ID), not just into code.
- Never log or commit secrets. Redact tokens/passwords in error messages.

## 2. Backend (Python 3.12, FastAPI)

### Style and tooling
- **ruff** for lint and format (line length 100); **mypy --strict** on `app/`; both must pass.
- Full type hints everywhere. Use `from __future__ import annotations` only if needed; use `X | None`.
- Pydantic v2 models for all API I/O and settings; `dataclass(slots=True, frozen=True)` or plain typed
  classes for internal value objects. No untyped dicts crossing module boundaries.
- Use `enum.StrEnum` for statuses/directions/strategies; the same enums are used by the DB and the API.

### Async rules (critical for this project)
- Never block the event loop: no `requests`, `time.sleep`, sync file/DB I/O in hot paths. Use async
  libraries or `asyncio.to_thread`. Console `input()` is never used inside the app.
- Create background tasks only through the supervised helper in `core/tasks.py`: it keeps a reference,
  logs unhandled exceptions, supports cancellation and is awaited at shutdown.
- Always use timeouts for external calls (`asyncio.timeout`), and handle `CancelledError` properly
  (cleanup, then re-raise).
- Shared mutable state is touched only on the event loop. No `await` between a read and the dependent
  write of the same state unless it is documented why that is safe.
- Use monotonic time (`time.perf_counter_ns`) for latency, UTC `datetime` for stored timestamps
  (timezone-aware, never naive). Inject a clock so tests can control time.

### Structure
- Layering: `api` → `engine/services` → `db repositories` / `quotex` / `telegram`. Lower layers never
  import upper layers. `engine` knows nothing about FastAPI. `quotex/` is the only place importing `pyquotex`.
- Dependency injection through FastAPI `Depends` for request handlers; explicit constructor injection
  elsewhere (no module-level singletons holding connections).
- Routers are thin: validate → call a service → map to a response model. Business rules live in
  `engine/`. DB access only through repositories.
- Application lifecycle in the `lifespan` context manager: start Telegram/Quotex/engine/DBWriter, and
  shut them down in reverse order with a flush.

### FastAPI practices
- Version the API (`/api/v1`). Use `APIRouter` per area, tags, `response_model`, explicit status codes.
- Consistent error body (`{"error": {"code", "message", "details"}}`) via exception handlers; no stack
  traces to clients.
- Validate everything at the edge (Pydantic constraints: positive stakes, ranges, list lengths).
- Pagination and filtering on list endpoints; never return unbounded lists.
- CORS: only the dev origin in development; none in production (same origin).
- Settings via `pydantic-settings`; all configuration through environment/`.env`; sensible, safe defaults
  (demo account, loopback bind).
- Health endpoint reports component status; no secrets in it.
- WebSocket: bounded per-client queues, heartbeat, sequence numbers, drop-and-resync for slow clients.

### Database
- SQLAlchemy 2.x style (`select()`, typed `Mapped[]`), async sessions, one session per unit of work.
- Alembic for every schema change; migrations are reviewed and reversible. No `create_all` in production code.
- Indexes for each query pattern used by the dashboard/reports; verify with `EXPLAIN` when in doubt.
- Money: never `float`. Use the representation chosen in Phase 1 consistently.
- Keep transactions short; batch writes in `DBWriter`.

### Errors and logging
- Define a small exception hierarchy (`DomainError`, `QuotexError`, `RiskBlocked`, …). Don't use bare
  `except:`; catch specific exceptions and either handle or re-raise with context.
- Structured logging with `signal_id`/`chain_id`/`trade_id`; INFO for lifecycle events, DEBUG for detail,
  WARNING/ERROR for problems. No emojis or `print` in library code.

### Testing
- **pytest** + **pytest-asyncio**; `tests/unit`, `tests/integration`, shared fixtures in `conftest.py`.
- The fake Quotex adapter and a fake Telegram source drive integration tests — **tests never touch the
  real services** and never need credentials. Live checks are separate, opt-in scripts (marked, skipped by default).
- Strategy logic and parsers get table-driven tests from `docs/DOMAIN.md` and real messages.
- Fix flaky tests, never retry-until-green. Tests must run offline and fast.

## 3. Frontend (React 18, Vite, TypeScript)

### Style and tooling
- TypeScript **strict**; no `any` (use `unknown` + narrowing); no `// @ts-ignore` without a reason.
- ESLint (with `typescript-eslint`, `react-hooks`, `jsx-a11y`) and Prettier; `tsc --noEmit` must pass.
- Function components + hooks only. Co-locate component, styles and tests; one component per file.
- Names: components `PascalCase`, hooks `useThing`, files match the main export.

### Structure
- Feature folders (`features/chains`, `features/groups`, …) with their own components/hooks/api;
  shared UI in `components/`, utilities in `lib/`, typed API client in `api/`.
- Types for API data come from the OpenAPI schema (generated) or one hand-written module mirroring it;
  never re-declare the same shape in several places.

### State and data
- **TanStack Query** for server state (caching, retries, invalidation); the WebSocket client updates the
  Query cache instead of keeping a parallel store. Handle reconnect → refetch snapshot.
- Local component state first; a small store (Zustand) only for genuinely global UI state.
- Forms: React Hook Form + Zod schemas mirroring the backend validation (e.g. one multiplier per step).
- No data fetching in render; no derived state stored in state — compute it (`useMemo` only when measured).

### UX and quality
- Always handle loading, empty and error states. Destructive actions (kill switch, end chain) need a
  confirmation and show the DEMO/REAL account clearly.
- Accessibility: semantic HTML, labels for inputs, keyboard operable controls, sufficient contrast.
- Performance: virtualise or paginate long tables, avoid re-render storms from the event stream
  (batch updates per animation frame, select narrow slices), code-split routes.
- Never store secrets in the frontend; it has no credentials. Escape/render untrusted text (Telegram
  messages) as plain text, never as HTML.
- Tests: **Vitest + React Testing Library** for components and hooks; test behaviour, not implementation.
  Mock the API layer, not React internals.

## 4. Git hygiene (agent rules)

- **The agent never commits, pushes or alters history** unless the owner explicitly asks.
- Do not stage files either; leave the working tree for the owner to review.
- When the owner allows commits later: small commits, imperative messages, one concern each,
  conventional prefix (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), no secrets, no generated artefacts.
- `.gitignore` is maintained as the project grows (Phase 0 creates it).

## 5. Security checklist (apply in every phase)

- Bind to `127.0.0.1` by default; refuse public bind without explicit opt-in.
- No secrets in code, logs, reports, test fixtures or the frontend bundle.
- Validate and bound all inputs (including Telegram message length before parsing).
- Treat Telegram message content as untrusted: never `eval`/format it into SQL/HTML/shell.
- Rate-limit and size-limit anything exposed on the API; keep dependencies updated and minimal.
- The account type (DEMO/REAL) must be unmistakable in the UI, the logs and every trade record.
