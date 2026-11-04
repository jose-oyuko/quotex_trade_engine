"""A refused Quotex login says what Quotex really answered, not what is likely.

The library only says "Login failed. Unknown error" (or crashes) and keeps no trace of the page it
got. `PageCapture` records the pages while it logs in; these tests stand a stub in for the two
library methods that receive them, so nothing here touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pyquotex import config as qx_config
from pyquotex.network.login import Login

from app.quotex.base import LoginRequest
from app.quotex.errors import QuotexConnectionError
from app.quotex.pyquotex_client import (
    KEEP_PAGES,
    PageCapture,
    PyQuotexClient,
    explain_connect_error,
    page_report,
)
from app.quotex.pyquotex_login import PyQuotexLogin

EMAIL = "me@example.com"
PASSWORD = "my-secret-password"

CHALLENGE = (
    "<html><head><title>Just a moment...</title><script>var secret='x';</script></head>"
    "<body><h1>Checking your browser before accessing quotex.com</h1>"
    '<div id="cf-chl-widget">please wait</div>'
    f"<!-- {EMAIL} {PASSWORD} --></body></html>"
)
PLAIN = (
    "<html><head><title>Quotex | Sign in</title></head><body><main class='auth__body'>"
    "<p>Something went wrong, please try again later</p></main></body></html>"
)


def response(
    html: str, status: int = 200, url: str = "https://quotex.com/en/sign-in/?utm=1"
) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, url=url, text=html, cookies={})


# --- reading a page ----------------------------------------------------------------------------


def test_a_page_report_has_the_status_the_address_without_its_query_the_title_and_the_words() -> (
    None
):
    report = page_report("the sign-in page", response(CHALLENGE, 403), (EMAIL, PASSWORD))
    assert report is not None
    assert report.status == 403 and report.url == "https://quotex.com/en/sign-in/"
    assert report.title == "Just a moment..."
    assert "Checking your browser" in report.text and "var secret" not in report.text  # no scripts
    assert report.looks_like == "a Cloudflare check (not Quotex's own page)"


def test_the_owners_email_and_password_never_stay_in_a_report() -> None:
    report = page_report("the login form's answer", response(CHALLENGE), (EMAIL, PASSWORD))
    assert report is not None
    for secret in (EMAIL, PASSWORD):
        assert secret not in report.html and secret not in report.text


def test_a_plain_error_page_is_not_called_cloudflare_and_a_captcha_is_named() -> None:
    plain = page_report("the login form's answer", response(PLAIN), ())
    assert plain is not None and plain.looks_like is None
    captcha = page_report(
        "the login form's answer", response("<title>x</title><div class='g-recaptcha'></div>"), ()
    )
    assert captcha is not None and captcha.looks_like == "a page that asks for a captcha"


def test_a_text_is_short_and_a_missing_title_or_body_is_not_a_crash() -> None:
    long_page = page_report("x", response("<p>" + "word " * 500 + "</p>"), ())
    assert long_page is not None and len(long_page.text) <= 300 and long_page.title is None
    odd = page_report("x", SimpleNamespace(status_code="n/a", url=None, text=None), ())
    assert odd is not None and odd.status is None
    assert page_report("x", None, ()) is None


# --- the capture itself ------------------------------------------------------------------------


@pytest.fixture
def library_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-ins for the two library methods: the capture then wraps something with no network."""
    answers: dict[str, Any] = {"sign_in": response(CHALLENGE, 403)}

    async def get_sign_page(self: Any) -> Any:
        return answers["sign_in"]

    async def success_login(self: Any) -> tuple[bool, str]:
        return False, "Login failed. Unknown error"

    monkeypatch.setattr(Login, "get_sign_page", get_sign_page)
    monkeypatch.setattr(Login, "success_login", success_login)
    return answers


