"""Service for timetable and calendar domain logic."""

import logging
from datetime import date, datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.subject import Subject
from app.services.google_calendar_service import GoogleCalendarService, ScheduledClass

logger = logging.getLogger(__name__)


class TimetableService:
    """Domain service for managing timetable and calendar logic."""

    def __init__(self, db: Session):
        self.db = db
        self.calendar_service = GoogleCalendarService(db)

    def is_holiday(self, target_date: date) -> bool:
        """Check if the given date is a college holiday."""
        # Using Google Calendar as source of truth, a holiday might just have no classes.
        # We can still fallback to DB holidays if needed.
        return self.db.query(Holiday).filter(Holiday.date == target_date).first() is not None

    def get_exceptions_for_date(self, target_date: date) -> List[ClassException]:
        """Get the list of class exceptions for a specific date."""
        return self.db.query(ClassException).filter(ClassException.date == target_date).all()

    def get_classes_for_date(self, target_date: date) -> List[ScheduledClass]:
        """Get the list of scheduled classes for a specific date from Google Calendar."""
        try:
            # The real schedule source: Google Calendar
            scheduled_classes = self.calendar_service.get_scheduled_classes(target_date)
            # Filter out cancelled classes
            return [c for c in scheduled_classes if not c.is_cancelled]
        except Exception as e:
            logger.error(f"Failed to fetch schedule from Google Calendar: {e}")
            return []

    def is_class_scheduled(self, subject_code: str, target_date: date) -> bool:
        """Check if a specific subject is scheduled for a given date."""
        scheduled_classes = self.get_classes_for_date(target_date)
        return any(c.subject.code == subject_code for c in scheduled_classes)

    def get_today_schedule(self) -> List[ScheduledClass]:
        """Convenience method to get today's scheduled classes."""
        tz_name = get_settings().timezone or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        today = datetime.now(tz).date()
        return self.get_classes_for_date(today)

    def reschedule_class(
        self,
        subject_id: int,
        from_date: date,
        to_date: date,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None,
        description: Optional[str] = None,
    ) -> tuple[ClassException, ClassException]:
        """Reschedule a class from an original date to a new target date."""
        cancel_desc = description or f"Rescheduled to {to_date.isoformat()}"
        extra_desc = description or f"Rescheduled from {from_date.isoformat()}"

        cancelled = ClassException(
            subject_id=subject_id,
            date=from_date,
            exception_type=ExceptionType.CANCELLED,
            description=cancel_desc,
        )
        extra = ClassException(
            subject_id=subject_id,
            date=to_date,
            exception_type=ExceptionType.EXTRA,
            start_time=start_time,
            end_time=end_time,
            description=extra_desc,
        )
        self.db.add_all([cancelled, extra])
        self.db.commit()
        self.db.refresh(cancelled)
        self.db.refresh(extra)
        return (cancelled, extra)

