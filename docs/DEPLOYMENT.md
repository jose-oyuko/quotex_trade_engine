# Deploying on a VPS (Linux)

> **Not verified on a real server.** This guide is written from how the application is built and tested
> on Windows and on fakes. The pieces are standard (uv, Node.js, systemd, SSH), but nobody has yet
> followed these steps on a VPS. Treat the first deployment as a test, on the demo account, and report
> anything that differs. Windows needs none of this: use `npm start`.

## The one thing to understand first

**The dashboard has a login, but it is served over plain HTTP.** The owner account (created on the first
start, see [OPERATIONS.md](OPERATIONS.md)) keeps strangers out of the dashboard, but on an open network
the password and the session cookie would travel unencrypted, and the login page would be exposed to
guessing. That is why the application refuses to listen on anything but loopback (`127.0.0.1`) unless
told otherwise. On a VPS the safe design is therefore:

```
your laptop --- SSH tunnel ---> VPS: 127.0.0.1:8000  (the application)
```

The application stays on loopback; you reach it through an encrypted SSH tunnel that only your SSH key
can open. Nothing is exposed to the internet except SSH. This is the recommended setup and needs no
change to the application's settings.

Do **not** set `HOST=0.0.0.0` and open the port. The application will refuse unless you also set
`ALLOW_PUBLIC_BIND=true`, and then the only thing between the internet and your trading account is a
password sent in clear text.

## Setup

The server needs **no Node.js**: the dashboard is built on your own computer and copied over, and
everything else runs through `uv`. That keeps the server light (a 1 GB machine is enough) and avoids
installing a Node version.

Assumed: Ubuntu 24.04, a normal user (called `quotex` below, with `sudo`), SSH key login.

**1. On the server**, as that user, not root:

```bash
sudo apt update && sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh          # installs uv into ~/.local/bin
source $HOME/.local/bin/env                               # or log out and in again
git clone <your repository URL> quotex_trade_engine       # a private repository needs a token or deploy key
cd quotex_trade_engine
uv sync --directory backend                               # Python 3.12 and every dependency
uv run --directory backend alembic upgrade head           # creates the database
cp .env.example backend/.env
chmod 600 backend/.env
nano backend/.env          # only ENVIRONMENT=production; the logins are typed on the dashboard
uv run --directory backend python -m scripts.secret_key   # adds SECRET_KEY to backend/.env (kept if present)
```

Copy `backend/.env` somewhere safe now (not next to a backup of the database): the key in it decrypts the
logins you will store.

`uv sync` fetches the Quotex library from GitHub, so the server needs `git` and internet access
(it has both). All other packages come ready-built for Linux; one small one (`pyaes`) is built on the
spot and needs no compiler.

