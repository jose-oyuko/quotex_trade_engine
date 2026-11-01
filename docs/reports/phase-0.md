# Phase 0 — Foundation and tooling — Report

**Date:** 2026-11-01
**Status:** Done with open items (two things not verified, see section 7)

## 1. Summary
Phase 0 delivered an empty but fully wired project. The backend (FastAPI on Python 3.12, managed by
`uv`) starts, answers `GET /api/v1/health`, and refuses to listen on a public address unless
`ALLOW_PUBLIC_BIND=true`. The frontend (React 18 + Vite + TypeScript strict) has one page that calls
the health endpoint and shows the result, with a dev proxy for `/api` and `/ws`. The pinned
`pyquotex` 1.1.0 installs and imports. One command, `npm run check`, runs lint, type checks, tests and
the build for both sides, and all of it passes.

## 2. What was done
- **Repo hygiene:** `.gitignore` (venvs, `node_modules`, `data/`, `.env*`, `*.session`, `session.json`,
  build output, caches, local databases), `.env.example`, `README.md` with setup, run, checks and a
  security note.
- **Backend** (`backend/`):
  - `pyproject.toml`: Python `>=3.12,<3.13`, all dependencies from the phase scope, `pyquotex` pinned
    to commit `a50a030…`, ruff / mypy (strict) / pytest configuration. `uv.lock` generated.
  - `app/core/config.py`: `Settings` (pydantic-settings), safe defaults (loopback, port 8000, no
    public bind); a validator rejects non-loopback hosts unless `allow_public_bind` is set.
  - `app/core/logging.py`: structlog + stdlib routed through one pipeline; readable in development,
    JSON in production.
  - `app/core/tasks.py`: `TaskSupervisor` — keeps task references, logs unhandled exceptions,
    cancels and awaits tasks on shutdown.
  - `app/main.py`: `create_app()` with lifespan (starts logging; shutdown stops the supervisor);
    `app/api/health.py`: `GET /api/v1/health`; `app/__main__.py`: `python -m app` entry point that
    prints the refusal message and exits with code 2.
- **Frontend** (`frontend/`): Vite + React 18 + TypeScript (`strict`, `noUncheckedIndexedAccess`),
  ESLint 9 (typescript-eslint strict-type-checked, react-hooks, jsx-a11y), Prettier, Vitest + React
  Testing Library, dev proxy `/api` and `/ws` → `127.0.0.1:8000`, health page
  (`src/App.tsx`, `src/api/health.ts`) with loading / error / OK states.
- **Scripts** (root `package.json`, work on Windows/macOS/Linux): `setup`, `backend`, `frontend`,
  `test`, `lint`, `typecheck`, `build`, `check`.
- **Docs:** D-5 (pin recorded), D-19 (`uv` decided) updated; D-21 added; this report; STATUS.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Fresh clone → documented setup steps → backend and frontend start; the page shows health OK | ⚠️ partly | `npm run backend` + `npm run frontend` started; `GET /api/v1/health` returned 200 both directly and through the Vite proxy (`curl`). Page behaviour covered by component tests with mocked `fetch`. **Not done:** a real clean-clone run and a look at the page in a browser (section 7). |
| `ruff check`, `ruff format --check`, `mypy`, `pytest`, `eslint`, `tsc --noEmit`, `vitest` all pass | ✅ | Section 4 |
| `pyquotex` importable in the venv (import only) | ✅ | `tests/unit/test_pyquotex_import.py` imports it and asserts version `1.1.0` |
| `HOST=0.0.0.0` with no flag is refused with a clear message (test) | ✅ | `tests/unit/test_config.py::test_public_bind_is_refused_without_flag` (4 hosts), `::test_public_bind_refused_from_environment`; manually: `HOST=0.0.0.0 npm run backend` printed "Refusing to listen on '0.0.0.0' …" and exited with code 2 |
| No secrets or generated junk in the tree | ✅ | `git status --short --ignored` shows only intended files; build output, venv and caches are ignored; grep for password/secret/token finds only documentation text |

## 4. Checks run

```
$ npm run check          (lint → typecheck → test → build, from the repo root)
ruff check .                      All checks passed
ruff format --check .             15 files already formatted
eslint .                          no output (clean)
prettier --check .                All matched files use Prettier code style
mypy                              Success: no issues found in 9 source files
tsc -b --noEmit                   no output (clean)
pytest                            17 passed in 1.16s
vitest run                        3 passed (1 file)
vite build                        built in 1.36s (js 144.89 kB, gzip 46.67 kB)
```

Runtime checks:
```
$ curl http://127.0.0.1:8000/api/v1/health    → {"status":"ok","version":"0.1.0",...} HTTP 200
$ curl http://127.0.0.1:5173/api/v1/health    → same body, HTTP 200 (through the Vite proxy)
Listening sockets: 127.0.0.1:8000 and 127.0.0.1:5173 only
```

