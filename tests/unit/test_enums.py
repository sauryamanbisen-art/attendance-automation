"""Unit tests for domain enumerations."""

from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    CheckStatus,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)


def test_attendance_status_properties() -> None:
    """Test AttendanceStatus enumeration behavior and properties."""
    present = AttendanceStatus.PRESENT
    absent = AttendanceStatus.ABSENT
    unknown = AttendanceStatus.UNKNOWN

    assert present.value == "PRESENT"
    assert absent.value == "ABSENT"
    assert unknown.value == "UNKNOWN"

    # Only explicit ABSENT should be actionable
    assert not present.is_actionable
    assert absent.is_actionable
    assert not unknown.is_actionable

    # UNKNOWN must always be uncertain
    assert not present.is_uncertain
    assert not absent.is_uncertain
    assert unknown.is_uncertain


def test_decision_enums() -> None:
    """Test DecisionAction and DecisionReason enums."""
    assert DecisionAction.NO_ACTION == "NO_ACTION"
    assert DecisionAction.ELIGIBLE_FOR_NOTIFICATION == "ELIGIBLE_FOR_NOTIFICATION"

    assert DecisionReason.ATTENDANCE_NOT_CONFIRMED == "ATTENDANCE_NOT_CONFIRMED"
    assert DecisionReason.STATUS_PRESENT == "STATUS_PRESENT"
    assert DecisionReason.STATUS_UNKNOWN == "STATUS_UNKNOWN"
    assert DecisionReason.UNRELIABLE_ATTENDANCE_RESULT == "UNRELIABLE_ATTENDANCE_RESULT"
    assert DecisionReason.MISSING_PROFESSOR_MAPPING == "MISSING_PROFESSOR_MAPPING"
    assert DecisionReason.ALREADY_NOTIFIED == "ALREADY_NOTIFIED"
    assert DecisionReason.ABSENT_AND_CONFIRMED == "ABSENT_AND_CONFIRMED"


def test_operational_enums() -> None:
    """Test NotificationStatus, CheckStatus, and AuditEventType enums."""
    assert set(NotificationStatus) == {
        NotificationStatus.PENDING,
        NotificationStatus.SENT,
        NotificationStatus.FAILED,
        NotificationStatus.SKIPPED,
    }

    assert set(CheckStatus) == {
        CheckStatus.SUCCESS,
        CheckStatus.FAILED,
        CheckStatus.PARTIAL,
    }

    assert AuditEventType.CONFIRMATION == "CONFIRMATION"
    assert AuditEventType.ATTENDANCE_CHECK == "ATTENDANCE_CHECK"
    assert AuditEventType.DECISION == "DECISION"
