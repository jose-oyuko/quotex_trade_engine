"""Password hashing with scrypt from the standard library (decision D-60).

A stored hash looks like `scrypt$<n>$<r>$<p>$<salt>$<hash>` (base64), so the cost can be raised
later and old hashes still verify. Hashing takes 16 MB and a fraction of a second: always call the
`async` functions, which run it in a worker thread so the event loop is never held.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets

# RFC 7914's setting for interactive logins: 16 MB, about half a second on a slow PC and far less on
# a server. A costlier setting would hold a one-core server for seconds on every login.
N = 2**14
R = 8
P = 1
KEY_BYTES = 32
SALT_BYTES = 16
MAX_MEMORY = 128 * 1024 * 1024  # OpenSSL refuses scrypt above its default 32 MB otherwise

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256  # hashing is costly; a megabyte "password" must not be a way to slow us


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=MAX_MEMORY, dklen=KEY_BYTES
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    """True if `password` matches `stored`. A malformed hash never matches (and never raises)."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored: str) -> bool:
    return await asyncio.to_thread(verify_password, password, stored)


# A hash of a password nobody has, checked when the user name is unknown, so that an unknown user
# costs as much time as a wrong password and the timing does not reveal which user names exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, username: str) -> str | None:
    """Why this password is not acceptable, in words for the owner; None if it is fine."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"The password must be at most {MAX_PASSWORD_LENGTH} characters long."
    if password.strip().lower() == username.strip().lower():
        return "The password must not be the same as the username."
    if not password.strip():
        return "The password must not be only spaces."
    return None
