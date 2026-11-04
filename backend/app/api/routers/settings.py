"""Settings the owner changes in the dashboard, and the secrets it stores (encrypted).

Secrets go in and never come out: the answers say only whether one is set and can be read.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ConfigDep, VaultDep
from app.api.schemas.settings import (
    SecretIn,
    SecretItemOut,
    SecretsOut,
    SettingItemOut,
    SettingsIn,
    SettingsOut,
)
from app.services.app_config import ConfigService
from app.vault.store import SecretStatus, VaultStatus

router = APIRouter(tags=["settings"])

APPLY_NOTE = "A saved setting is used from the next start of the application."


async def _settings_out(config: ConfigService) -> SettingsOut:
    return SettingsOut(
        items=[
            SettingItemOut(
                key=item.field.key,
                label=item.field.label,
                help=item.field.help,
                kind=item.field.kind,
                choices=list(item.field.choices),
                value=item.value,
                default_value=item.default_value,
                source=item.source,
            )
            for item in await config.items()
        ],
        apply_note=APPLY_NOTE,
    )


def _secret_out(item: SecretStatus) -> SecretItemOut:
    return SecretItemOut(
        name=item.name,
        label=item.label,
        help=item.help,
        group=item.group,
        is_set=item.set,
        readable=item.readable,
        updated_at=item.updated_at,
    )


def _secrets_out(status: VaultStatus) -> SecretsOut:
    key = status.key if status.key in ("ok", "missing", "invalid") else "invalid"
    return SecretsOut(key=key, items=[_secret_out(i) for i in status.secrets])


@router.get("/settings", response_model=SettingsOut)
async def get_settings(config: ConfigDep) -> SettingsOut:
    """The settings that can be changed here, with where each value comes from."""
    return await _settings_out(config)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsIn, config: ConfigDep) -> SettingsOut:
    """Save some settings (all or none: a bad value changes nothing). `null` clears a stored one."""
    await config.update(body.values)
    return await _settings_out(config)


@router.get("/secrets", response_model=SecretsOut)
async def get_secrets(vault: VaultDep) -> SecretsOut:
    """Which secrets are stored, and whether SECRET_KEY can read them. Never a value."""
    return _secrets_out(await vault.status())


@router.put("/secrets/{name}", response_model=SecretItemOut)
async def put_secret(name: str, body: SecretIn, vault: VaultDep) -> SecretItemOut:
    """Store a secret, encrypted, replacing the earlier one. Needs SECRET_KEY in `backend/.env`."""
    await vault.put(name, body.value)
    status = await vault.status()
    return _secret_out(next(i for i in status.secrets if i.name == name))


@router.delete("/secrets/{name}", status_code=204)
async def delete_secret(name: str, vault: VaultDep) -> Response:
    """Remove a stored secret. Fine if it was not set."""
    await vault.delete(name)
    return Response(status_code=204)
