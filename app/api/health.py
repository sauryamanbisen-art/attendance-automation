"""Health check and status API routes."""

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def get_health() -> dict[str, str | bool]:
    """Return application health and active environment status."""
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "adapter": settings.portal_adapter,
        "dry_run": settings.dry_run,
        "timezone": settings.timezone,
    }
