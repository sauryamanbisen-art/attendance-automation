"""Application settings endpoint."""

import os
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.schemas import SettingsResponse, SessionStatusResponse
from app.config import get_settings

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsResponse)
def read_settings() -> SettingsResponse:
    """Retrieve current application settings (safe metadata only)."""
    settings = get_settings()
    
    # We only return explicitly safe configuration fields
    return SettingsResponse(
        app_name=settings.app_name,
        app_env=settings.app_env,
        log_level=settings.log_level,
        timezone=settings.timezone,
        dry_run=settings.dry_run,
        portal_adapter=settings.portal_adapter,
        portal_headless=settings.portal_headless,
        portal_browser_channel=settings.portal_browser_channel or settings.pwioi_browser_channel,
        email_provider=settings.email_provider,
        notification_sender_email=settings.notification_sender_email,
        pwioi_academic_term=settings.pwioi_academic_term
    )

@router.get("/session", response_model=SessionStatusResponse)
def get_session_status() -> SessionStatusResponse:
    """Check if the portal session storage state exists and is usable."""
    settings = get_settings()
    # Adapter usually falls back to PWIOI storage state if pwioi is the adapter
    storage_state_path = settings.pwioi_storage_state if settings.portal_adapter == "pwioi" else settings.portal_storage_state
    
    exists = os.path.exists(storage_state_path)
    
    student_name = None
    student_email = None
    enrollment_id = None
    
    if exists:
        try:
            import json
            with open(storage_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for origin in data.get("origins", []):
                for item in origin.get("localStorage", []):
                    if item.get("name") == "user":
                        u = json.loads(item.get("value", "{}"))
                        student_name = u.get("name")
                        student_email = u.get("email")
                    elif item.get("name") == "userDetails":
                        ud = json.loads(item.get("value", "{}"))
                        enrollment_id = ud.get("enrollmentId")
        except Exception:
            pass

        return SessionStatusResponse(
            is_authenticated=True,
            session_file_exists=True,
            message="Authenticated session found.",
            student_name=student_name,
            student_email=student_email,
            enrollment_id=enrollment_id,
        )
    else:
        return SessionStatusResponse(
            is_authenticated=False,
            session_file_exists=False,
            message="No authenticated session found."
        )

@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def clear_session():
    """Securely clear the portal session state."""
    settings = get_settings()
    storage_state_path = settings.pwioi_storage_state if settings.portal_adapter == "pwioi" else settings.portal_storage_state
    
    if os.path.exists(storage_state_path):
        try:
            os.remove(storage_state_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to securely delete session: {str(e)}")
    
    return None

