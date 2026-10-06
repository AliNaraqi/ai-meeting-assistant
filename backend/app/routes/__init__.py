"""HTTP route exports."""

from app.routes.auth import router as auth_router
from app.routes.insights import router as insights_router
from app.routes.integrations import router as integrations_router
from app.routes.jobs import router as jobs_router
from app.routes.me import router as me_router
from app.routes.meetings import router as meetings_router
from app.routes.qa import router as qa_router
from app.routes.recordings import router as recordings_router

__all__ = [
    "auth_router",
    "insights_router",
    "integrations_router",
    "jobs_router",
    "me_router",
    "meetings_router",
    "qa_router",
    "recordings_router",
]
