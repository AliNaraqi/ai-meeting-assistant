"""FastAPI application entrypoint for AI Meeting Assistant."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import check_database, check_redis
from app.middleware import RequestIdMiddleware, UploadRateLimitMiddleware, install_error_handlers
from app.routes import (
    auth_router,
    insights_router,
    integrations_router,
    jobs_router,
    me_router,
    meetings_router,
    qa_router,
    recordings_router,
)
from app.services.providers import log_provider_mode

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    # Zero-dependency local mode: create SQLite tables on boot.
    if cfg.database_url.startswith("sqlite"):
        try:
            from app.database import get_engine
            from app.models import Base

            Base.metadata.create_all(bind=get_engine(cfg))
            logger.info("SQLite schema ready")
        except Exception:
            logger.exception("SQLite schema bootstrap failed")
    if cfg.seed_demo_on_startup:
        try:
            from app.scripts.seed_demo import seed_demo

            meeting_id = seed_demo(force=False, reset=False)
            logger.info("Startup demo meeting ready: %s", meeting_id)
        except Exception:
            logger.exception("Startup demo seed failed (app will still start)")
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)

app.add_middleware(UploadRateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)
install_error_handlers(app)
log_provider_mode()

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(integrations_router)
app.include_router(meetings_router)
app.include_router(recordings_router)
app.include_router(jobs_router)
app.include_router(insights_router)
app.include_router(qa_router)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/health/live")
def health_live() -> dict[str, str]:
    """Process liveness probe — no dependency checks."""
    return {"status": "ok", "version": settings.app_version}


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness probe — verifies PostgreSQL and Redis connectivity."""
    database_ok = check_database(settings)
    redis_ok = check_redis(settings)
    ready = database_ok and redis_ok
    payload = {
        "status": "ready" if ready else "not_ready",
        "version": settings.app_version,
        "database": "ok" if database_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
    }
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/api/v1/status")
def api_status() -> dict[str, object]:
    """Public ops snapshot: provider mode, queue depth, last job time."""
    from app.database import get_session_factory
    from app.services.status import build_status_payload

    db = get_session_factory(get_settings())()
    try:
        return build_status_payload(db, get_settings())
    finally:
        db.close()


@app.get("/status")
def serve_status_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "status.html")


@app.get("/")
def serve_landing() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/login")
def serve_login() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/app")
def serve_app() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.html")


@app.get("/meetings/new")
def serve_meeting_new() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "meeting-new.html")


@app.get("/meetings/{meeting_id}")
def serve_meeting_workspace(meeting_id: str) -> FileResponse:
    _ = meeting_id
    return FileResponse(FRONTEND_DIR / "meeting.html")


@app.get("/share/{token}")
def serve_share_page(token: str) -> FileResponse:
    _ = token
    return FileResponse(FRONTEND_DIR / "share.html")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
