"""The owner's account and sessions.

Rules (decisions D-59, D-60): there is one admin; the first account is made with a one-time setup
code that only appears in the application's log; passwords are hashed with scrypt; a session is a
random token whose SHA-256 is all that is stored; failed attempts are throttled; and a response
never says which part of a login was wrong.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.passwords import (
    DUMMY_HASH,
    hash_password_async,
    password_problem,
    verify_password_async,
)
from app.auth.throttle import LoginThrottle
from app.core.clock import Clock
from app.core.errors import DomainError
from app.db.models import AuthSession, User
from app.domain.enums import UserRole

log = structlog.get_logger()

SESSION_COOKIE = "qte_session"
SESSION_LIFETIME = timedelta(days=30)  # however active, a login ends after this
SESSION_IDLE_LIMIT = timedelta(days=7)  # and after this long without being used
TOUCH_EVERY = timedelta(minutes=5)  # "last seen" is written at most this often
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
# No 0/O or 1/I/L: the code is read off a screen and typed
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class AuthError(DomainError):
    """Base of the login errors; the messages are safe to show."""


class NotLoggedInError(AuthError):
    pass


class InvalidLoginError(AuthError):
    pass


class ThrottledError(AuthError):
    def __init__(self, seconds: int) -> None:
        minutes = max(1, round(seconds / 60))
        super().__init__(f"Too many failed attempts. Try again in about {minutes} minute(s).")
        self.seconds = seconds


class SetupClosedError(AuthError):
    pass


class WrongSetupCodeError(AuthError):
    pass


class InvalidAccountError(AuthError):
    """The username or password is not acceptable (the message says why)."""


@dataclass(slots=True, frozen=True)
class UserInfo:
    id: int
    username: str
    role: UserRole


@dataclass(slots=True, frozen=True)
class AuthState:
    setup_required: bool
    user: UserInfo | None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()


def _new_setup_code() -> str:
    chars = [secrets.choice(_CODE_ALPHABET) for _ in range(12)]
    return "-".join("".join(chars[i : i + 4]) for i in range(0, 12, 4))


def _check_username(username: str) -> str:
    username = username.strip()
    if not _USERNAME.match(username):
        raise InvalidAccountError(
            "The username must be 3 to 64 characters: letters, digits, dots, dashes or underscores."
        )
    return username


class AuthService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        *,
        throttle: LoginThrottle | None = None,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock
        self._throttle = throttle or LoginThrottle()
        self._setup_code: str | None = None

    # --- first run ---

    async def prepare(self) -> None:
        """At start-up: if there is no account yet, make a setup code and say it in the log."""
        async with self._sessions() as session:
            users = await session.scalar(select(func.count()).select_from(User)) or 0
        if users == 0:
            self._setup_code = _new_setup_code()
            log.warning(
                "owner_setup_required",
                setup_code=self._setup_code,
                hint="open the dashboard and create the owner account with this code",
            )
        else:
            self._setup_code = None

    @property
    def setup_required(self) -> bool:
        return self._setup_code is not None

    async def setup(
        self, *, code: str, username: str, password: str, client: str
    ) -> tuple[UserInfo, str]:
        """Create the owner and log them in. Works once: with the right code, while no account
        exists. Returns the user and the session token for the cookie."""
        if self._setup_code is None:
            raise SetupClosedError("The owner account already exists. Log in instead.")
        if (locked := self._throttle.seconds_locked("setup")) > 0:
            raise ThrottledError(locked)
        if not hmac.compare_digest(code.strip().upper().encode(), self._setup_code.encode()):
            self._throttle.failed("setup")
            log.warning("setup_code_wrong", client=client)
            raise WrongSetupCodeError(
                "That setup code is not right. Look in the application's log."
            )
        username = _check_username(username)
        if (problem := password_problem(password, username)) is not None:
            raise InvalidAccountError(problem)
        hashed = await hash_password_async(password)
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            if await session.scalar(select(func.count()).select_from(User)):
                self._setup_code = None
                raise SetupClosedError("The owner account already exists. Log in instead.")
            user = User(
                username=username,
                password_hash=hashed,
                role=UserRole.ADMIN,
                created_at=now,
                updated_at=now,
                password_changed_at=now,
            )
            session.add(user)
            await session.flush()
            info = UserInfo(user.id, user.username, user.role)
            token = self._add_session(session, info.id, now)
        self._setup_code = None
        self._throttle.succeeded("setup")
        log.info("owner_created", username=username)
        return info, token

    # --- sessions ---

    def _add_session(self, session: AsyncSession, user_id: int, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        session.add(
            AuthSession(
                token_hash=_hash_token(token),
                user_id=user_id,
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_LIFETIME,
            )
        )
        return token

    async def login(self, *, username: str, password: str, client: str) -> tuple[UserInfo, str]:
        keys = (f"user:{username.strip().lower()}", f"ip:{client}")
        for key in keys:
            if (locked := self._throttle.seconds_locked(key)) > 0:
                raise ThrottledError(locked)
        async with self._sessions() as session:
            user = await session.scalar(select(User).where(User.username == username.strip()))
        # An unknown name is checked against a dummy hash: the same work, so the same time.
        ok = await verify_password_async(password, user.password_hash if user else DUMMY_HASH)
        if user is None or not ok:
            for key in keys:
                self._throttle.failed(key)
            log.warning("login_failed", client=client)
            raise InvalidLoginError("Wrong username or password.")
        for key in keys:
            self._throttle.succeeded(key)
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            token = self._add_session(session, user.id, now)
        log.info("login", username=user.username)
        return UserInfo(user.id, user.username, user.role), token

    async def authenticate(self, token: str | None) -> UserInfo | None:
        """The user a session cookie belongs to, or None (no cookie, unknown, expired or idle)."""
        if not token:
            return None
        now = self._clock.now()
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(AuthSession, User)
                    .join(User, User.id == AuthSession.user_id)
                    .where(AuthSession.token_hash == _hash_token(token))
                )
            ).first()
            if row is None:
                return None
            auth, user = row
            if auth.expires_at <= now or now - auth.last_seen_at > SESSION_IDLE_LIMIT:
                await session.execute(
                    delete(AuthSession).where(AuthSession.token_hash == auth.token_hash)
                )
                await session.commit()
                return None
            if now - auth.last_seen_at > TOUCH_EVERY:
                auth.last_seen_at = now
                await session.commit()
            return UserInfo(user.id, user.username, user.role)

    async def state(self, token: str | None) -> AuthState:
        if self._setup_code is not None:
            async with self._sessions() as session:
                if await session.scalar(select(func.count()).select_from(User)):
                    self._setup_code = None  # the account was made by `npm run owner:reset`
        return AuthState(self.setup_required, await self.authenticate(token))

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(AuthSession).where(AuthSession.token_hash == _hash_token(token))
            )

    # --- the account ---

    async def change_password(
        self, user: UserInfo, *, current: str, new: str, keep_token: str | None
    ) -> None:
        """Change the password and end every other session (a stolen cookie stops working)."""
        key = f"password:{user.id}"
        if (locked := self._throttle.seconds_locked(key)) > 0:
            raise ThrottledError(locked)
        async with self._sessions() as session:
            row = await session.get(User, user.id)
        if row is None or not await verify_password_async(current, row.password_hash):
            self._throttle.failed(key)
            raise InvalidLoginError("The current password is not right.")
        self._throttle.succeeded(key)
        if (problem := password_problem(new, user.username)) is not None:
            raise InvalidAccountError(problem)
        hashed = await hash_password_async(new)
        now = self._clock.now()
        async with self._sessions() as session, session.begin():
            fresh = await session.get(User, user.id)
            if fresh is None:
                raise NotLoggedInError("This account no longer exists.")
            fresh.password_hash = hashed
            fresh.password_changed_at = now
            fresh.updated_at = now
            others = delete(AuthSession).where(AuthSession.user_id == user.id)
            if keep_token:
                others = others.where(AuthSession.token_hash != _hash_token(keep_token))
            await session.execute(others)
        log.info("password_changed", username=user.username)

    async def set_owner(self, *, username: str | None, password: str) -> tuple[str, bool]:
        """For the command on the machine (`npm run owner:reset`): create the account if there is
        none, otherwise replace the admin's password. Ends every session. Returns the username and
        whether it was created."""
        now = self._clock.now()
        async with self._sessions() as session:
            existing = await session.scalar(select(User).order_by(User.id).limit(1))
        name = existing.username if existing else _check_username(username or "")
        if (problem := password_problem(password, name)) is not None:
            raise InvalidAccountError(problem)
        hashed = await hash_password_async(password)
        async with self._sessions() as session, session.begin():
            if existing is None:
                session.add(
                    User(
                        username=name,
                        password_hash=hashed,
                        role=UserRole.ADMIN,
                        created_at=now,
                        updated_at=now,
                        password_changed_at=now,
                    )
                )
            else:
                row = await session.get(User, existing.id)
                if row is None:
                    raise NotLoggedInError("This account no longer exists.")
                row.password_hash = hashed
                row.password_changed_at = now
                row.updated_at = now
                await session.execute(delete(AuthSession))
        return name, existing is None
