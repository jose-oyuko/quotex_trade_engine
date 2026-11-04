#!/bin/sh
# Prepares the data volume, then starts what it is given (by default the application).
#
#   1. SECRET_KEY: the key that encrypts the logins stored on the dashboard. Taken from the
#      environment if given; otherwise made once and kept in the data volume (never in the image).
#   2. The database is created or brought up to date (the application refuses to start on one that
#      is behind), so an upgrade is just a new image.
#
# Nothing here ever prints a secret.
set -eu
umask 077

data="${DATA_DIR:-/data}"
mkdir -p "$data"

if [ -z "${SECRET_KEY:-}" ]; then
  keyfile="$data/secret_key"
  if [ ! -s "$keyfile" ]; then
    python -c "from app.vault.crypto import generate_key; print(generate_key())" > "$keyfile"
    echo "qte: made a new SECRET_KEY and kept it in $keyfile (the data volume)." >&2
    echo "qte: back that file up SEPARATELY from backups of the database: see docs/DOCKER.md." >&2
  fi
  SECRET_KEY="$(cat "$keyfile")"
  export SECRET_KEY
fi

python -m alembic upgrade head

exec "$@"
