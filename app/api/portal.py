"""API endpoints for portal academic attendance synchronization and queries."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.factory import get_portal_adapter
from app.config import get_settings
from app.database import get_db
from app.services.portal_attendance_service import PortalAttendanceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["Portal Synchronization"])


class PortalSummaryResponse(BaseModel):
    sync_status: str
    overall_rate: Optional[float] = None
    total_classes: Optional[int] = None
    attended_classes: Optional[int] = None
    missed_classes: Optional[int] = None
    course_count: Optional[int] = None
    academic_term: Optional[str] = None
    synced_at: Optional[str] = None
    courses: dict[str, Any] = {}
    message: Optional[str] = None


@router.get("/summary", response_model=PortalSummaryResponse)
def get_portal_summary(db: Session = Depends(get_db)) -> PortalSummaryResponse:
    """Retrieve authoritative academic attendance summary from the PWIOI portal.
    
    Invariants:
    - Never generates synthetic or placeholder percentages.
    - If unextracted or awaiting sync, returns None metrics with sync_status='AWAITING_PORTAL_SYNC'.
    """
    svc = PortalAttendanceService(db)
    summary = svc.get_summary()

    if not summary or summary.sync_status != "SYNCED":
        return PortalSummaryResponse(
            sync_status="AWAITING_PORTAL_SYNC",
            message="Waiting for first portal synchronization.",
        )

    return PortalSummaryResponse(
        sync_status="SYNCED",
        overall_rate=summary.overall_rate,
        total_classes=summary.total_classes,
        attended_classes=summary.attended_classes,
        missed_classes=summary.missed_classes,
        course_count=summary.course_count,
        academic_term=summary.academic_term,
        synced_at=summary.synced_at.isoformat() if summary.synced_at else None,
        courses=summary.get_course_stats(),
        message="Authoritative PWIOI portal attendance synchronized.",
    )


@router.post("/sync", response_model=PortalSummaryResponse)
def sync_portal_attendance(db: Session = Depends(get_db)) -> PortalSummaryResponse:
    """Synchronize academic attendance directly from the real PWIOI portal.
    
    Reads real overall attendance, classes attended, and course cards via Playwright.
    """
    settings = get_settings()
    svc = PortalAttendanceService(db)

    try:
        adapter = get_portal_adapter(settings)
        if not hasattr(adapter, "extract_academic_summary"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Adapter '{adapter.adapter_name}' does not support academic summary extraction.",
            )

        extracted = adapter.extract_academic_summary()

        if extracted.get("sync_status") != "SYNCED":
            # Session requires manual authentication
            return PortalSummaryResponse(
                sync_status="AWAITING_PORTAL_SYNC",
                message="PWIOI portal session requires manual Google Sign-In or is expired. Please run in headed mode to sign in.",
            )

        summary = svc.update_summary(
            overall_rate=extracted.get("overall_rate"),
            total_classes=extracted.get("total_classes"),
            attended_classes=extracted.get("attended_classes"),
            missed_classes=extracted.get("missed_classes"),
            course_count=extracted.get("course_count"),
            course_stats=extracted.get("courses"),
            sync_status="SYNCED",
        )

        return PortalSummaryResponse(
            sync_status="SYNCED",
            overall_rate=summary.overall_rate,
            total_classes=summary.total_classes,
            attended_classes=summary.attended_classes,
            missed_classes=summary.missed_classes,
            course_count=summary.course_count,
            academic_term=summary.academic_term,
            synced_at=summary.synced_at.isoformat() if summary.synced_at else None,
            courses=summary.get_course_stats(),
            message="Authoritative PWIOI portal attendance synchronized successfully.",
        )
    except Exception as exc:
        logger.error("Portal synchronization failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Portal synchronization failed: {str(exc)}",
        )
