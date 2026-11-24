# Deploying to a VPS with Docker, step by step

This is the exact route used on 2026-11-24 to put the application on the Linode server (Ubuntu, 1 GB of
memory) with Docker, including every problem met on the way and how it was solved. Follow it top to
bottom on a fresh server, or jump to the part you need. [DOCKER.md](DOCKER.md) explains *why* the container
is built the way it is; this file is the *how*.

Throughout:

- `SERVER_IP` is your server's address (Linode → Linodes → your server → "Public IP"). The address and
  user name of the current server are in your own notes, not in this repository.
- `quotex` is the normal (non-root) user on the server. Use your own if it differs.
- **On your PC** means a PowerShell or Windows Terminal window on your Windows computer.
  **On the server** means inside the SSH session.
- Never paste a key, a password, a token or the setup code into a chat, an issue or a screenshot.

## What you end up with

```
 your PC / phone                         the VPS
 ┌───────────────┐   SSH tunnel   ┌──────────────────────────────────────────┐
 │ browser       │ ═════════════> │ 127.0.0.1:8000  ──>  Docker container    │
 │ 127.0.0.1:8001│   (encrypted)  │  (nothing else      "app": API, engine,  │
 └───────────────┘                │   can reach it)      dashboard            │
                                  │                     volume qte-data:     │
                                  │                      database, logs      │
                                  │ ~/quotex_trade_engine/.env: SECRET_KEY   │
                                  └──────────────────────────────────────────┘
```

