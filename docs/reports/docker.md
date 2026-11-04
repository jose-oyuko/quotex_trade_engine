# Docker support — Report

**Date:** 2026-11-04
**Status:** Done with open items: the image was built and run on this PC (Windows, Docker Desktop 27.0.3) and
checked as listed below. A real Mac (Apple Silicon too), a real server, and the real Telegram and Quotex logins
inside the container were **not** tried.

## 1. Summary
The application can now run as one Docker container: `docker compose up -d --build`, then the dashboard at
<http://127.0.0.1:8000>. The image is 297 MB, runs as an ordinary user with a read-only filesystem, keeps all its
data in one volume, makes the key to the stored logins on first start, upgrades the database before it starts, and
publishes its port to the host's `127.0.0.1` only. It is optional: `npm start` (Windows) and the systemd guide (the
leanest setup for a 1 GB server) stay. Decision D-69 records why Docker is now acceptable (D-53 had declined it
because the logins needed a terminal).

## 2. What was done
- `Dockerfile` (three stages: dashboard with Node, packages with `uv` and git, slim runtime with neither),
  `compose.yaml`, `docker/entrypoint.sh`, `.dockerignore`, `.gitattributes` (Unix line endings for the script).
- `core/config.py`: the setting `CONTAINER` (set by the image) lets the application listen on all addresses inside
  the container while the localhost-only host-name check stays on (`ALLOW_PUBLIC_BIND` would have switched it off).
- `docs/DOCKER.md` (new guide), `README.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md` (D-69),
  `.env.example` (documents `CONTAINER`).
- `tests/unit/test_docker_setup.py` (15 tests).

## 3. Checks run
```
$ ruff / mypy        All checks passed; no issues in 129 source files
$ pytest             1233 passed, 0 failed (15 of them new, in test_docker_setup.py)
$ docker build       exit 0, image quotex-trade-engine:local, 297 MB
$ docker compose config   valid
```
Run by hand on the built image, through the real `compose.yaml` (only the host port changed, to 18781, because this
PC's own application uses 8000):
- Starts and becomes **healthy** in about 15 s; the log shows the key made, the three migrations, JSON logs, the
  setup code. Memory about **132 MB** of the 512 MB limit, CPU 0.1% idle.
- Dashboard page served (200 `text/html`); a request with `Host: evil.example` is refused (**403**) although the
  application listens on all addresses inside the container; the port is published to `127.0.0.1` only.
- Owner setup and login work; `POST /engine/start` without logins answers 409 with the reason (no network contact).
- Runs as **uid 10001**, not root; the root filesystem is read-only (writing `/app/x` fails); `/data` and `/tmp`
  are writable; `secret_key`, the database and the logs are mode 600/700.
- The image has no git, node, npm, gcc or uv (pip is part of the Python base image).
- A stored login is **encrypted** (no plain text found anywhere in the volume), survives stop and start, and is
  still readable afterwards (the same key was reused, not remade); the owner account survives too.
- `docker compose stop` (SIGINT) took **1.8 s**, exit code 0, with the application's own "Shutting down" and
  "shutdown" log lines (the orderly shutdown ran).
- The backup command works inside the read-only container into the volume, and `--no-secrets` leaves 0 stored
  secrets and 0 sessions in the copy (the user row is kept); `docker compose cp` copies it out.
- A `SECRET_KEY` given in the environment is used and no key file is made.

## 4. Challenges and how they were resolved
1. **The loopback-only rule vs a container.** Docker needs the application to listen on all addresses inside the
   container, which the rule refused, and the existing escape hatch (`ALLOW_PUBLIC_BIND`) would also have switched
   off the host-name protection. Resolution: a separate setting, `CONTAINER`, that lifts only the first (tested:
   a hostile `Host` is still refused). Compose publishes to `127.0.0.1` only, tested as text.
2. **The key.** There is no `.env` to hold it. By default it is made once into the volume (mode 600, never printed),
   which puts it beside the database; the guide says so and shows the safer way.
3. **Windows line endings.** A checkout with CRLF would break the `sh` script. `.gitattributes` forces LF and the
   Dockerfile strips a stray carriage return as well.
4. **Git Bash rewrote `/data/backups`** into a Windows path in my own test (a quirk of that shell, not of the
   image); the guide tells Git Bash users to prefix `MSYS_NO_PATHCONV=1`.
5. **Docker Desktop was not running** at the start; I started it (the application is installed on this PC) and
   removed only what I created (the test container, volume and a small image I pulled).

## 5. Deviations from the plan
None from the earlier proposal. The memory estimate for the Docker service on a 1 GB server (80-150 MB) is still
an estimate; it was not measured here.

## 6. Could not be verified
- A **real Mac / Apple Silicon**: the packages have ARM builds, but the image was only built for this PC's x86-64.
- A **real server**: the build on a 1 GB machine (it needs about 1.5 GB of disk and some minutes, and may need
  swap), and the real memory cost of Docker there.
- The **real logins** (Telegram, Quotex) and the real engine inside the container, as for the rest of the project.
- That `docker compose down` followed by a rebuild keeps the volume (standard Docker behaviour, not exercised).

**How to test it yourself:** `docker compose up -d --build`; open <http://127.0.0.1:8000>; get the setup code with
`docker compose logs app`; create the account; try *Settings*. Then `docker compose restart app` (your account and
stored logins stay), `docker compose down` and `up -d` again (the same), and the backup command in `docs/DOCKER.md`.
Use `docker stats` to see its memory.

## 7. Git state
Not committed (no commit was asked for). New: `Dockerfile`, `compose.yaml`, `.dockerignore`, `.gitattributes`,
`docker/entrypoint.sh`, `docs/DOCKER.md`, `docs/reports/docker.md`, `backend/tests/unit/test_docker_setup.py`;
changed: `backend/app/core/config.py`, `backend/pyproject.toml` (a lint rule for tests), `.env.example`, `README.md`,
`docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md`.
