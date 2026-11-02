# Quotex Trade Engine

A local web app that listens to several Telegram signal groups, turns the signals into Quotex
binary-option trades, runs a martingale / flip strategy per group, stores everything in a database
and shows it on a live dashboard with reports.

> **Status:** under construction, built phase by phase. See [docs/STATUS.md](docs/STATUS.md).
> Right now only the empty, wired-up foundation exists (Phase 0): a backend with a health check and a
> frontend page that shows it.

## Security note (read this)

- **Quotex has no official API.** This project uses an unofficial library (`pyquotex`) that imitates
  the Quotex website. It can break at any time, and automated trading may break Quotex's rules and
  get an account restricted. Keep real balances small. The app defaults to the **demo** account.
- **There is no login.** Whoever can reach the server can control trading. The server therefore listens
  on `127.0.0.1` only and **refuses to start on any other address** unless you set
  `ALLOW_PUBLIC_BIND=true`. Do not do that on an open network.
- **Credentials stay on your machine.** Telegram keys, Quotex password and session files live in
  `.env` and `data/`, both git-ignored. They are stored unencrypted for now, so protect the folder
  with normal file permissions. Never paste them into issues, logs or chat.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | recent | Installs Python 3.12 and the backend dependencies |
| Node.js | 20.15 or newer (tested on 20.15.1 and 26.13) | The frontend tools are pinned to versions that also work on Node 20.15 |
| Git | any | `pyquotex` is installed from GitHub |

You do not need Python installed yourself: `uv` downloads Python 3.12 when needed.

## Setup

From the repository root:

```
npm run setup
```

This runs `uv sync` for the backend (creates `backend/.venv`, installs everything including the pinned
`pyquotex`), `npm install` for the frontend, and `npm run db:upgrade`, which creates the database
(`backend/data/quotex.db`, git-ignored). The first run takes a few minutes because `pyquotex` is
fetched from GitHub.

The backend refuses to start if the database has not been created or is behind the code. After
pulling new code, run `npm run db:upgrade` again; it only applies what is missing.

| Command | What it does |
|---|---|
| `npm run db:upgrade` | Create or update the database to the newest schema |
| `npm run db:downgrade` | Remove every table (back to an empty database). **Deletes all data.** |

Optional: copy `.env.example` to `backend/.env` to change settings (port, log level, ...). The
defaults are safe and need no file.

## Run (development)

Two terminals, both from the repository root:

```
npm run backend      # API on http://127.0.0.1:8000
npm run frontend     # dashboard on http://127.0.0.1:5173
```

Open <http://127.0.0.1:5173>. The page should say **Health OK**. The dev server forwards `/api` and
`/ws` to the backend, so the browser only ever talks to one address.

Always start the backend with `npm run backend` (or `python -m app`), not with a bare `uvicorn`
command: that is what enforces the loopback-only rule.

## Checks

| Command | What it does |
|---|---|
| `npm run lint` | ruff (check + format check), ESLint, Prettier check |
| `npm run typecheck` | mypy (strict) and `tsc --noEmit` |
| `npm run test` | pytest and Vitest |
| `npm run build` | production build of the frontend |
| `npm run check` | all of the above |

## Layout

```
backend/    FastAPI app (app/), tests (tests/), pyproject.toml, uv.lock
frontend/   React + Vite + TypeScript dashboard
docs/       architecture, decisions, phases, status, phase reports
data/       created at runtime (git-ignored): database, sessions, logs
```

Start with [CLAUDE.md](CLAUDE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) to see how the
parts fit together.