## 5. Challenges and how they were resolved
1. **No usable Python 3.12 on the machine** — cause: system Python is 3.9, and the registered
   `C:\Python312` install is broken (uv warned it cannot query it) — resolution: `uv python install 3.12`
   (managed copy, 3.12.15); nothing on the system was touched — remaining risk: none.
2. **Frontend build failed: "Cannot find native binding"** — cause: the Vite scaffold pulled Vite 8,
   whose bundler needs Node ≥ 20.19, and the machine has Node 20.15.1. A clean reinstall did not help,
   so it was not the npm optional-dependency bug the error message suggests — resolution: pinned the
   newest versions that support Node 20.15 (Vite 6, plugin-react 4, Vitest 3, jest-dom 6.6, jsdom 26,
   TypeScript 5.9, ESLint 9), recorded as D-21 — remaining risk: npm still prints `EBADENGINE`
   warnings for a few transitive packages (e.g. `eslint-visitor-keys`); they are warnings only and
   everything runs.
3. **Scaffold did not match the docs** (React 19, TypeScript 7, oxlint, no `strict`) — resolution:
   replaced with React 18 (as in `ARCHITECTURE.md`), ESLint with the plugins `CONVENTIONS.md` asks for,
   and strict TypeScript — remaining risk: none.
4. **pydantic wraps validator errors** — my first `__main__.py` caught the wrong exception type, so the
   refusal would have shown a traceback. Found before running it; now catches `ValidationError` and
   the manual run confirmed the message and exit code 2.
5. **`uv sync` took more than 5 minutes** on the first run (cloning `pyquotex` from GitHub). It ran in
   the background and succeeded; later runs are fast.

## 6. Deviations from the plan
- **React 18 / toolchain versions are older than "latest"** because of the Node version (D-21).
- **Dependencies are declared as ranges (`>=`) in `pyproject.toml`**, with exact versions in `uv.lock`
  and `package-lock.json`. Conventions say "pin versions"; the lock files do that. The git dependency
  is pinned to an exact commit.
- New/updated decisions: **D-5** (pin recorded), **D-19** (`uv`), **D-21** (frontend versions).

## 7. Could not be verified
1. **Clean-clone setup.** I ran `uv sync` and `npm install` from scratch inside the existing folder
   (and re-did `npm install` from an empty `node_modules`), but did not clone into a new directory or
   machine. To check: in a new folder, clone/copy the repo, run `npm run setup`, then `npm run backend`
   and `npm run frontend`. Success = both start and <http://127.0.0.1:5173> shows "Health OK".
2. **Page in a real browser.** The "Health OK" text is verified by component tests (mocked `fetch`) and
   the proxy by `curl`, but I did not open the page in a browser. Success = green "Health OK — version
   0.1.0, development" text; with the backend stopped, a red "Backend not reachable" message.

## 8. Measurements
None this phase (no hot path yet).

## 9. New dependencies / files of note
Backend runtime: fastapi 0.162, uvicorn[standard] 0.54, pydantic-settings 2.16, sqlalchemy[asyncio] 2.1,
aiosqlite 0.22, alembic 1.20, telethon 1.45, structlog 26.1 (all required by the phase scope, used from
later phases), pyquotex 1.1.0 @ `a50a030` (brings curl-cffi 0.17). Dev: ruff 0.17, mypy 2.4, pytest 9.2,
pytest-asyncio 1.4, httpx 0.28.
Frontend: react 18.3, vite 6.4, vitest 3.2, typescript 5.9, eslint 9, typescript-eslint 8, prettier 3,
Testing Library, jsdom 26 (see `frontend/package.json`).
Files of note: `backend/app/core/config.py` (bind rule), `backend/app/core/tasks.py` (supervised tasks),
`package.json` (root scripts), `frontend/vite.config.ts` (proxy).

## 10. Suggestions and open questions
- **Upgrade Node to 22 LTS** at some point. It lifts the version limits in D-21 and removes the
  `EBADENGINE` warnings. Not needed for the project to work.
- `uvicorn app.main:app --host 0.0.0.0` bypasses the bind check because the host is a command-line
  argument. The README says to start with `npm run backend` / `python -m app`. A stronger guard
  (checking the real listening address at startup) could come in Phase 9; not built now.
- `backend/.env` is read relative to where the backend is started (`npm run backend` starts it in
  `backend/`). `data/` therefore also appears under `backend/` at runtime (git-ignored). The
  architecture sketch shows `data/` at the repository root; say if you prefer that and I will set the
  default path in Phase 1 when the database appears.
- The `S` (security) ruff rules are on, and tests carry a few `noqa` markers for the deliberate
  `0.0.0.0` strings.

## 11. Git state
**No commits were made and nothing was staged.** `git status --short`:
```
 M docs/DECISIONS.md
?? .env.example
?? .gitignore
?? README.md
?? backend/
?? frontend/
?? package.json
```
The owner's commit `77a5ded agent guide files` (CLAUDE.md and docs/) appeared during the phase; I did
not make it. `docs/STATUS.md` is also modified by this phase (it shows as `M` once saved).
