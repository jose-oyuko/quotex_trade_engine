"""The OpenAPI document, including the WebSocket messages.

FastAPI describes only HTTP routes. The frontend needs the WebSocket protocol typed too, so its
message models are added to `components.schemas` here, together with `ServerMessage` (the union a
client has to be ready to receive, discriminated by `type`) and `ClientMessage`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.api.schemas.ws import SERVER_MESSAGE_MODELS, ResyncRequest

REF = "#/components/schemas/{model}"


def build_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    models: list[type[BaseModel]] = [*SERVER_MESSAGE_MODELS, ResyncRequest]
    _, definitions = models_json_schema(
        [(model, "serialization") for model in models], ref_template=REF
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(definitions.get("$defs", {}))
    components["ServerMessage"] = {
        "title": "ServerMessage",
        "description": "Every message the server can send on /ws; see app/api/schemas/ws.py.",
        "oneOf": [{"$ref": REF.format(model=model.__name__)} for model in SERVER_MESSAGE_MODELS],
        "discriminator": {
            "propertyName": "type",
            "mapping": {
                _type_of(model): REF.format(model=model.__name__) for model in SERVER_MESSAGE_MODELS
            },
        },
    }
    components["ClientMessage"] = {
        "title": "ClientMessage",
        "description": "The only message a client may send on /ws.",
        "$ref": REF.format(model=ResyncRequest.__name__),
    }
    app.openapi_schema = schema
    return schema


def _type_of(model: Any) -> str:
    """The literal `type` value of a message model."""
    default: str = model.model_fields["type"].default
    return default
