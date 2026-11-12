"""Trading sessions: set up, edit, start now, stop, and the history of their runs (D-71 to D-73)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import EngineDep, RunningEngineDep, SessionsDep
from app.api.schemas.common import DEFAULT_PAGE_SIZE, LimitParam, OffsetParam, Page
from app.api.schemas.sessions import SessionIn, SessionOut, SessionRunOut
from app.api.views import run_out, session_out
from app.services.sessions import InvalidSessionError, SessionValues

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _values(body: SessionIn) -> SessionValues:
    return SessionValues(
        name=body.name,
        enabled=body.enabled,
        asset=body.asset.strip(),
        duration_s=body.duration_s,
        start_time=body.start_time,
        end_time=body.end_time,
        timezone=body.timezone,
        repeat=body.repeat,
        weekdays=tuple(body.weekdays),
        pause_s=body.pause_s,
        profit_target=body.profit_target,
        loss_limit=body.loss_limit,
        max_pairs=body.max_pairs,
        strategy=body.strategy.strategy,
        base_stake=body.strategy.base_stake,
        max_steps=body.strategy.max_steps,
        multipliers=tuple(body.strategy.multipliers),
        min_payout_pct=body.strategy.min_payout_pct,
    )


@router.get("", response_model=Page[SessionOut])
async def list_sessions(
    sessions: SessionsDep,
    engine: EngineDep,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[SessionOut]:
    views = await sessions.list_all()
    return Page(
        items=[session_out(v, engine) for v in views[offset : offset + limit]],
        total=len(views),
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    body: SessionIn, response: Response, sessions: SessionsDep, engine: EngineDep
) -> SessionOut:
    """Saves the session. Two enabled sessions may not have overlapping windows."""
    view = await sessions.create(_values(body))
    response.headers["Location"] = f"/api/v1/sessions/{view.session.id}"
    return session_out(view, engine)


@router.get("/runs", response_model=Page[SessionRunOut])
async def list_runs(
    sessions: SessionsDep,
    session_id: int | None = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> Page[SessionRunOut]:
    """Runs of every session (or of one), newest first."""
    runs = await sessions.runs(session_id=session_id, limit=limit, offset=offset)
    return Page(
        items=[run_out(r) for r in runs],
        total=await sessions.count_runs(session_id=session_id),
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, sessions: SessionsDep, engine: EngineDep) -> SessionOut:
    return session_out(await sessions.get(session_id), engine)


@router.put("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: int, body: SessionIn, sessions: SessionsDep, engine: EngineDep
) -> SessionOut:
    """Refused while the session is running. Saving a 'once' session arms it again."""
    return session_out(await sessions.update(session_id, _values(body)), engine)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: int, sessions: SessionsDep) -> Response:
    """Only a session with no runs on record can be deleted; otherwise disable it."""
    await sessions.delete(session_id)
    return Response(status_code=204)


@router.post("/{session_id}/start", response_model=SessionRunOut)
async def start_session_now(
    session_id: int, sessions: SessionsDep, engine: RunningEngineDep
) -> SessionRunOut:
    """Begin a run now, for a window of the session's usual length; the first pair goes out at
    once. Refused while another run is in progress (only one session runs at a time)."""
    view = await sessions.get(session_id)
    if not view.session.enabled:
        raise InvalidSessionError("The session is switched off: enable it first.")
    return run_out(engine.scheduler.start_now(session_id))


@router.post("/{session_id}/stop", response_model=SessionRunOut)
async def stop_session(
    session_id: int, sessions: SessionsDep, engine: RunningEngineDep
) -> SessionRunOut:
    """No new pairs from now on; the chains already running finish."""
    await sessions.get(session_id)
    return run_out(engine.scheduler.stop_run(session_id))
