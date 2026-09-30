"""API endpoints for dashboard metrics and aggregations."""

from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import DashboardResponse, SubjectResponse, SubjectResultItem
from app.config import get_settings
from app.database.session import get_db
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_result import AttendanceResult
from app.services.confirmation import ConfirmationService
from app.services.timetable_service import TimetableService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/today", response_model=DashboardResponse)
def get_today_dashboard(db: Session = Depends(get_db)):
    """Get aggregated dashboard data for today."""
    settings = get_settings()
    tz_name = settings.timezone or "Asia/Kolkata"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    today = datetime.now(tz).date()

    # 1. Timetable Schedule
    timetable_service = TimetableService(db)
    is_holiday = timetable_service.is_holiday(today)
    expected_classes = timetable_service.get_classes_for_date(today)
    
    expected_classes_resp = [
        SubjectResponse(
            id=s.id,
            code=s.code,
            name=s.name,
            professor_name=s.professor_mapping.professor_name if s.professor_mapping else None,
            professor_email=s.professor_mapping.professor_email if s.professor_mapping else None,
            google_chat_space=s.professor_mapping.google_chat_space if s.professor_mapping else None,
        ) for s in expected_classes
    ]

    # 2. Confirmation
    confirmation_service = ConfirmationService(db)
    is_confirmed = confirmation_service.is_confirmed(today)

    # 3. Attendance Records (from the most recent check today)
    latest_check = (
        db.query(AttendanceCheck)
        .filter(AttendanceCheck.check_date == today)
        .order_by(AttendanceCheck.created_at.desc())
        .first()
    )

    attendance_records_resp: List[SubjectResultItem] = []
    if latest_check:
        results = db.query(AttendanceResult).filter(AttendanceResult.check_id == latest_check.id).all()
        for r in results:
            attendance_records_resp.append(SubjectResultItem(
                subject_code=r.subject_code,
                status=r.status,
                raw_status=r.raw_status,
                is_reliable=r.is_reliable
            ))

    return DashboardResponse(
        today=today,
        is_holiday=is_holiday,
        is_confirmed=is_confirmed,
        expected_classes=expected_classes_resp,
        attendance_records=attendance_records_resp,
    )
