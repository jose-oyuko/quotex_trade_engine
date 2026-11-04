"""The encryption of stored secrets and the handling of SECRET_KEY in `.env`."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.vault.crypto import Cipher, generate_key, parse_key
from app.vault.errors import KeyInvalidError, KeyMissingError, SecretUnreadableError
from app.vault.key import ensure_secret_key, key_in_env_file
from scripts.secret_key import create

KEY = generate_key()
OTHER_KEY = generate_key()


# --- the key ---


def test_a_generated_key_is_32_random_bytes_as_text_and_never_repeats() -> None:
    keys = {generate_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(len(parse_key(k)) == 32 for k in keys)
    assert all("=" not in k and " " not in k for k in keys)  # safe to put in a .env line


@pytest.mark.parametrize("text", [None, "", "   "])
def test_a_missing_key_is_reported_as_missing_with_the_fix(text: str | None) -> None:
    with pytest.raises(KeyMissingError, match=r"npm run key:create"):
        parse_key(text)


@pytest.mark.parametrize(
    "text",
    ["short", "not base64 at all!!", base64.urlsafe_b64encode(b"x" * 16).decode(), "a" * 200],
)
def test_a_malformed_key_is_reported_as_invalid_with_the_fix(text: str) -> None:
    with pytest.raises(KeyInvalidError, match=r"npm run key:create"):
        parse_key(text)


def test_the_cipher_says_what_the_key_is_like_without_revealing_it() -> None:
    assert Cipher(KEY).status() == "ok"
    assert Cipher(None).status() == "missing"
    assert Cipher("garbage").status() == "invalid"


# --- encrypting ---


def test_a_value_comes_back_exactly_and_is_not_in_the_stored_text() -> None:
    cipher = Cipher(KEY)
    for value in ("hunter2 and more", "pässwörd ✓", "x" * 512, " leading and trailing "):
        stored = cipher.encrypt("quotex_password", value)
        assert stored.startswith("v1.")
        assert value.strip() not in stored
        assert cipher.decrypt("quotex_password", stored) == value


def test_the_same_value_is_stored_differently_every_time() -> None:
    cipher = Cipher(KEY)
    assert cipher.encrypt("quotex_password", "same") != cipher.encrypt("quotex_password", "same")


def test_a_wrong_key_is_an_error_never_a_wrong_answer() -> None:
    stored = Cipher(KEY).encrypt("quotex_password", "secret")
    with pytest.raises(SecretUnreadableError, match="SECRET_KEY"):
        Cipher(OTHER_KEY).decrypt("quotex_password", stored)


def test_a_value_moved_to_another_name_does_not_decrypt() -> None:
    cipher = Cipher(KEY)
    stored = cipher.encrypt("quotex_password", "secret")
    with pytest.raises(SecretUnreadableError):
        cipher.decrypt("telegram_api_hash", stored)


def test_damaged_or_foreign_stored_text_is_unreadable_not_a_crash() -> None:
    cipher = Cipher(KEY)
    stored = cipher.encrypt("quotex_password", "secret")
    flipped = stored[:-3] + ("AAA" if not stored.endswith("AAA") else "BBB")
    for bad in ("", "plain text", "v2." + stored[3:], flipped, stored[:20], "v1.!!!!"):
        with pytest.raises(SecretUnreadableError):
            cipher.decrypt("quotex_password", bad)


def test_without_a_usable_key_nothing_is_encrypted_or_decrypted() -> None:
    with pytest.raises(KeyMissingError):
        Cipher(None).encrypt("quotex_password", "secret")
    with pytest.raises(KeyInvalidError):
        Cipher("garbage").decrypt("quotex_password", "v1.AAAA")


# --- SECRET_KEY in .env ---


def test_a_key_is_added_to_a_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = tmp_path / "sub" / ".env"
    assert ensure_secret_key(env) is True
    key = key_in_env_file(env.read_text(encoding="utf-8"))
    assert key is not None and len(parse_key(key)) == 32


def test_an_existing_key_is_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"HOST=127.0.0.1\nSECRET_KEY={KEY}\nPORT=8000\n", encoding="utf-8")
    assert ensure_secret_key(env) is False
    assert env.read_text(encoding="utf-8") == f"HOST=127.0.0.1\nSECRET_KEY={KEY}\nPORT=8000\n"


def test_a_key_in_the_environment_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", KEY)
    env = tmp_path / ".env"
    assert ensure_secret_key(env) is False
    assert not env.exists()


def test_other_lines_and_their_line_endings_are_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_bytes(
        b"# my notes\r\nHOST=127.0.0.1\r\n# SECRET_KEY=\r\nQUOTEX_EMAIL=me@example.com\r\n"
    )
    assert ensure_secret_key(env) is True
    raw = env.read_bytes()
    assert raw.startswith(
        b"# my notes\r\nHOST=127.0.0.1\r\n# SECRET_KEY=\r\nQUOTEX_EMAIL=me@example.com\r\n"
    )
    assert b"\n" not in raw.replace(b"\r\n", b"")  # still all Windows line endings
    assert key_in_env_file(raw.decode()) is not None


def test_a_blank_key_line_is_filled_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("HOST=127.0.0.1\nSECRET_KEY=\nPORT=8000\n", encoding="utf-8")
    assert ensure_secret_key(env) is True
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "HOST=127.0.0.1" and lines[2] == "PORT=8000"
    assert lines[1].startswith("SECRET_KEY=") and len(lines[1]) > len("SECRET_KEY=") + 20
    assert sum(1 for line in lines if line.startswith("SECRET_KEY=")) == 1


def test_a_commented_key_does_not_count_as_a_key() -> None:
    assert key_in_env_file(f"# SECRET_KEY={KEY}\n") is None
    assert key_in_env_file("SECRET_KEY=\n") is None
    assert key_in_env_file(f'SECRET_KEY="{KEY}"\n') == KEY


def test_the_command_says_what_it_did_and_never_prints_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    first = create(env)
    key = key_in_env_file(env.read_text(encoding="utf-8")) or ""
    assert "Created SECRET_KEY" in first and "Keep a copy" in first and key not in first
    second = create(env)
    assert "already set" in second and key not in second
    assert key_in_env_file(env.read_text(encoding="utf-8")) == key  # unchanged
