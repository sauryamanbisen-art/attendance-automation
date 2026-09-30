"""Database models package."""

from app.models.attendance_check import AttendanceCheck
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.attendance_result import AttendanceResult
from app.models.audit_event import AuditEvent
from app.models.calendar import ClassException, Holiday
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.setting import Setting
from app.models.subject import Subject
from app.models.timetable import TimetableSlot

__all__ = [
    "Setting",
    "Subject",
    "ProfessorMapping",
    "AttendanceConfirmation",
    "AttendanceCheck",
    "AttendanceResult",
    "NotificationEvent",
    "AuditEvent",
    "TimetableSlot",
    "Holiday",
    "ClassException",
]