async def test_the_pages_are_recorded_and_handed_on_unchanged(
    library_stubs: dict[str, Any],
) -> None:
    capture = PageCapture((EMAIL, PASSWORD))
    with capture:
        got = await Login.get_sign_page(object())  # type: ignore[call-arg, arg-type]
        outcome = await Login.success_login(SimpleNamespace(response=response(PLAIN)))  # type: ignore[arg-type]
    assert got is library_stubs["sign_in"]  # the very same object
    assert outcome == (False, "Login failed. Unknown error")
    assert [p.step for p in capture.pages] == ["the sign-in page", "the login form's answer"]
    assert [p.status for p in capture.pages] == [403, 200]


async def test_the_librarys_methods_are_put_back_even_when_something_fails(
    library_stubs: dict[str, Any],
) -> None:
    before = (Login.get_sign_page, Login.success_login)
    with pytest.raises(RuntimeError), PageCapture():
        assert (Login.get_sign_page, Login.success_login) != before  # wrapped inside the block
        raise RuntimeError("boom")
    assert (Login.get_sign_page, Login.success_login) == before


async def test_outside_the_block_nothing_is_recorded(library_stubs: dict[str, Any]) -> None:
    capture = PageCapture()
    with capture:
        pass
    await Login.get_sign_page(object())  # type: ignore[call-arg, arg-type]
    assert capture.pages == [] and capture.describe() is None


async def test_the_description_says_what_came_back(library_stubs: dict[str, Any]) -> None:
    capture = PageCapture((EMAIL, PASSWORD))
    with capture:
        await Login.get_sign_page(object())  # type: ignore[call-arg, arg-type]
    sentence = capture.describe()
    assert sentence is not None
    assert "answered the sign-in page with HTTP 403" in sentence
    assert "from https://quotex.com/en/sign-in/" in sentence
    assert 'titled "Just a moment..."' in sentence
    assert "Checking your browser" in sentence and "Cloudflare check" in sentence
    assert EMAIL not in sentence and PASSWORD not in sentence


async def test_the_page_is_saved_scrubbed_and_only_the_newest_few_are_kept(
    library_stubs: dict[str, Any], tmp_path: Path
) -> None:
    capture = PageCapture((EMAIL, PASSWORD))
    with capture:
        await Login.get_sign_page(object())  # type: ignore[call-arg, arg-type]
    folder = tmp_path / "diagnostics"
    for index in range(KEEP_PAGES + 2):
        (folder).mkdir(exist_ok=True)
        (folder / f"quotex-login-2020010{index}-000000.html").write_text("old", encoding="utf-8")
    saved = capture.save(folder)
    assert saved is not None and saved.parent == folder
    text = saved.read_text(encoding="utf-8")
    assert "Just a moment..." in text and "HTTP 403" in text
    assert EMAIL not in text and PASSWORD not in text
    assert len(list(folder.glob("quotex-login-*.html"))) == KEEP_PAGES
    assert saved.exists()  # the newest is among those kept


def test_nothing_is_saved_when_no_page_was_seen(tmp_path: Path) -> None:
    assert PageCapture().save(tmp_path / "diagnostics") is None
    assert not (tmp_path / "diagnostics").exists()


# --- through the dashboard login ---------------------------------------------------------------


class StubLibrary:
    """Stands in for `pyquotex.stable_api.Quotex`: asks the (stubbed) sign-in page, then fails."""

    mode: ClassVar[str] = "unknown"

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def set_account_mode(self, mode: str) -> None:
        pass

    async def connect(self) -> tuple[bool, str]:
        login = SimpleNamespace(response=response(PLAIN))
        await Login.get_sign_page(login)  # type: ignore[arg-type]
        if StubLibrary.mode == "crash":
            raise AttributeError("'Response' object has no attribute 'reason_phrase'")
        await Login.success_login(login)  # type: ignore[arg-type]
        return False, "Login failed. Unknown error"

    async def close(self) -> bool:
        return True


def request(tmp_path: Path) -> LoginRequest:
    async def no_pin(prompt: str) -> str:
        raise AssertionError("no PIN expected")

    return LoginRequest(
        email=EMAIL,
        password=PASSWORD,
        host="quotex.com",
        ask_pin=no_pin,
        diagnostics_dir=tmp_path / "diagnostics",
    )


