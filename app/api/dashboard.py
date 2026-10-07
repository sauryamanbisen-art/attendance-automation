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

    
    # 1. Timetable Schedule (from Google Calendar)
    timetable_service = TimetableService(db)
    is_holiday = timetable_service.is_holiday(today)
    
    error_message = None
    try:
        expected_classes = timetable_service.get_classes_for_date(today)
        expected_classes_resp = [
            SubjectResponse(
                id=c.subject.id,
                code=c.subject.code,
                name=c.subject.name,
                professor_name=c.subject.professor_mapping.professor_name if c.subject.professor_mapping else None,
                professor_email=c.subject.professor_mapping.professor_email if c.subject.professor_mapping else None,
                google_chat_space=c.subject.professor_mapping.google_chat_space if c.subject.professor_mapping else None,
            ) for c in expected_classes
        ]
    except Exception as e:
        expected_classes = []
        expected_classes_resp = []
        error_message = str(e)


    # 2. Confirmation
    confirmation_service = ConfirmationService(db)
    is_confirmed = confirmation_service.is_confirmed(today)

    # 3. Attendance Records (from the most recent check today - strictly aligned with verified schedule)
    latest_check = (
        db.query(AttendanceCheck)
        .filter(AttendanceCheck.check_date == today)
        .order_by(AttendanceCheck.created_at.desc())
        .first()
    )

    attendance_records_resp: List[SubjectResultItem] = []
    if latest_check and len(expected_classes) > 0:
        from app.models.subject import is_valid_curriculum_code
        expected_codes_set = {c.subject.code for c in expected_classes}
        results = db.query(AttendanceResult).filter(AttendanceResult.check_id == latest_check.id).all()
        for r in results:
            if not is_valid_curriculum_code(r.subject_code):
                continue
            if r.subject_code not in expected_codes_set:
                continue
            attendance_records_resp.append(SubjectResultItem(
                subject_code=r.subject_code,
                status=r.status,
                raw_status=r.raw_status,
                is_reliable=r.is_reliable
            ))

    # 4. Authoritative Academic Attendance from PWIOI Portal
    from app.services.portal_attendance_service import PortalAttendanceService
    portal_svc = PortalAttendanceService(db)
    acad = portal_svc.get_summary()
    acad_rate = acad.overall_rate if (acad and acad.sync_status == "SYNCED") else None
    acad_att = acad.attended_classes if (acad and acad.sync_status == "SYNCED") else None
    acad_tot = acad.total_classes if (acad and acad.sync_status == "SYNCED") else None
    acad_status = acad.sync_status if acad else "AWAITING_PORTAL_SYNC"

    # 5. Real Discrepancies Count (Absent records for valid curriculum subjects)
    from app.core.enums import AttendanceStatus
    from app.models.subject import Subject, is_valid_curriculum_code
    from sqlalchemy import func
    valid_subject_codes = {s.code for s in db.query(Subject).all() if is_valid_curriculum_code(s.code)}
    discrepancies_count = 0
    if valid_subject_codes:
        discrepancies_count = (
            db.query(func.count(AttendanceResult.id))
            .filter(
                AttendanceResult.status == AttendanceStatus.ABSENT,
                AttendanceResult.subject_code.in_(valid_subject_codes),
            )
            .scalar() or 0
        )

    return DashboardResponse(
        today=today,
        is_holiday=is_holiday,
        is_confirmed=is_confirmed,
        expected_classes=expected_classes_resp,
        attendance_records=attendance_records_resp,
        academic_attendance_rate=acad_rate,
        academic_attended_classes=acad_att,
        academic_total_classes=acad_tot,
        academic_sync_status=acad_status,
        discrepancies_count=discrepancies_count,
        error_message=error_message,
    )
