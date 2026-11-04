"""The API's published description: committed, current, and complete."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute

from app.api import ws
from app.api.schemas.ws import SERVER_MESSAGE_MODELS
from app.core.config import Settings
from app.events import types as event_types
from app.events.types import Event
from app.main import create_app
from scripts.export_openapi import OUTPUT, render

# Every operation the API offers. Adding or removing one must be a deliberate change here (and in
# the API tests and docs/API.md), not something that slips in.
EXPECTED_OPERATIONS = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/auth/state"),
    ("POST", "/api/v1/auth/setup"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/password"),
    ("GET", "/api/v1/status"),
    ("GET", "/api/v1/telegram/chats"),
    ("GET", "/api/v1/telegram/login"),
    ("POST", "/api/v1/telegram/login/start"),
    ("POST", "/api/v1/telegram/login/resend"),
    ("POST", "/api/v1/telegram/login/code"),
    ("POST", "/api/v1/telegram/login/password"),
    ("POST", "/api/v1/telegram/login/cancel"),
    ("POST", "/api/v1/telegram/logout"),
    ("GET", "/api/v1/engine"),
    ("POST", "/api/v1/engine/start"),
    ("POST", "/api/v1/engine/stop"),
    ("POST", "/api/v1/engine/restart"),
    ("PUT", "/api/v1/account/real-trading"),
    ("GET", "/api/v1/settings"),
    ("PUT", "/api/v1/settings"),
    ("GET", "/api/v1/secrets"),
    ("PUT", "/api/v1/secrets/{name}"),
    ("DELETE", "/api/v1/secrets/{name}"),
    ("GET", "/api/v1/groups"),
    ("POST", "/api/v1/groups"),
    ("GET", "/api/v1/groups/{group_id}"),
    ("PUT", "/api/v1/groups/{group_id}"),
    ("DELETE", "/api/v1/groups/{group_id}"),
    ("POST", "/api/v1/groups/{group_id}/pause"),
    ("POST", "/api/v1/groups/{group_id}/resume"),
    ("GET", "/api/v1/groups/{group_id}/risk"),
    ("PUT", "/api/v1/groups/{group_id}/risk"),
    ("GET", "/api/v1/chains"),
    ("GET", "/api/v1/chains/{chain_id}"),
    ("POST", "/api/v1/chains/{chain_id}/stop-after-current"),
    ("POST", "/api/v1/chains/{chain_id}/end"),
    ("GET", "/api/v1/trades"),
    ("GET", "/api/v1/trades/{trade_id}"),
    ("GET", "/api/v1/signals"),
    ("GET", "/api/v1/signals/{signal_id}"),
    ("GET", "/api/v1/risk"),
    ("PUT", "/api/v1/risk/limits"),
    ("GET", "/api/v1/risk/events"),
    ("POST", "/api/v1/kill-switch"),
    ("DELETE", "/api/v1/kill-switch"),
    ("GET", "/api/v1/account"),
    ("PUT", "/api/v1/account"),
    ("GET", "/api/v1/reports/summary"),
    ("GET", "/api/v1/reports/breakdown"),
    ("GET", "/api/v1/reports/equity"),
    ("GET", "/api/v1/reports/depth"),
    ("GET", "/api/v1/reports/export/trades.csv"),
    ("GET", "/api/v1/reports/export/breakdown.csv"),
}


def build() -> Any:
    return create_app(Settings(_env_file=None))  # type: ignore[call-arg]


def test_the_committed_openapi_document_is_current() -> None:
    """If this fails: run `npm run api:generate`, then commit docs/openapi.json and the types."""
    assert OUTPUT.read_text(encoding="utf-8") == render()


def test_the_api_offers_exactly_the_expected_operations() -> None:
    document = build().openapi()
    operations = {
        (method.upper(), path) for path, methods in document["paths"].items() for method in methods
    }
    assert operations == EXPECTED_OPERATIONS
    assert [route.path for route in ws.router.routes if isinstance(route, APIWebSocketRoute)] == [
        "/ws"
    ]


def test_every_operation_is_documented_and_every_failure_uses_the_error_body() -> None:
    document = build().openapi()
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            assert operation.get("summary"), (method, path)
            for status, response in operation["responses"].items():
                if status.startswith(("4", "5")):
                    schema = response["content"]["application/json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ErrorBody"}, (
                        method,
                        path,
                        status,
                    )
            assert "422" in operation["responses"] or ("{" not in path and method == "get"), (
                method,
                path,
            )


def test_the_websocket_protocol_is_part_of_the_document() -> None:
    schemas = build().openapi()["components"]["schemas"]
    union = schemas["ServerMessage"]
    assert union["discriminator"]["propertyName"] == "type"
    mapping = union["discriminator"]["mapping"]
    assert len(mapping) == len(SERVER_MESSAGE_MODELS)
    for message_type, ref in mapping.items():
        model = schemas[ref.rsplit("/", 1)[1]]
        assert model["properties"]["type"]["const"] == message_type
        assert {"type", "seq", "at"} <= set(model["required"] + ["type"])
    assert schemas["ClientMessage"]["$ref"] == "#/components/schemas/ResyncRequest"


def test_every_event_the_engine_publishes_has_a_websocket_message() -> None:
    """A new kind of event must be shown to the dashboards (or be deliberately left out here)."""
    mapping = set(
        build().openapi()["components"]["schemas"]["ServerMessage"]["discriminator"]["mapping"]
    )
    events = {
        cls.name
        for cls in vars(event_types).values()
        if isinstance(cls, type) and issubclass(cls, Event) and cls is not Event
    }
    sent_as_controls = {"setting.changed"}  # becomes `controls.changed`
    assert events - sent_as_controls <= mapping
    assert mapping - events == {"snapshot", "heartbeat", "controls.changed"}


@pytest.mark.parametrize("name", ["TradeOut", "ChainOut", "GroupSettingsOut", "RiskLimitsOut"])
def test_money_is_text_in_every_response(name: str) -> None:
    """Floats must never carry money to the dashboard."""
    schemas = build().openapi()["components"]["schemas"]
    text = json.dumps(schemas[name])
    assert '"type": "number"' not in text, name
