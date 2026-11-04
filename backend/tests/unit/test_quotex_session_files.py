"""The Quotex library wants a session *file*; the application must never leave one behind.

These tests stand in a small class for the library's `Quotex` (the real one needs the network) that
writes and reads `session.json` exactly where the library does: under `config.base_dir`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pyquotex import config as qx_config

from app.quotex.base import LoginRequest
from app.quotex.errors import QuotexConnectionError
from app.quotex.pyquotex_client import PyQuotexClient, explain_connect_error
from app.quotex.pyquotex_login import PyQuotexLogin

EMAIL = "me@example.com"
ENTRY = {"cookies": "c=1", "token": "tok-secret-value", "user_agent": "test"}


class FakeLibrary:
    """Stands in for `pyquotex.stable_api.Quotex`."""

    instances: ClassVar[list[FakeLibrary]] = []
    behaviour: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.folder = Path(qx_config.base_dir)
        self.closed = False
        self.seen_session_at_start: dict[str, Any] | None = None
        session_file = self.folder / "session.json"
        if session_file.exists():
            self.seen_session_at_start = json.loads(session_file.read_text()).get(kwargs["email"])
        FakeLibrary.instances.append(self)

    def set_account_mode(self, mode: str) -> None:
        self.mode = mode

    async def connect(self) -> tuple[bool, str]:
        behaviour = FakeLibrary.behaviour
        if behaviour.get("raise") is not None:
            raise behaviour["raise"]
        if behaviour.get("pin"):
            code = await self.kwargs["on_otp_callback"]("Enter the PIN: ")
            assert code == behaviour["pin"]
        if not behaviour.get("ok", True):
            return False, "Login failed. Wrong password"
        qx_config.update_session(self.kwargs["email"], dict(ENTRY))  # what the library saves
        return True, "ok"

    async def close(self) -> bool:
        self.closed = True
        return True


@pytest.fixture(autouse=True)
def fresh_library() -> Any:
    FakeLibrary.instances = []
    FakeLibrary.behaviour = {}
    saved = qx_config.base_dir
    yield
    qx_config.base_dir = saved


def leftovers() -> list[Path]:
    return sorted(Path(tempfile.gettempdir()).glob("qte-quotex-*"))


def request(ask: Any = None) -> LoginRequest:
    async def no_pin(prompt: str) -> str:
        raise AssertionError("no PIN was expected")

    return LoginRequest(email=EMAIL, password="pw", host="quotex.com", ask_pin=ask or no_pin)


# --- the login made on the dashboard -----------------------------------------------------------


async def test_a_login_returns_the_session_as_text_and_leaves_no_file_behind() -> None:
    before = leftovers()
    text = await PyQuotexLogin(request(), quotex_class=FakeLibrary).run()
    assert json.loads(text) == ENTRY
    library = FakeLibrary.instances[0]
    assert library.closed and not library.folder.exists()  # the private folder is gone
    assert library.mode == "PRACTICE"  # logging in never touches the real account
    assert leftovers() == before


async def test_the_pin_is_asked_through_the_callback_with_quotexs_words() -> None:
    FakeLibrary.behaviour = {"pin": "654321"}
    asked: list[str] = []

    async def ask(prompt: str) -> str:
        asked.append(prompt)
        return "654321"

    text = await PyQuotexLogin(request(ask), quotex_class=FakeLibrary).run()
    assert asked == ["Enter the PIN: "] and json.loads(text) == ENTRY


@pytest.mark.parametrize("outcome", ["refused", "crash", "no session"])
async def test_a_failed_login_leaves_no_file_behind_either(outcome: str) -> None:
    before = leftovers()
    if outcome == "refused":
        FakeLibrary.behaviour = {"ok": False}
    elif outcome == "crash":
        FakeLibrary.behaviour = {"raise": RuntimeError("boom")}
    else:  # Quotex says yes but the library saved no token

        class NoToken(FakeLibrary):
            async def connect(self) -> tuple[bool, str]:
                return True, "ok"

        with pytest.raises(QuotexConnectionError, match="gave no session"):
            await PyQuotexLogin(request(), quotex_class=NoToken).run()
        assert leftovers() == before
        return
    with pytest.raises(QuotexConnectionError):
        await PyQuotexLogin(request(), quotex_class=FakeLibrary).run()
    assert FakeLibrary.instances[0].closed
    assert leftovers() == before


async def test_a_refusal_carries_the_reason_quotex_gave() -> None:
    FakeLibrary.behaviour = {"ok": False}
    with pytest.raises(QuotexConnectionError, match="Wrong password"):
        await PyQuotexLogin(request(), quotex_class=FakeLibrary).run()


async def test_the_librarys_crash_on_a_blocked_sign_in_page_is_explained() -> None:
    FakeLibrary.behaviour = {
        "raise": AttributeError("'Response' object has no attribute 'reason_phrase'")
    }
    with pytest.raises(QuotexConnectionError) as caught:
        await PyQuotexLogin(request(), quotex_class=FakeLibrary).run()
    message = str(caught.value)
    assert "Cloudflare" in message and "not a wrong password" in message
    assert "reason_phrase" not in message and "AttributeError" not in message


def test_other_library_errors_keep_their_own_words() -> None:
    assert explain_connect_error(RuntimeError("socket closed")) == "RuntimeError: socket closed"


# --- the engine's connection -------------------------------------------------------------------


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.quotex.pyquotex_client.Quotex", FakeLibrary)


def make_client(tmp_path: Path, session: str | None) -> PyQuotexClient:
    return PyQuotexClient(
        email=EMAIL,
        password="pw",
        host="quotex.com",
        data_dir=tmp_path / "data",
        session=session,
    )


@pytest.mark.usefixtures("patched_client")
async def test_a_stored_session_is_given_to_the_library_in_a_private_folder_and_removed(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, json.dumps(ENTRY))
    await client.connect(demo=True)
    library = FakeLibrary.instances[0]
    assert library.seen_session_at_start == ENTRY  # the library found its login where it looks
    assert library.folder != tmp_path / "data" and library.folder.exists()
    assert not (library.folder / "session.json").exists()  # off the disk once connected
    assert not (tmp_path / "data").exists()  # nothing at all went to the data folder
    await client.close()
    assert not library.folder.exists() and library.closed


@pytest.mark.usefixtures("patched_client")
async def test_the_session_file_is_removed_even_when_the_connection_fails(tmp_path: Path) -> None:
    FakeLibrary.behaviour = {"ok": False}
    client = make_client(tmp_path, json.dumps(ENTRY))
    with pytest.raises(QuotexConnectionError):
        await client.connect(demo=True)
    folder = FakeLibrary.instances[0].folder
    assert not (folder / "session.json").exists()
    await client.close()
    assert not folder.exists()


@pytest.mark.usefixtures("patched_client")
async def test_a_damaged_stored_session_is_reported_not_a_crash(tmp_path: Path) -> None:
    client = make_client(tmp_path, "{not json")
    with pytest.raises(QuotexConnectionError, match="damaged"):
        await client.connect(demo=True)
    await client.close()
    assert leftovers() == [] or all(not p.exists() or p.is_dir() for p in leftovers())


@pytest.mark.usefixtures("patched_client")
async def test_without_a_stored_session_the_data_folder_is_used_as_before(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, None)
    await client.connect(demo=True)
    library = FakeLibrary.instances[0]
    assert library.folder == tmp_path / "data"  # the command-line login's place
    await client.close()
    assert (tmp_path / "data").exists()  # and it is not deleted