- The application runs in one container that restarts by itself after a crash or a reboot.
- Its port is published to the server's `127.0.0.1` only: the internet cannot reach it. You reach it
  through an SSH tunnel (step 11). To reach it from any device, see
  [Reaching it from any device](#reaching-it-from-any-device) at the end.
- Your data lives in a Docker *volume* (`qte-data`) that survives rebuilds and upgrades.
- The key that encrypts your stored logins lives in a separate file, `.env`, next to `compose.yaml`.

---

## 0. Before you start (on your PC)

1. **The code you want must be on GitHub.** The server downloads it from there, not from your PC.
   In the repository folder:

   ```
   git status -sb
   ```

   If the first line says `ahead N`, those commits are only on your PC: `git push` first.

2. **An SSH key.** You already have one at `C:\Users\Administrator\.ssh\id_ed25519`. For a new server, add
   the public half (`id_ed25519.pub`) when creating the Linode (Linode → Create → "SSH Keys"), or later
   with `ssh-copy-id`-style copying into `~/.ssh/authorized_keys` on the server.

3. **A GitHub token**, because the repository is private and GitHub refuses account passwords for
   `git clone`/`git pull`. GitHub → your picture → Settings → Developer settings → Personal access
   tokens → **Fine-grained tokens** → Generate new token:
   - Repository access: *Only select repositories* → `quotex_trade_engine`
   - Permissions → Repository permissions → **Contents: Read-only**
   - Copy the token into your password manager. When git asks for a password, paste the token.

## 1. Log in to the server

On your PC:

```
ssh quotex@SERVER_IP
```

The first time, it asks whether to trust the server's fingerprint: type `yes`. With the key in place there
is no password (unless your key has a passphrase). `exit` leaves the server.

A brand-new Linode only has `root`. Make the normal user once, as root:

```
adduser quotex
usermod -aG sudo quotex
mkdir -p /home/quotex/.ssh && cp ~/.ssh/authorized_keys /home/quotex/.ssh/
chown -R quotex:quotex /home/quotex/.ssh && chmod 700 /home/quotex/.ssh
```

Then log in as `quotex` and do everything below as that user, never as root.

## 2. Use tmux, so a dropped connection cannot interrupt anything

On 2026-11-24 the SSH connection dropped (`client_loop: send disconnect: Connection reset`) in the middle
of the build, which cancelled it. Inside `tmux`, commands keep running when the connection drops.

```
sudo apt update && sudo apt install -y tmux
tmux new -s deploy
```

- Connection dropped? Log in again and type `tmux attach -t deploy`: you are back where you were.
- To leave tmux on purpose and keep it running: **Ctrl+B**, then **D**.
- Copying text with the mouse inside tmux: hold **Shift** while you drag.

## 3. Look at the server first

```
free -h                     # memory and swap
df -h /                     # free disk space
sudo ss -ltnp | grep 8000   # is anything already using port 8000?
systemctl list-units | grep -i quotex   # an older, non-Docker setup?
```

What you need: about **4 GB free disk** (2 GB swap + 1.5 GB for the image and build), and nothing on port
8000.

If an older systemd service of this application exists (from [DEPLOYMENT.md](DEPLOYMENT.md)), it holds
port 8000 and the container will not start. Stop it and stop it starting at boot:

```
sudo systemctl disable --now quotex-trade-engine
```

(Use the name `systemctl list-units` showed.)

## 4. Swap (needed on a 1 GB server)

Building the image installs the Python packages and builds the dashboard; at its peak that wants more than
1.5 GB of memory. The Linode came with 495 MB of swap, which is not enough. Add 2 GB more (it adds to the
existing swap; nothing is replaced):

```
swapon --show               # make sure /swapfile is not already in the list
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

`free -h` should now show about **2.5Gi** of swap. The `/etc/fstab` line keeps it after a reboot.

If `/swapfile` already existed, use another name (for example `/swapfile2`) in all four commands.

Once running, the application itself uses only 150-300 MB; the swap is the safety net for builds.

## 5. Install Docker

Docker's own installer for Ubuntu:

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker quotex
exit
```

`usermod` lets `quotex` use Docker without `sudo`; it only takes effect after logging in again. So log in
again (`ssh quotex@SERVER_IP`, then `tmux new -s deploy` or `tmux attach -t deploy`) and check:

```
docker version
docker compose version
```

Both should print versions without a "permission denied".

## 6. Get the code

If there is **no** `~/quotex_trade_engine` folder yet:

```
cd ~
git clone https://github.com/jose-oyuko/quotex_trade_engine.git
cd quotex_trade_engine
```

If the folder **already exists** (from an older setup):

```
cd ~/quotex_trade_engine
git pull
```

Git asks for a user name (your GitHub user name) and a password: paste the **token** from step 0, not
your GitHub password. (Nothing is shown while you paste: that is normal.)

To avoid typing the token on every `git pull` later, `git config --global credential.helper store` keeps it
in `~/.git-credentials` on the server, readable only by `quotex`. Only do this on a server only you use.

## 7. Build the image

```
docker compose build
```

The first build takes a few minutes: it downloads the base images, installs the Python packages
(`uv sync`) and builds the dashboard (`npm run build`). It ends with `Image quotex-trade-engine:local Built`.
Later builds reuse what did not change and take seconds to a couple of minutes.

Check:

```
docker images | grep quotex
```

You should see `quotex-trade-engine   local   ...   428MB` (the size will vary a little).

If the build stopped because the connection dropped, just run `docker compose build` again inside tmux:
the finished parts are cached.

## 8. The key to your stored logins

Everything you store on the dashboard's Settings page (Telegram, Quotex, Deriv logins) is encrypted with
`SECRET_KEY`. Keep the key in a file of its own, `.env` next to `compose.yaml`, instead of letting the
container keep it in the data volume beside the database. This command makes a fresh key and writes it
straight into `.env`, so it never needs to be copied or pasted:

```
cd ~/quotex_trade_engine
printf 'SECRET_KEY=%s\n' "$(docker compose run -T --rm --no-deps app python -c 'from app.vault.crypto import generate_key; print(generate_key())' 2>/dev/null | tail -n 1)" > .env && chmod 600 .env
```

Check it without showing the key:

```
wc -c .env           # about 56: a key is there
cut -c1-11 .env      # prints SECRET_KEY=
```

A very small number from `wc -c` means the key is missing: run the command again.

**Save a copy of the key off the server** (your password manager), apart from any backup of the
database. Show it once, copy it with the mouse (in Windows Terminal selecting copies, or Ctrl+Shift+C;
in tmux hold Shift while dragging), then wipe the screen:

```
cat .env
clear
```

Lose the key and the stored logins cannot be read: you type them in again on the Settings page; nothing
else is lost.

**Remove the spare key.** Any container started before `.env` existed (for example the key command itself,
the very first time) made a key of its own in the volume. With `.env` present it is never used; delete it
so only one key exists:

```
docker compose run --rm --no-deps --entrypoint rm app -f /data/secret_key
```

Never put the key in a chat or a screenshot. If that happens before you have stored any logins, simply
make a new one with the command above (nothing is encrypted with it yet). After logins are stored,
changing the key means typing those logins in again.

## 9. Start it

```
docker compose up -d
docker compose ps
```

Wait 10-20 seconds and run `docker compose ps` again. The STATUS column should say **Up ... (healthy)**.

- `(health: starting)`: still starting, wait a little.
- **`Restarting (1)`**: the application stops with an error and Docker keeps restarting it. See
  [Troubleshooting](#troubleshooting): read the log.

## 10. The setup code

The first start, with an empty database, prints a one-time code for creating the owner account:

```
docker compose logs app | grep owner_setup_required
```

Note the code (never paste it anywhere). If nothing is printed, the application is not running (step 9),
or the owner account already exists (then you log in with its password).

## 11. Open the dashboard from your PC

On your PC, in a **new** terminal window, start the tunnel and leave it running:

```
ssh -N -L 8001:127.0.0.1:8000 quotex@SERVER_IP
```

It prints nothing; that is normal. Ctrl+C closes it. Then open **<http://127.0.0.1:8001>** in your browser.

Why 8001: your PC's own copy of the application uses port 8000. The tunnel takes port 8001 on your PC and
carries it to port 8000 on the server. If your local app is not running, `-L 8000:127.0.0.1:8000` and
<http://127.0.0.1:8000> work as well.

In the browser:

1. Create the owner account with the setup code from step 10 and a strong password.
2. **Settings**: store the logins (Telegram, Quotex and/or Deriv) and log in. The server has none of the
   ones on your PC: they are typed in again here.
3. Leave the account on **demo** until you have watched it work for a while (see the checklist in
   [DEPLOYMENT.md](DEPLOYMENT.md)).
4. The server has no price history: for backtests, download prices on the Backtest page.

Quotex: Cloudflare blocked Quotex's sign-in from this server before. That depends on the server's address,
not on Docker; Deriv is not affected.

## 12. Day to day

On the server, in `~/quotex_trade_engine`:

| What | Command |
|---|---|
| Is it running and healthy? | `docker compose ps` |
| The log, live (Ctrl+C stops watching, not the app) | `docker compose logs -f app` |
| The last 50 lines of the log | `docker compose logs app --tail 50` |
| Restart (the engine you left running comes back) | `docker compose restart app` |
| Stop it (the data stays) | `docker compose down` |
| Start it again | `docker compose up -d` |
| Forgot the owner password | `docker compose exec app python -m scripts.owner` |
| How much memory it uses | `docker stats --no-stream` |

**Never run `docker compose down -v`**: the `-v` deletes the volume, that is your database.

The container restarts by itself after a crash and after the server reboots (`restart: unless-stopped`).

### Updating to new code

On your PC: commit and `git push`. Then on the server:

```
cd ~/quotex_trade_engine
git pull
docker compose up -d --build
docker compose ps
```

The database is brought up to date automatically when the container starts. If that fails, the container
stops with the error in `docker compose logs app` and nothing runs on a half-updated database.

### Backups

A backup made while it runs is consistent. It must be written into the volume (the rest of the container is
read-only), then copied out:

```
docker compose exec app python -m scripts.backup --to /data/backups --no-secrets
docker compose cp app:/data/backups ./backups-from-docker
```

Then, on your PC, copy it off the server:

```
scp -r quotex@SERVER_IP:quotex_trade_engine/backups-from-docker .
```

`--no-secrets` leaves out the stored logins. Keep the `.env` key apart from the backups. A restore is
described in [OPERATIONS.md](OPERATIONS.md) and [DOCKER.md](DOCKER.md).

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| `client_loop: send disconnect: Connection reset` | The SSH connection dropped (network). | Log in again; `tmux attach -t deploy`. If you were not in tmux, rerun the last command inside tmux; a build continues from its cache. |
| The build hangs, or the log shows `Killed` | Out of memory. | `sudo dmesg -T \| grep -i -E "out of memory\|oom" \| tail` confirms it. Add swap (step 4). |
| `permission denied ... docker.sock` | The `docker` group is not active yet. | Log out and in again after step 5. |
| `git` says authentication failed | A GitHub password was used, or the token expired or lacks access. | Use a fine-grained token with Contents: Read-only on this repository (step 0). |
| `docker compose ps` says `Restarting (1)` | The application exits with an error. | `docker compose logs app --tail 40`; the last lines say why (no secret is ever printed there). |
| `ModuleNotFoundError: No module named 'httpx'` | Happened on 2026-11-24: two packages the Deriv code needs were listed only as development tools, so the image did not contain them. Fixed in commit `8f05efd`. | `git pull` and `docker compose up -d --build`. |
| `port is already allocated` / `address already in use` | Something else on the server uses port 8000 (often the old systemd service). | Step 3: find it with `sudo ss -ltnp \| grep 8000` and stop it. |
| No setup code in the log | Not running, or the owner already exists. | Steps 9-10; or log in; or reset the password with `scripts.owner`. |
| The tunnel says `bind ... Address already in use` (on your PC) | Port 8001 on your PC is taken. | Use another, e.g. `-L 8002:127.0.0.1:8000` and <http://127.0.0.1:8002>. |
| The browser says the page cannot be reached | The tunnel window was closed, or the container is down. | Restart the tunnel; check `docker compose ps` on the server. |
| Settings says a stored login "cannot be read" | The key changed (or `.env` went missing). | Restore `.env` from your saved copy, or type the logins in again. |

## Starting again, or moving to another server

- **Fresh start on the same server, keeping nothing:** `docker compose down -v` (deletes the database),
  delete `.env`, then steps 8-11.
- **Moving to a new server, keeping the data:** make a backup *with* secrets on the old server, copy it and
  your `.env` to the new one, do steps 1-8 there but put the old `.env` in place instead of making a new
  key, restore the backup as in [DOCKER.md](DOCKER.md), then start.

## Reaching it from any device

The steps above keep the dashboard reachable only through an SSH tunnel. Making it reachable from a phone or
any computer is a choice between convenience and how much of a trading account you put on the internet. It
is described in the chat of 2026-11-24 and, once chosen and built, will be written here.
