"""API routers package."""

from fastapi import APIRouter

from app.api.audit import router as audit_router
from app.api.calendar import router as calendar_router
from app.api.checks import router as checks_router
from app.api.confirmations import router as confirmations_router
from app.api.dashboard import router as dashboard_router
from app.api.google_chat import router as google_chat_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.settings import router as settings_router
from app.api.subjects import router as subjects_router
from app.api.timetable import router as timetable_router
from app.api.notifications import router as notifications_router
from app.api.gmail import router as gmail_router

api_router = APIRouter(prefix="/api")

api_router.include_router(health_router)
api_router.include_router(confirmations_router)
api_router.include_router(subjects_router)
api_router.include_router(timetable_router)
api_router.include_router(calendar_router)
api_router.include_router(dashboard_router)
api_router.include_router(checks_router)
api_router.include_router(history_router)
api_router.include_router(audit_router)
api_router.include_router(settings_router)
api_router.include_router(google_chat_router)
api_router.include_router(notifications_router)
api_router.include_router(gmail_router)

__all__ = ["api_router"]
