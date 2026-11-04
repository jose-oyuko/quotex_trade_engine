"""Who is using the dashboard: first-run setup, login, logout and the password.

These are the only routes (besides `/health`) that answer without a session. The session is a random
token in an HttpOnly, SameSite=Strict cookie; the page's JavaScript never sees it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import AuthDep, CurrentUserDep
from app.api.schemas.auth import AuthStateOut, LoginIn, PasswordChangeIn, SetupIn, UserOut
from app.auth.service import SESSION_COOKIE, SESSION_LIFETIME, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


def client_of(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",  # plain http only on the owner's own machine
        path="/",
    )


def _out(user: UserInfo) -> UserOut:
    return UserOut(username=user.username, role=user.role)


@router.get("/state", response_model=AuthStateOut)
async def get_state(request: Request, response: Response, auth: AuthDep) -> AuthStateOut:
    """Is an owner account still to be created, and is this browser logged in?"""
    response.headers["Cache-Control"] = "no-store"
    state = await auth.state(request.cookies.get(SESSION_COOKIE))
    return AuthStateOut(
        setup_required=state.setup_required,
        authenticated=state.user is not None,
        user=None if state.user is None else _out(state.user),
    )


@router.post("/setup", response_model=UserOut, status_code=201)
async def setup(body: SetupIn, request: Request, response: Response, auth: AuthDep) -> UserOut:
    """Create the owner account (once). The setup code is printed in the application's log."""
    user, token = await auth.setup(
        code=body.setup_code,
        username=body.username,
        password=body.password,
        client=client_of(request),
    )
    _set_cookie(request, response, token)
    return _out(user)


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, auth: AuthDep) -> UserOut:
    user, token = await auth.login(
        username=body.username, password=body.password, client=client_of(request)
    )
    _set_cookie(request, response, token)
    return _out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, auth: AuthDep) -> None:
    """End this browser's session. Fine to call when not logged in."""
    await auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeIn, request: Request, user: CurrentUserDep, auth: AuthDep
) -> None:
    """Change the password. Every other logged-in browser is logged out."""
    await auth.change_password(
        user,
        current=body.current_password,
        new=body.new_password,
        keep_token=request.cookies.get(SESSION_COOKIE),
    )