async def test_an_unknown_error_is_followed_by_the_page_that_caused_it(
    library_stubs: dict[str, Any], tmp_path: Path
) -> None:
    StubLibrary.mode = "unknown"
    library_stubs["sign_in"] = response(CHALLENGE, 403)
    with pytest.raises(QuotexConnectionError) as caught:
        await PyQuotexLogin(request(tmp_path), quotex_class=StubLibrary).run()
    message = str(caught.value)
    assert "Login failed. Unknown error" in message  # what the library said is still there
    assert "answered the login form's answer with HTTP 200" in message  # and what was really sent
    assert 'titled "Quotex | Sign in"' in message
    assert "Something went wrong, please try again later" in message
    assert "was saved as" in message and "diagnostics" in message
    assert EMAIL not in message and PASSWORD not in message
    [saved] = list((tmp_path / "diagnostics").glob("quotex-login-*.html"))
    assert "Something went wrong" in saved.read_text(encoding="utf-8")


async def test_the_librarys_reason_phrase_crash_names_the_real_status_and_page(
    library_stubs: dict[str, Any], tmp_path: Path
) -> None:
    StubLibrary.mode = "crash"
    library_stubs["sign_in"] = response(CHALLENGE, 403)
    with pytest.raises(QuotexConnectionError) as caught:
        await PyQuotexLogin(request(tmp_path), quotex_class=StubLibrary).run()
    message = str(caught.value)
    assert "reason_phrase" not in message and "AttributeError" not in message
    assert "HTTP 403" in message and 'titled "Just a moment..."' in message
    assert "Cloudflare check" in message  # said because the page itself says so
    assert "not a wrong password" in message
    assert list((tmp_path / "diagnostics").glob("quotex-login-*.html"))


async def test_without_a_captured_page_the_old_explanations_are_unchanged() -> None:
    crash = AttributeError("'Response' object has no attribute 'reason_phrase'")
    assert "Cloudflare" in explain_connect_error(crash)
    assert explain_connect_error(RuntimeError("socket closed")) == "RuntimeError: socket closed"
    assert "Cloudflare" in explain_connect_error(crash, PageCapture())  # nothing was seen


async def test_a_login_that_reuses_a_token_sees_no_page_and_keeps_its_message(
    library_stubs: dict[str, Any], tmp_path: Path
) -> None:
    class TokenOnly(StubLibrary):
        async def connect(self) -> tuple[bool, str]:
            return False, "Websocket connection rejected."

    with pytest.raises(QuotexConnectionError) as caught:
        await PyQuotexLogin(request(tmp_path), quotex_class=TokenOnly).run()
    assert str(caught.value) == "Quotex did not accept the login: Websocket connection rejected."
    assert not (tmp_path / "diagnostics").exists()


# --- through the engine's connection -----------------------------------------------------------


async def test_the_engines_failed_connection_reports_the_page_too(
    library_stubs: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    StubLibrary.mode = "unknown"
    library_stubs["sign_in"] = response(CHALLENGE, 403)
    monkeypatch.setattr("app.quotex.pyquotex_client.Quotex", StubLibrary)
    saved = qx_config.base_dir
    try:
        client = PyQuotexClient(
            email=EMAIL,
            password=PASSWORD,
            host="quotex.com",
            data_dir=tmp_path / "data",
            session=json.dumps({"cookies": "c=1", "token": None, "user_agent": "t"}),
        )
        with pytest.raises(QuotexConnectionError) as caught:
            await client.connect(demo=True)
        await client.close()
    finally:
        qx_config.base_dir = saved
    message = str(caught.value)
    assert "HTTP 200" in message and "Something went wrong" in message
    assert EMAIL not in message and PASSWORD not in message
    assert list((tmp_path / "data" / "diagnostics").glob("quotex-login-*.html"))
