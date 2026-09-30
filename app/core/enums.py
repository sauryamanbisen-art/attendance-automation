"""Domain enumerations for attendance automation."""

from enum import Enum


class AttendanceStatus(str, Enum):
    """Domain representation of attendance status.

    UNKNOWN must always be treated as uncertain and fail closed.
    """

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"

    @property
    def is_actionable(self) -> bool:
        """Only an explicit ABSENT status can ever be actionable."""
        return self == AttendanceStatus.ABSENT

    @property
    def is_uncertain(self) -> bool:
        """UNKNOWN is always treated as uncertain."""
        return self == AttendanceStatus.UNKNOWN


class DecisionAction(str, Enum):
    """Action outcome determined by the Decision Engine."""

    NO_ACTION = "NO_ACTION"
    ELIGIBLE_FOR_NOTIFICATION = "ELIGIBLE_FOR_NOTIFICATION"


class DecisionReason(str, Enum):
    """Explanatory reason for the decision outcome."""

    ATTENDANCE_NOT_CONFIRMED = "ATTENDANCE_NOT_CONFIRMED"
    STATUS_PRESENT = "STATUS_PRESENT"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    UNRELIABLE_ATTENDANCE_RESULT = "UNRELIABLE_ATTENDANCE_RESULT"
    MISSING_PROFESSOR_MAPPING = "MISSING_PROFESSOR_MAPPING"
    ALREADY_NOTIFIED = "ALREADY_NOTIFIED"
    ABSENT_AND_CONFIRMED = "ABSENT_AND_CONFIRMED"
    HOLIDAY = "HOLIDAY"
    CLASS_CANCELLED = "CLASS_CANCELLED"


class NotificationStatus(str, Enum):
    """Status of a notification event."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CheckStatus(str, Enum):
    """Status of an attendance portal check run."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class AuditEventType(str, Enum):
    """Category of an audit event."""

    CONFIRMATION = "CONFIRMATION"
    ATTENDANCE_CHECK = "ATTENDANCE_CHECK"
    DECISION = "DECISION"
    NOTIFICATION = "NOTIFICATION"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    SUBJECT_MAPPING = "SUBJECT_MAPPING"
