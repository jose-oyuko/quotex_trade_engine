"""One error format for the whole API: `{"error": {"code", "message", "details"}}`.

`code` is stable and meant for programs, `message` for the owner. Nothing here ever includes a stack
trace or the value that was rejected (it might be a secret); unexpected errors are logged and the
client only learns that something went wrong.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas.common import ErrorBody, ErrorDetail, FieldProblem
from app.auth.service import (
    InvalidAccountError,
    InvalidLoginError,
    NotLoggedInError,
    SetupClosedError,
    ThrottledError,
    WrongSetupCodeError,
)
from app.core.errors import DomainError
from app.engine.errors import (
    AccountSwitchRefusedError,
    EngineBusyError,
    EngineStartError,
    RealTradingInUseError,
    UnknownChainError,
)
from app.engine.risk import RiskConfigError
from app.quotex.errors import NotConnectedError, QuotexError, RealAccountNotAllowedError
from app.services.app_config import InvalidSettingError
from app.services.groups import (
    GroupExistsError,
    GroupInUseError,
    GroupNotFoundError,
    InvalidGroupError,
)
from app.services.telegram_login import (
    CodeStaleError,
    CodeWrongError,
    EngineRunningError,
    MustWaitError,
    NotConfiguredError,
    PasswordWrongError,
    RefusedError,
    WrongStepError,
)
from app.vault.errors import (
    InvalidSecretError,
    KeyInvalidError,
    KeyMissingError,
    SecretUnreadableError,
    UnknownSecretError,
)

log = structlog.get_logger()


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[FieldProblem] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


# The first match along an exception's class hierarchy wins, so subclasses come before bases.
DOMAIN_ERRORS: dict[type[DomainError], tuple[int, str]] = {
    GroupNotFoundError: (404, "group_not_found"),
    GroupExistsError: (409, "group_exists"),
    GroupInUseError: (409, "group_in_use"),
    InvalidGroupError: (422, "invalid_group"),
    UnknownChainError: (404, "chain_not_running"),
    AccountSwitchRefusedError: (409, "account_switch_refused"),
    EngineBusyError: (409, "engine_busy"),
    EngineStartError: (409, "engine_start_failed"),
    RealTradingInUseError: (409, "real_trading_in_use"),
    RealAccountNotAllowedError: (403, "real_trading_not_allowed"),
    RiskConfigError: (422, "invalid_risk_limits"),
    NotConnectedError: (503, "quotex_not_connected"),
    QuotexError: (502, "quotex_error"),
    NotLoggedInError: (401, "not_authenticated"),
    InvalidLoginError: (401, "invalid_login"),
    ThrottledError: (429, "too_many_attempts"),
    SetupClosedError: (409, "setup_closed"),
    WrongSetupCodeError: (403, "wrong_setup_code"),
    InvalidAccountError: (422, "invalid_account"),
    KeyMissingError: (503, "secret_key_missing"),
    KeyInvalidError: (503, "secret_key_invalid"),
    SecretUnreadableError: (409, "secret_unreadable"),
    UnknownSecretError: (404, "unknown_secret"),
    InvalidSecretError: (422, "invalid_secret"),
    InvalidSettingError: (422, "invalid_setting"),
    NotConfiguredError: (409, "telegram_not_configured"),
    EngineRunningError: (409, "engine_running"),
    WrongStepError: (409, "telegram_login_step"),
    CodeWrongError: (422, "telegram_code_invalid"),
    CodeStaleError: (409, "telegram_code_expired"),
    PasswordWrongError: (422, "telegram_password_invalid"),
    RefusedError: (422, "telegram_login_refused"),
    MustWaitError: (429, "telegram_wait"),
}

HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    429: "too_many_requests",
    501: "not_implemented",
    503: "unavailable",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[FieldProblem] | dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        for cls in type(exc).__mro__:
            if cls in DOMAIN_ERRORS:
                status, code = DOMAIN_ERRORS[cls]
                return error_response(status, code, str(exc))
        return error_response(400, "domain_error", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            FieldProblem(
                field=".".join(str(part) for part in error["loc"][1:]) or str(error["loc"][0]),
                message=str(error["msg"]).removeprefix("Value error, "),
            )
            for error in exc.errors()
        ]
        return error_response(422, "validation_error", "The request is not valid.", problems)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled_api_error", path=request.url.path, error=type(exc).__name__, exc_info=exc
        )
        return error_response(500, "internal_error", "Something went wrong; see the server log.")
