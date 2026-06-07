"""FastAPI application: JSON + SSE API and the static dashboard.

Run it with the ``topsongs-web`` console script (or ``python -m topsongs.web``).
Listens on ``TOPSONGS_WEB_HOST``:``TOPSONGS_WEB_PORT`` (default 0.0.0.0:8080).
Set ``TOPSONGS_WEB_TOKEN`` to require a bearer token on every ``/api`` call.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .runner import RunActiveError, RunManager
from .services import (
    ConfigError,
    artist_names,
    config_view,
    get_settings,
    prune_execute,
    prune_preview,
    purge_execute,
    purge_preview,
    run_missing,
    status_payload,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="topsongs", docs_url=None, redoc_url=None, openapi_url=None)


def _state_dir() -> Path:
    try:
        return get_settings().state_dir
    except ConfigError:
        return Path(os.environ.get("STATE_DIR", "state"))


run_manager = RunManager(_state_dir())


def require_token(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Enforce TOPSONGS_WEB_TOKEN when it is set; otherwise the API is open.

    EventSource cannot set headers, so the SSE route accepts ``?token=`` too.
    """
    expected = os.environ.get("TOPSONGS_WEB_TOKEN")
    if not expected:
        return
    provided = None
    if authorization and authorization.startswith("Bearer "):
        provided = authorization[len("Bearer "):]
    elif token:
        provided = token
    if provided != expected:
        raise HTTPException(status_code=401, detail="Ungültiges oder fehlendes Token.")


def _wrap(func, *args):
    """Call a service function, turning ConfigError into a clean 400."""
    try:
        return func(*args)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #

class RunBody(BaseModel):
    dry_run: bool = False


class MissingBody(BaseModel):
    artist: str | None = None
    user: str | None = None
    all_types: bool = False
    no_cache: bool = False


class PurgeBody(BaseModel):
    prefix: str | None = None


class PruneBody(BaseModel):
    keep: list[str] = []
    rename_prefix: str = ""


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/api/auth")
def auth_info() -> dict:
    """Public: tells the frontend whether a token is required (no secret leaked)."""
    return {"token_required": bool(os.environ.get("TOPSONGS_WEB_TOKEN"))}


@app.get("/api/status", dependencies=[Depends(require_token)])
def api_status() -> dict:
    payload = status_payload()
    payload["run"] = run_manager.status()
    return payload


@app.get("/api/config", dependencies=[Depends(require_token)])
def api_config() -> dict:
    return _wrap(config_view)


@app.get("/api/artists", dependencies=[Depends(require_token)])
async def api_artists() -> dict:
    return await asyncio.to_thread(_wrap, artist_names)


@app.post("/api/run", dependencies=[Depends(require_token)])
async def api_run(body: RunBody) -> dict:
    try:
        await run_manager.start(body.dry_run)
    except RunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_manager.status()


@app.get("/api/run", dependencies=[Depends(require_token)])
def api_run_status() -> dict:
    return {**run_manager.status(), "summary": run_manager.summary()}


@app.get("/api/run/stream", dependencies=[Depends(require_token)])
async def api_run_stream() -> StreamingResponse:
    async def events():
        async for line in run_manager.subscribe():
            if line is None:
                done = {"return_code": run_manager.return_code, "summary": run_manager.summary()}
                yield f"event: done\ndata: {json.dumps(done)}\n\n"
                break
            yield f"data: {json.dumps({'line': line})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/missing", dependencies=[Depends(require_token)])
async def api_missing(body: MissingBody) -> dict:
    # Network-bound and potentially slow; run off the event loop.
    return await asyncio.to_thread(
        _wrap, run_missing, body.artist, body.user, body.all_types, body.no_cache
    )


@app.post("/api/purge/preview", dependencies=[Depends(require_token)])
async def api_purge_preview(body: PurgeBody) -> dict:
    return await asyncio.to_thread(_wrap, purge_preview, body.prefix)


@app.post("/api/purge", dependencies=[Depends(require_token)])
async def api_purge(body: PurgeBody) -> dict:
    return await asyncio.to_thread(_wrap, purge_execute, body.prefix)


@app.post("/api/prune/preview", dependencies=[Depends(require_token)])
async def api_prune_preview(body: PruneBody) -> dict:
    return await asyncio.to_thread(_wrap, prune_preview, body.keep, body.rename_prefix)


@app.post("/api/prune", dependencies=[Depends(require_token)])
async def api_prune(body: PruneBody) -> dict:
    return await asyncio.to_thread(_wrap, prune_execute, body.keep, body.rename_prefix)


# --------------------------------------------------------------------------- #
# Static dashboard (mounted last so /api wins)
# --------------------------------------------------------------------------- #

@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("TOPSONGS_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("TOPSONGS_WEB_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
