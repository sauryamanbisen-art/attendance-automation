"""Service for timetable and calendar domain logic."""

from datetime import date, datetime, timezone
from typing import List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.subject import Subject
from app.models.timetable import TimetableSlot


class TimetableService:
    """Domain service for managing timetable and calendar logic."""

    def __init__(self, db: Session):
        self.db = db

    def is_holiday(self, target_date: date) -> bool:
        """Check if the given date is a college holiday."""
        return self.db.query(Holiday).filter(Holiday.date == target_date).first() is not None

    def get_exceptions_for_date(self, target_date: date) -> List[ClassException]:
        """Get the list of class exceptions for a specific date."""
        return self.db.query(ClassException).filter(ClassException.date == target_date).all()

    def get_classes_for_date(self, target_date: date) -> List[Subject]:
        """Get the list of subjects scheduled for a specific date.

        This takes into account:
        - Regular weekday schedule
        - Semester valid_from/valid_to dates
        - College holidays (returns empty list if holiday, unless extra classes exist)
        - Cancelled classes
        - Extra classes
        """
        holiday = self.is_holiday(target_date)
        weekday = target_date.weekday()

        # 1. Base regular schedule (if not holiday)
        regular_subjects = []
        if not holiday:
            # Fetch all slots for this weekday
            slots = self.db.query(TimetableSlot).filter(TimetableSlot.weekday == weekday).all()

            valid_slots = []
            for slot in slots:
                if slot.valid_from and slot.valid_from > target_date:
                    continue
                if slot.valid_to and slot.valid_to < target_date:
                    continue
                valid_slots.append(slot)

            regular_subjects = [slot.subject for slot in valid_slots]

        # 2. Apply exceptions (cancellations and extra classes)
        exceptions = self.db.query(ClassException).filter(ClassException.date == target_date).all()

        cancelled_subject_ids = {
            exc.subject_id for exc in exceptions if exc.exception_type == ExceptionType.CANCELLED
        }

        extra_subjects = [
            exc.subject for exc in exceptions if exc.exception_type == ExceptionType.EXTRA
        ]

        # Final resolution: remove cancelled, add extra, deduplicate
        final_subjects_dict = {}

        for subj in regular_subjects:
            if subj.id not in cancelled_subject_ids:
                final_subjects_dict[subj.id] = subj

        for subj in extra_subjects:
            final_subjects_dict[subj.id] = subj

        return list(final_subjects_dict.values())

    def is_class_scheduled(self, subject_code: str, target_date: date) -> bool:
        """Check if a specific subject is scheduled for a given date."""
        scheduled_subjects = self.get_classes_for_date(target_date)
        return any(subj.code == subject_code for subj in scheduled_subjects)

    def get_today_schedule(self) -> List[Subject]:
        """Convenience method to get today's scheduled classes."""
        tz_name = get_settings().timezone or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        today = datetime.now(tz).date()
        return self.get_classes_for_date(today)
