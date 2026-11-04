# Running with Docker

An optional way to run the whole application (API, trading engine and dashboard) as one container: the
quickest on a Mac or Linux machine, and a tidy way to run it on a server. Nothing to install but Docker:
no Node.js, no `uv`, no Python. On Windows, `npm start` stays the simple way.

> **Not verified on a real Mac or server.** The image was built and run on Windows with Docker Desktop (see
> [reports/docker.md](reports/docker.md) for exactly what was checked). The Telegram and Quotex logins and the
> engine were **not** run in it against the real services. Treat the first run as a test, on the demo account.

## The 3-minute start

```
git clone <your repository URL> quotex_trade_engine
cd quotex_trade_engine
docker compose up -d --build
```

The first build takes a few minutes (it downloads the packages and builds the dashboard); every later start takes
seconds. Then:

1. Open <http://127.0.0.1:8000>. The setup code is in the log:
   `docker compose logs app | grep owner_setup_required` (on Windows PowerShell:
   `docker compose logs app | Select-String owner_setup_required`).
2. Create the owner account with it, then use the **Settings** page exactly as in
   [OPERATIONS.md](OPERATIONS.md): store the logins, log in to Telegram and Quotex, start the engine.

Nothing is typed in a terminal, which is what makes a container practical.

## What is where

| | |
|---|---|
| **The port** | published to `127.0.0.1` **only** (`127.0.0.1:8000:8000` in `compose.yaml`). Do not change it to `8000:8000`: the dashboard speaks plain HTTP. On a server, use the SSH tunnel from [DEPLOYMENT.md](DEPLOYMENT.md). |
| **Your data** | the volume `qte-data`, mounted at `/data`: the database (`quotex.db`), the logs, and by default the key to your stored logins (`secret_key`). It survives `docker compose down` and upgrades. `docker compose down -v` **deletes it**. |
| **Settings** | no `backend/.env`. Everything is on the dashboard. The image sets the few it needs (`HOST`, `CONTAINER`, `DATA_DIR`, `ENVIRONMENT`). Other settings can go in `compose.yaml` under `environment:`. |
| **The key** | see below. |

## The key to your stored logins (read this)

The logins you store on the dashboard are encrypted with `SECRET_KEY`. In a container:

- **Default:** the first start makes a key and keeps it in the volume (`/data/secret_key`, readable only by the
  application). The log says so; it never prints the key. This is the easy way, with one catch: **the key sits
  beside the database**, so a copy of the whole volume contains both.
- **Safer:** keep the key apart from the data. Make a file called `.env` next to `compose.yaml` containing one
  line, `SECRET_KEY=<a key>`, and compose passes it in. A key can be made with
  `docker compose run --rm --no-deps app python -c "from app.vault.crypto import generate_key; print(generate_key())"`.
  Keep a copy of that file somewhere safe (not in git; `.env` is git-ignored).
- **Lose the key** and the stored logins cannot be read again: you type them again, nothing else is lost.
  Changing the key later makes each stored login show "cannot be read" until re-entered.

## Day to day

```
docker compose up -d --build        start, or rebuild after pulling new code
docker compose logs -f app          the log (the setup code, problems)
docker compose ps                   is it running and healthy?
docker compose restart app          restart it (the engine you left running comes back by itself)
docker compose down                 stop and remove the container (the data volume stays)
```

The container stops the way Ctrl+C does (the engine stops, the database writer drains), and `restart:
unless-stopped` brings it back after a crash or a reboot of the machine, with the engine you left running.

**Forgot the password:** `docker compose exec app python -m scripts.owner`.

**A backup** (consistent while it runs; see OPERATIONS.md for what it holds). It must go to the volume, because
the rest of the container is read-only:

```
docker compose exec app python -m scripts.backup --to /data/backups --no-secrets
docker compose cp app:/data/backups ./backups-from-docker
```

(In Git Bash on Windows, put `MSYS_NO_PATHCONV=1` before the command: Git Bash otherwise rewrites `/data/...` into a Windows path.)

`--no-secrets` leaves out the stored logins and sessions. Without it the backup holds them (encrypted); keep it
apart from the key. A restore: copy the folder back into the volume, stop the app, run
`python -m scripts.backup --restore ... --yes` as in OPERATIONS.md.

**Moving old logins out of an old `backend/.env`:** not needed in Docker (there is no `.env`); store them on the
dashboard.

## Upgrading

```
git pull
docker compose up -d --build
```

The start script brings the database up to date before the application starts; if that fails, the container
stops with the error in `docker compose logs app` and nothing runs on a half-migrated database.

## On a 1 GB server

It fits, with less room than without Docker: the Docker service itself uses roughly 80-150 MB (an estimate, not
measured here), and the application a further 150-300 MB. `compose.yaml` limits the container to 512 MB so it
cannot starve the machine, and a swap file (see DEPLOYMENT.md) is still advisable. If memory is tight,
[DEPLOYMENT.md](DEPLOYMENT.md)'s systemd setup uses none for Docker. Steps for a server:

1. Install Docker (Docker's own instructions for Ubuntu), then `git clone` and `docker compose up -d --build`
   as above. The build needs about 1.5 GB of disk and some minutes; a 1 GB machine can build it, slowly. If it
   runs out of memory, build elsewhere and copy the image (`docker save` / `docker load`), or add swap first.
2. Reach the dashboard through the SSH tunnel (`ssh -N -L 8000:127.0.0.1:8000 you@server`), never by opening
   port 8000 in the firewall.
3. The setup code and everything after is as in the 3-minute start.

## What the container does for safety

- Runs as an ordinary user (not root), with a read-only filesystem except the data volume and a small `/tmp`,
  no extra privileges, and all Linux capabilities dropped.
- Listens on all addresses *inside* the container (`CONTAINER=true`) but still refuses any request that is not
  addressed to `localhost` / `127.0.0.1`, and Docker publishes the port to the host's `127.0.0.1` only.
- Contains no secrets: `.dockerignore` keeps `.env`, session files, databases and backups out of the image, and
  the key is made at run time.
- The image holds no Node.js, git or compiler.

## Limits

- Apple Silicon (ARM) Macs build the image natively; the packages involved have ARM builds, but this was not tried.
- Quotex's Cloudflare check depends on the address your traffic comes from, not on Docker: a container on a
  server is no more welcome to Cloudflare than the same program without one.
- The container's clock is the host's. Keep the host's time correct.
