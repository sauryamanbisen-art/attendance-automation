"""Unit tests for SQLAlchemy models, constraints, and relationships."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AttendanceStatus, CheckStatus, NotificationStatus
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.attendance_result import AttendanceResult
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject


def test_unique_confirmation_per_date(db_session: Session) -> None:
    """Enforce constraint: One attendance confirmation per date."""
    target_date = date(2026, 9, 25)

    c1 = AttendanceConfirmation(date=target_date)
    db_session.add(c1)
    db_session.commit()

    # Attempt inserting second confirmation for the exact same date
    c2 = AttendanceConfirmation(date=target_date)
    db_session.add(c2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_unique_notification_per_date_and_subject(db_session: Session) -> None:
    """Enforce constraint: One notification event per date + subject."""
    target_date = date(2026, 9, 25)

    subject = Subject(code="CS101", name="Python Programming")
    db_session.add(subject)
    db_session.commit()

    n1 = NotificationEvent(
        date=target_date,
        subject_id=subject.id,
        subject_code=subject.code,
        recipient_email="prof@college.edu",
        status=NotificationStatus.SENT,
    )
    db_session.add(n1)
    db_session.commit()

    # Attempt duplicate notification for identical date + subject
    n2 = NotificationEvent(
        date=target_date,
        subject_id=subject.id,
        subject_code=subject.code,
        recipient_email="prof@college.edu",
        status=NotificationStatus.PENDING,
    )
    db_session.add(n2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_subject_professor_cascade(db_session: Session) -> None:
    """Deleting a subject must cascade and delete its professor mapping."""
    subject = Subject(code="CS102", name="Data Structures")
    db_session.add(subject)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Prof. Knuth",
        professor_email="knuth@cs.edu",
    )
    db_session.add(mapping)
    db_session.commit()

    mapping_id = mapping.id
    db_session.delete(subject)
    db_session.commit()

    assert db_session.query(ProfessorMapping).filter(ProfessorMapping.id == mapping_id).first() is None


def test_attendance_check_and_results_cascade(db_session: Session) -> None:
    """Deleting an attendance check must cascade and remove all associated results."""
    check = AttendanceCheck(
        check_date=date(2026, 9, 25),
        adapter_name="fake",
        status=CheckStatus.SUCCESS,
    )
    db_session.add(check)
    db_session.flush()

    res = AttendanceResult(
        check_id=check.id,
        subject_code="CS101",
        status=AttendanceStatus.PRESENT,
    )
    db_session.add(res)
    db_session.commit()

    res_id = res.id
    db_session.delete(check)
    db_session.commit()

    assert db_session.query(AttendanceResult).filter(AttendanceResult.id == res_id).first() is None
