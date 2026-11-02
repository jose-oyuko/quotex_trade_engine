# Deploying on a VPS (Linux)

> **Not verified on a real server.** This guide is written from how the application is built and tested
> on Windows and on fakes. The pieces are standard (uv, Node.js, systemd, SSH), but nobody has yet
> followed these steps on a VPS. Treat the first deployment as a test, on the demo account, and report
> anything that differs. Windows needs none of this: use `npm start`.

## The one thing to understand first

**The application has no login.** Anyone who can reach its port can use the dashboard and the API,
which can place trades. That is why it refuses to listen on anything but loopback (`127.0.0.1`) unless
told otherwise. On a VPS the safe design is therefore:

```
your laptop --- SSH tunnel ---> VPS: 127.0.0.1:8000  (the application)
```

The application stays on loopback; you reach it through an encrypted SSH tunnel that only your SSH key
can open. Nothing is exposed to the internet except SSH. This is the recommended setup and needs no
change to the application's settings.

Do **not** set `HOST=0.0.0.0` and open the port. The application will refuse unless you also set
`ALLOW_PUBLIC_BIND=true`, and then anyone on the internet can trade on your account.

## Setup

On the server (Ubuntu or Debian assumed), as a normal user, not root:

```bash
# 1. tools: git, Node.js 22+ (for building the dashboard), uv
sudo apt update && sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh          # installs uv into ~/.local/bin
# install Node.js 22 or newer by your preferred method (https://nodejs.org)

# 2. the code
git clone <your repository URL> quotex_trade_engine
cd quotex_trade_engine

# 3. install, build the dashboard, create the database
npm run setup
npm run build

# 4. settings: copy and edit; keep it private
cp .env.example backend/.env
chmod 600 backend/.env
nano backend/.env          # logins, ENVIRONMENT=production, ENGINE_ENABLED=false for now
```

Python itself is installed by uv. If the server is too small to build the dashboard (Vite needs a few
hundred MB of memory), build it on your computer (`npm run build`) and copy `frontend/dist/` to the
same place on the server.

Use `ENVIRONMENT=production` (JSON console logs; the development-only CORS allowance for the Vite server is off). Leave `HOST=127.0.0.1`.

**Logins on a server.** The Telegram login and the Quotex PIN are interactive. Do them over SSH, with
the service stopped, exactly as in [OPERATIONS.md](OPERATIONS.md): `npm run telegram:login`, then
`npm run quotex:diagnose`. The saved sessions in `backend/data/` then serve the service. Quotex may
treat a login from a new place (the server's address) as suspicious and email a PIN: expect it. If you
can, log in from the server's address first on the demo account.

## Running it as a service (systemd)

Create `/etc/systemd/system/quotex-engine.service` (replace `youruser` and the paths):

```ini
[Unit]
Description=Quotex Trade Engine
After=network-online.target
Wants=network-online.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/quotex_trade_engine/backend
ExecStart=/home/youruser/.local/bin/uv run python -m app
Restart=on-failure
RestartSec=10
# Give the application time to drain its queue and write everything before it is killed.
TimeoutStopSec=30
KillSignal=SIGINT
# Reduce what a compromise could reach.
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quotex-engine
systemctl status quotex-engine
journalctl -u quotex-engine -f          # console output; the JSON log file is also in backend/data/logs/
```

Notes:

- `KillSignal=SIGINT` is the same as pressing Ctrl+C: it runs the orderly shutdown (engine stops, the
  writer drains, the database closes). Whether `uv run` hands the signal on to the application on Linux
  has not been tested: after the first `systemctl stop`, check the log for the `shutdown` line, and if it is
  missing, run the application with the virtual environment's Python directly
  (`backend/.venv/bin/python -m app`) instead of through `uv run`.
- `Restart=on-failure` brings it back after a crash. The restart behaves as described in
  [FAILURE_MODES.md](FAILURE_MODES.md): open trades are marked `unknown`, the kill switch and limits are
  restored. A restart does **not** mean it is safe to ignore: check the trades marked `unknown`.
- The application refuses to start on a database that is behind the code. After an upgrade run
  `npm run db:upgrade` before restarting the service (`npm start` does this, the service does not).

## Using the dashboard from your computer

```bash
ssh -N -L 8000:127.0.0.1:8000 youruser@your.server
```

Leave it running and open <http://127.0.0.1:8000> in your browser. It looks local because it is: the
tunnel carries it. On Windows, `ssh` is built in, or use PuTTY's tunnel settings.

## If you must put it behind a web address

Only do this with a reverse proxy (nginx, Caddy) that **requires authentication** (basic auth over
HTTPS at the least, better a VPN or an identity-aware proxy) in front of *every* path, including
`/ws`. Then:

- the application keeps `HOST=127.0.0.1`; only the proxy reaches it;
- set `ALLOW_PUBLIC_BIND=true`: this switches off the check that the request is addressed to
  `localhost`, which would otherwise refuse your public host name. The name is the setting's, not
  a statement that the port is public; the bind address is what matters;
- the proxy must pass the original `Host` header unchanged and support WebSockets (`/ws`): the
  application compares a browser's `Origin` with the `Host` and refuses unsafe requests from other
  sites.

This is more moving parts and more ways to expose a trading account. The SSH tunnel is simpler and
safer; prefer it.

## Backups on a server

Schedule `npm run backup` (cron or a systemd timer) and copy `backups/` off the server:

```
# crontab -e   (daily at 03:30; uv must be on cron's PATH)
30 3 * * *  cd /home/youruser/quotex_trade_engine && PATH=$PATH:/home/youruser/.local/bin npm run backup -- --no-secrets >> backups/cron.log 2>&1
```

A backup is consistent while the application runs. Without `--no-secrets` it contains the saved logins:
leave them out of automated copies that leave the server, and keep one manual copy with them if you
want to avoid logging in again after a rebuild.

## Docker

Not provided. The application needs interactive logins and a persistent data folder, so a container
adds volume and terminal handling for no gain on a single-user setup (see decision D-53). If you want
it, a small Dockerfile is straightforward, but it would be new, untested scope.

## Checklist before real money

- [ ] Running on the **demo** account for a good while; live checks in the phase reports done.
- [ ] Reachable only through the tunnel (or an authenticated proxy): `curl http://<server ip>:8000`
      from another machine must fail.
- [ ] `backend/.env` is mode 600 and not in any backup that leaves the server.
- [ ] Risk limits set (max stake, daily stop-loss); kill switch tested.
- [ ] A backup exists off the server and a restore has been rehearsed.
- [ ] You know where the log is and have read a day of it.
