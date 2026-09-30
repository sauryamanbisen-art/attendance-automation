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


@router.get("", response_model=HistoryResponse)
def get_attendance_history(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    subject_code: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get historical attendance records with calendar and notification context."""
    
    # Base query combining results, checks, subjects
    query = (
        db.query(AttendanceResult, AttendanceCheck, Subject)
        .join(AttendanceCheck, AttendanceResult.check_id == AttendanceCheck.id)
        .outerjoin(Subject, AttendanceResult.subject_id == Subject.id)
    )

    if start_date:
        query = query.filter(AttendanceCheck.check_date >= start_date)
    
    if end_date:
        query = query.filter(AttendanceCheck.check_date <= end_date)
        
    if subject_code:
        query = query.filter(AttendanceResult.subject_code == subject_code)
        
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
                "classes": [s.id for s in classes_for_date],
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
            notes=result.notes,
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