**2. On your Windows PC**, build the dashboard and copy it over (from the repository folder; use your
server's address):

```
npm run build
scp -r frontend\dist quotex@139.162.165.238:~/quotex_trade_engine/frontend/
```

`frontend/dist` is git-ignored, so it is never in the clone. Copy it again after any change to the
dashboard. The backend finds it at `../frontend/dist` and serves it on the same port.

Use `ENVIRONMENT=production` (JSON console logs; the development-only CORS allowance for the Vite
server is off). Leave `HOST=127.0.0.1`.

**First start and the logins on a server.** Nothing is typed in a terminal any more: after the service is
running (next section) and the tunnel is open (the section after that), everything is done on the
dashboard at <http://127.0.0.1:8000>:

1. **Owner account.** The setup code is in the service's log: `journalctl -u quotex-engine | grep
   owner_setup_required`. Create the account with it. (Lost the password later? On the server:
   `uv run --directory backend python -m scripts.owner`.)
2. **Settings.** Store the Quotex email and password, log in to Quotex (the e-mailed PIN is typed there),
   enter the Telegram API id and hash and log in to Telegram (phone, code), then press **Start the engine**.
   Log in on the server itself rather than copying a login from your PC: Telegram may end a session used
   from two places, and Quotex may treat a login from a new place (the server's address) as suspicious and
   e-mail a PIN: expect it. Quotex's website may also refuse a server's address outright (Cloudflare); the
   dashboard then says so in words (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).
3. The engine, once left running, starts again by itself whenever the service restarts.

Old logins in `backend/.env` from an earlier version can be moved with `uv run --directory backend python -m
scripts.env_import` (or the notice on the Settings page). The command-line tools (`scripts.telegram_cli`,
`scripts.quotex_diagnose`) use the same stored logins and remain available over SSH.

## Running it as a service (systemd)

Create `/etc/systemd/system/quotex-engine.service` (replace `quotex` with your user name and fix the paths):

```ini
[Unit]
Description=Quotex Trade Engine
After=network-online.target
Wants=network-online.target

[Service]
User=quotex
WorkingDirectory=/home/quotex/quotex_trade_engine/backend
ExecStart=/home/quotex/quotex_trade_engine/backend/.venv/bin/python -m app
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

- `ExecStart` runs the virtual environment's Python directly, not through `uv run`: the stop signal then
  reaches the application itself, and nothing tries to re-sync packages at start-up.
- `KillSignal=SIGINT` is the same as pressing Ctrl+C: it runs the orderly shutdown (engine stops, the
  writer drains, the database closes). After the first `systemctl stop`, check the log for the `shutdown`
  line.
- `Restart=on-failure` brings it back after a crash. The restart behaves as described in
  [FAILURE_MODES.md](FAILURE_MODES.md): open trades are marked `unknown`, the kill switch and limits are
  restored. A restart does **not** mean it is safe to ignore: check the trades marked `unknown`.
- The application refuses to start on a database that is behind the code. After an upgrade run
  `uv run --directory backend alembic upgrade head` before restarting the service (`npm start` does this on
  Windows, the service does not).

## Using the dashboard from your computer

```bash
ssh -N -L 8000:127.0.0.1:8000 quotex@your.server
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

Schedule the backup command (cron or a systemd timer) and copy `backups/` off the server:

```
# crontab -e   (daily at 03:30)
30 3 * * *  mkdir -p /home/quotex/quotex_trade_engine/backups && cd /home/quotex/quotex_trade_engine && /home/quotex/.local/bin/uv run --directory backend python -m scripts.backup --no-secrets >> backups/cron.log 2>&1
```

A backup is consistent while the application runs. Without `--no-secrets` it contains the saved logins
and the encrypted stored secrets: leave them out of automated copies that leave the server, and keep one
manual copy with them if you want to avoid logging in again after a rebuild. With `--no-secrets` the
copy of the database has its stored secrets and login sessions emptied out and is compacted, so none of
it is left in the file.

**`SECRET_KEY`** (in `backend/.env`, created by `npm start` or `uv run --directory backend python -m
scripts.secret_key`) decrypts the stored secrets. Keep a copy of `.env` somewhere safe, **not next to a
backup of the database**: together they are the logins. Lose the key and the stored logins are lost
(they are typed in again); the rest of the data is unaffected. Restoring a database onto a machine with
a different key leaves the stored secrets unreadable; the Settings page says so and lets you re-enter them.

## Docker

Not provided. The application needs interactive logins and a persistent data folder, so a container
adds volume and terminal handling for no gain on a single-user setup (see decision D-53). If you want
it, a small Dockerfile is straightforward, but it would be new, untested scope.

## Checklist before real money

- [ ] Running on the **demo** account for a good while; live checks in the phase reports done.
- [ ] Reachable only through the tunnel (or an authenticated proxy): `curl http://<server ip>:8000`
      from another machine must fail.
- [ ] `backend/.env` is mode 600 and not in any backup that leaves the server.
- [ ] A copy of `backend/.env` (it holds `SECRET_KEY`) is kept somewhere safe, apart from database backups:
      without the key the stored logins cannot be read.
- [ ] Real money is allowed on the dashboard only deliberately (it asks for your password), and the engine
      always comes back on the demo account after a restart.
- [ ] Risk limits set (max stake, daily stop-loss); kill switch tested.
- [ ] A backup exists off the server and a restore has been rehearsed.
- [ ] You know where the log is and have read a day of it.
