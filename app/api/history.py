"""API endpoints for attendance history."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import HistoryItem, HistoryResponse
from app.database.session import get_db
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_result import AttendanceResult
from app.models.notification_event import NotificationEvent
from app.models.subject import Subject
from app.services.timetable_service import TimetableService

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/summary")
def get_attendance_summary(db: Session = Depends(get_db)):
    """Get separated academic attendance and automation verification log statistics.
    
    Invariants:
    - Real academic attendance is retrieved from PortalAttendanceService.
    - If unextracted from portal, academic metrics remain None with 'AWAITING_PORTAL_SYNC'.
    - Automation check history is separated from academic attendance percentages.
    """
    from sqlalchemy import func
    from app.core.enums import AttendanceStatus
    from app.models.subject import VALID_CURRICULUM_CODES
    from app.services.portal_attendance_service import PortalAttendanceService

    # 1. Automation Check Execution Logs (filtered strictly to valid curriculum subjects)
    valid_results_query = db.query(AttendanceResult).filter(AttendanceResult.subject_code.in_(VALID_CURRICULUM_CODES))
    total_logs = valid_results_query.count()
    present_logs = valid_results_query.filter(AttendanceResult.status == AttendanceStatus.PRESENT).count()
    absent_logs = valid_results_query.filter(AttendanceResult.status == AttendanceStatus.ABSENT).count()
    unknown_logs = valid_results_query.filter(AttendanceResult.status == AttendanceStatus.UNKNOWN).count()
    marked_logs = present_logs + absent_logs
    check_recon_rate = round((present_logs / marked_logs * 100), 1) if marked_logs > 0 else None

    total_checks = db.query(AttendanceCheck).count()
    latest_chk = db.query(AttendanceCheck).order_by(AttendanceCheck.id.desc()).first()

    automation_logs = {
        "total_checks": total_checks,
        "total_log_records": total_logs,
        "present_logs": present_logs,
        "absent_logs": absent_logs,
        "unknown_logs": unknown_logs,
        "marked_logs": marked_logs,
        "check_reconciliation_rate": check_recon_rate,
        "flagged_events": absent_logs,
        "latest_check": {
            "id": latest_chk.id,
            "date": str(latest_chk.check_date),
            "status": latest_chk.status.value if hasattr(latest_chk.status, "value") else str(latest_chk.status),
            "checked_at": latest_chk.checked_at.isoformat() if latest_chk.checked_at else None,
        } if latest_chk else None,
    }

    # 2. Authoritative Academic Attendance from PWIOI Portal
    portal_svc = PortalAttendanceService(db)
    acad_summary = portal_svc.get_summary()

    if acad_summary and acad_summary.sync_status == "SYNCED":
        academic_attendance = {
            "overall_rate": acad_summary.overall_rate,
            "total_classes": acad_summary.total_classes,
            "attended_classes": acad_summary.attended_classes,
            "missed_classes": acad_summary.missed_classes,
            "course_count": acad_summary.course_count,
            "academic_term": acad_summary.academic_term,
            "sync_status": "SYNCED",
            "synced_at": acad_summary.synced_at.isoformat() if acad_summary.synced_at else None,
            "courses": acad_summary.get_course_stats(),
        }
    else:
        academic_attendance = {
            "overall_rate": None,
            "total_classes": None,
            "attended_classes": None,
            "missed_classes": None,
            "course_count": None,
            "academic_term": None,
            "sync_status": "AWAITING_PORTAL_SYNC",
            "synced_at": None,
            "courses": {},
        }

    # 3. Automation per-subject check history breakdown (valid curriculum only)
    subj_rows = (
        db.query(AttendanceResult.subject_code, AttendanceResult.status, func.count(AttendanceResult.id))
        .filter(AttendanceResult.subject_code.in_(VALID_CURRICULUM_CODES))
        .group_by(AttendanceResult.subject_code, AttendanceResult.status)
        .all()
    )
    subject_stats = {}
    for code, st, count in subj_rows:
        if code not in subject_stats:
            subject_stats[code] = {"present": 0, "absent": 0, "unknown": 0, "total": 0, "marked": 0, "rate": None}
        subject_stats[code]["total"] += count
        if st == AttendanceStatus.PRESENT:
            subject_stats[code]["present"] += count
            subject_stats[code]["marked"] += count
        elif st == AttendanceStatus.ABSENT:
            subject_stats[code]["absent"] += count
            subject_stats[code]["marked"] += count
        else:
            subject_stats[code]["unknown"] += count

    for code, stats in subject_stats.items():
        if stats["marked"] > 0:
            stats["rate"] = round((stats["present"] / stats["marked"]) * 100, 1)

    return {
        "total_records": total_logs,
        "present_count": present_logs,
        "absent_count": absent_logs,
        "unknown_count": unknown_logs,
        "marked_count": marked_logs,
        "attendance_rate": academic_attendance["overall_rate"],
        "discrepancies_count": absent_logs,
        "subject_stats": subject_stats,
        "academic_attendance": academic_attendance,
        "automation_logs": automation_logs,
    }


def sanitize_note(raw_notes: Optional[str]) -> Optional[str]:
    """Ensure internal debug metadata or serialized Python dicts never leak into UI.

    Invariants:
    - Never expose raw debug dicts like "{'date': ..., 'retries': ...}".
    - If marked as having notes with raw debug info, normalize to clean user-facing 'Has Noted' or 'Has notes'.
    - If clean human-readable text was provided, preserve it.
    """
    if not raw_notes or not isinstance(raw_notes, str):
        return None
    trimmed = raw_notes.strip()
    if trimmed.lower() in ("has noted", "has note", "has notes"):
        return "Has Noted" if "noted" in trimmed.lower() else "Has notes"
    if trimmed.lower().startswith("has note"):
        return "Has Noted" if "noted" in trimmed.lower() else "Has notes"
    if "{" in trimmed and "}" in trimmed:
        import ast
        try:
            dict_slice = trimmed[trimmed.index("{"):trimmed.rindex("}") + 1]
            val = ast.literal_eval(dict_slice)
            if isinstance(val, dict):
                reason = val.get("reason") or val.get("note") or val.get("message")
                if reason and isinstance(reason, str) and not reason.strip().startswith("{") and "{" not in reason:
                    return reason.strip()
        except Exception:
            pass
        return None
    if "retries" in trimmed or "retries_attempted" in trimmed or "{'date'" in trimmed or "{" in trimmed:
        return None
    return trimmed


@router.get("", response_model=HistoryResponse)
def get_attendance_history(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    subject_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get historical attendance records with calendar and notification context."""
    from app.models.subject import VALID_CURRICULUM_CODES
    
    # Base query combining results, checks, subjects - strictly filtered to valid curriculum
    query = (
        db.query(AttendanceResult, AttendanceCheck, Subject)
        .join(AttendanceCheck, AttendanceResult.check_id == AttendanceCheck.id)
        .outerjoin(Subject, AttendanceResult.subject_id == Subject.id)
        .filter(AttendanceResult.subject_code.in_(VALID_CURRICULUM_CODES))
    )

    if start_date:
        query = query.filter(AttendanceCheck.check_date >= start_date)
    
    if end_date:
        query = query.filter(AttendanceCheck.check_date <= end_date)
        
    if subject_code:
        query = query.filter(AttendanceResult.subject_code == subject_code)
        
    if status:
        try:
            from app.core.enums import AttendanceStatus
            status_enum = AttendanceStatus(status)
            query = query.filter(AttendanceResult.status == status_enum)
        except ValueError:
            pass
        
    # Get total count before pagination
    total = query.count()
    
    # Apply pagination and order by date desc, then check creation desc
    query = query.order_by(
        AttendanceCheck.check_date.desc(),
        AttendanceCheck.created_at.desc(),
        AttendanceResult.subject_code
    ).offset(offset).limit(limit)
    
    records = query.all()
    
    timetable_service = TimetableService(db)
    
    # Bulk fetch notification events for the resulting records
    # To minimize DB calls, we can fetch all notifications in the date range for these subjects
    if records:
        min_date = min(r[1].check_date for r in records)
        max_date = max(r[1].check_date for r in records)
        subject_ids = {r[2].id for r in records if r[2]}
        
        notifications = []
        if subject_ids:
            notifications = (
                db.query(NotificationEvent)
                .filter(
                    NotificationEvent.date >= min_date,
                    NotificationEvent.date <= max_date,
                    NotificationEvent.subject_id.in_(subject_ids)
                ).all()
            )
        
        notif_map = {(n.date, n.subject_id): n for n in notifications}
    else:
        notif_map = {}
        
    items = []
    
    # Cache calendar answers by date to avoid repeated evaluation
    date_cache = {}
    
    for result, check, subject in records:
        c_date = check.check_date
        
        if c_date not in date_cache:
            is_holiday = timetable_service.is_holiday(c_date)
            # Find classes for date to determine is_scheduled, is_cancelled, is_extra
            classes_for_date = timetable_service.get_classes_for_date(c_date)
            exceptions_for_date = timetable_service.get_exceptions_for_date(c_date)
            date_cache[c_date] = {
                "is_holiday": is_holiday,
                "classes": [s.subject.id for s in classes_for_date],
                "cancelled": [e.subject_id for e in exceptions_for_date if e.exception_type.value == "CANCELLED"],
                "extra": [e.subject_id for e in exceptions_for_date if e.exception_type.value == "EXTRA"]
            }
            
        cache = date_cache[c_date]
        
        is_scheduled = subject is not None and subject.id in cache["classes"]
        is_cancelled = subject is not None and subject.id in cache["cancelled"]
        is_extra = subject is not None and subject.id in cache["extra"]
        
        notif = notif_map.get((c_date, subject.id if subject else None))
        
        items.append(HistoryItem(
            check_id=check.id,
            run_id=check.run_id,
            check_date=check.check_date,
            subject_code=result.subject_code,
            subject_name=subject.name if subject else None,
            status=result.status,
            raw_status=result.raw_status,
            is_reliable=result.is_reliable,
            notes=sanitize_note(result.notes),
            is_holiday=cache["is_holiday"],
            is_cancelled=is_cancelled,
            is_extra=is_extra,
            is_scheduled=is_scheduled,
            notification_status=notif.status.value if notif else None,
            notification_dry_run=notif.dry_run if notif else None
        ))
        
    return HistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset
    )
