"""The error format, and the guards that keep other web pages (and floods) away from the API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.api.security import TokenBucket
from tests.api_support import group_body, running_api

API = "/api/v1"


# --- one error format ---


async def test_every_kind_of_failure_has_the_same_error_body(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        not_found = await rig.client.get(f"{API}/nothing-here")
        assert not_found.status_code == 404
        assert not_found.json() == {
            "error": {"code": "not_found", "message": "Not Found", "details": None}
        }
        wrong_method = await rig.client.delete(f"{API}/health")
        assert wrong_method.status_code == 405
        assert wrong_method.json()["error"]["code"] == "method_not_allowed"

        invalid = await rig.client.post(f"{API}/groups", json={"title": 5})
        assert invalid.status_code == 422
        error = invalid.json()["error"]
        assert error["code"] == "validation_error" and isinstance(error["details"], list)
        assert {"field", "message"} == set(error["details"][0])

        malformed = await rig.client.post(
            f"{API}/groups", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "validation_error"

        domain = await rig.client.get(f"{API}/groups/404")
        assert domain.json()["error"]["code"] == "group_not_found"


async def test_validation_errors_never_echo_what_was_sent(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        secret = "hunter2-super-secret"
        body = group_body(title=secret * 30)  # too long: rejected
        response = await rig.client.post(f"{API}/groups", json=body)
        assert response.status_code == 422
        assert secret not in response.text


async def test_an_unexpected_error_is_a_500_without_a_trace(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:

        async def boom() -> None:
            raise RuntimeError("internal detail: /home/owner/secret.txt")

        rig.app.add_api_route(f"{API}/boom", boom)
        response = await rig.client.get(f"{API}/boom")
        assert response.status_code == 500
        assert response.json() == {
            "error": {
                "code": "internal_error",
                "message": "Something went wrong; see the server log.",
                "details": None,
            }
        }
        assert "secret.txt" not in response.text and "Traceback" not in response.text


# --- who may talk to the API ---


async def test_only_loopback_host_names_are_served(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        for host in ("localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
            ok = await rig.client.get(f"{API}/health", headers={"Host": host})
            assert ok.status_code == 200, host
        for host in ("evil.example", "evil.example:8000", "127.0.0.1.evil.example"):
            refused = await rig.client.get(f"{API}/health", headers={"Host": host})
            assert refused.status_code == 403, host
            assert refused.json()["error"]["code"] == "host_not_allowed"


async def test_an_explicit_public_bind_turns_the_host_check_off(tmp_path: Path) -> None:
    async with running_api(tmp_path, allow_public_bind=True, host="0.0.0.0") as rig:  # noqa: S104
        response = await rig.client.get(f"{API}/health", headers={"Host": "my-vps.example"})
        assert response.status_code == 200


async def test_a_page_from_another_site_cannot_change_anything(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        await rig.create_group()
        hostile = {"Origin": "http://evil.example"}
        for response in (
            await rig.client.post(f"{API}/kill-switch", headers=hostile),
            await rig.client.delete(f"{API}/kill-switch", headers=hostile),
            await rig.client.post(f"{API}/groups/1/pause", headers=hostile),
            await rig.client.put(f"{API}/risk/limits", json={}, headers=hostile),
            await rig.client.delete(f"{API}/groups/1", headers=hostile),
            await rig.client.post(f"{API}/groups", json=group_body(), headers=hostile),
        ):
            assert response.status_code == 403, response.request.url
            assert response.json()["error"]["code"] == "origin_not_allowed"
        assert rig.fakes.engine.guard.kill_switch is False
        assert rig.fakes.engine.guard.paused_groups == frozenset()
        assert (await rig.client.get(f"{API}/groups/1")).status_code == 200  # still there


async def test_the_dashboards_own_origins_and_programs_without_an_origin_are_fine(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        for origin in ("http://127.0.0.1", "http://127.0.0.1:5173"):  # same site, dev server
            response = await rig.client.post(f"{API}/kill-switch", headers={"Origin": origin})
            assert response.status_code == 200, origin
        assert (await rig.client.post(f"{API}/kill-switch")).status_code == 200  # curl: no Origin
        # reading is not a change: the browser itself keeps another site from seeing the answer
        read = await rig.client.get(f"{API}/status", headers={"Origin": "http://evil.example"})
        assert read.status_code == 200


async def test_in_production_the_dev_server_origin_is_not_special(tmp_path: Path) -> None:
    async with running_api(tmp_path, environment="production") as rig:
        refused = await rig.client.put(
            f"{API}/risk/limits", json={}, headers={"Origin": "http://127.0.0.1:5173"}
        )
        assert refused.status_code == 403
        same_site = await rig.client.put(
            f"{API}/risk/limits", json={}, headers={"Origin": "http://127.0.0.1"}
        )
        assert same_site.status_code == 200


# --- floods and big bodies ---


async def test_a_large_body_is_refused_before_it_is_read(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:
        big = group_body(title="x" * 70_000)
        response = await rig.client.post(f"{API}/groups", json=big)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"


async def test_a_large_body_without_a_length_is_cut_off_too(tmp_path: Path) -> None:
    async with running_api(tmp_path) as rig:

        async def chunks() -> AsyncIterator[bytes]:
            for _ in range(80):
                yield b"x" * 1024

        response = await rig.client.post(
            f"{API}/groups", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"


async def test_commands_are_rate_limited_but_reading_is_not(tmp_path: Path) -> None:
    async with running_api(
        tmp_path, with_engine=True, api_command_burst=3, api_command_rate_per_s=0.001
    ) as rig:
        statuses = [(await rig.client.post(f"{API}/kill-switch")).status_code for _ in range(5)]
        assert statuses == [200, 200, 200, 429, 429]
        limited = await rig.client.post(f"{API}/kill-switch")
        assert limited.json()["error"]["code"] == "too_many_requests"
        for _ in range(20):
            assert (await rig.client.get(f"{API}/status")).status_code == 200


def test_the_token_bucket_refills_with_time() -> None:
    now = [100.0]
    bucket = TokenBucket(rate_per_s=2.0, burst=3, now=lambda: now[0])
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]
    now[0] += 0.5  # one token back
    assert bucket.take() is True and bucket.take() is False
    now[0] += 60  # never more than the burst
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


@pytest.mark.parametrize("burst", [1, 2])
def test_a_bucket_never_goes_negative(burst: int) -> None:
    bucket = TokenBucket(rate_per_s=0.0, burst=burst, now=lambda: 0.0)
    assert sum(bucket.take() for _ in range(10)) == burst
