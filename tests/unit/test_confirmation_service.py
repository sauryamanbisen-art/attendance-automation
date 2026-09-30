"""Unit tests for ConfirmationService ('I WENT TO COLLEGE')."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.attendance_confirmation import AttendanceConfirmation
from app.services.confirmation import ConfirmationService


def test_confirmation_is_date_specific(db_session: Session) -> None:
    """Confirmation must only apply to the exact selected date and not previous or future dates."""
    service = ConfirmationService(db_session)
    today = date(2026, 9, 25)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    assert not service.is_confirmed(today)
    assert not service.is_confirmed(yesterday)
    assert not service.is_confirmed(tomorrow)

    # Confirm today
    record, created = service.confirm_attendance(today, note="Attended classes")
    assert created is True
    assert record.date == today

    # Verify strictly today is confirmed
    assert service.is_confirmed(today) is True
    assert service.is_confirmed(yesterday) is False
    assert service.is_confirmed(tomorrow) is False


def test_confirmation_is_idempotent_no_duplicates(db_session: Session) -> None:
    """Duplicate confirmations for the same date must not create duplicate records."""
    service = ConfirmationService(db_session)
    target_date = date(2026, 9, 25)

    # First confirmation
    record1, created1 = service.confirm_attendance(target_date, note="First note")
    assert created1 is True

    # Second confirmation for the same date
    record2, created2 = service.confirm_attendance(target_date, note="Second note attempt")
    assert created2 is False
    assert record1.id == record2.id
    assert record1.confirmed_at == record2.confirmed_at

    # Check database row count
    count = (
        db_session.query(AttendanceConfirmation)
        .filter(AttendanceConfirmation.date == target_date)
        .count()
    )
    assert count == 1


def test_confirmation_stores_timestamp(db_session: Session) -> None:
    """Confirmation must store an accurate UTC confirmation timestamp."""
    service = ConfirmationService(db_session)
    target_date = date(2026, 9, 25)

    before = datetime.now(timezone.utc)
    record, _ = service.confirm_attendance(target_date)
    after = datetime.now(timezone.utc)

    assert record.confirmed_at is not None
    confirmed_dt = record.confirmed_at
    if confirmed_dt.tzinfo is None:
        confirmed_dt = confirmed_dt.replace(tzinfo=timezone.utc)
    assert before <= confirmed_dt <= after


def test_confirmation_concurrent_integrity_error_handled_gracefully(db_session: Session) -> None:
    """If another transaction creates a confirmation concurrently, IntegrityError must be handled idempotently."""
    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError

    service = ConfirmationService(db_session)
    target_date = date(2026, 9, 29)

    # Pre-insert existing confirmation in DB to simulate another transaction having just committed
    existing = AttendanceConfirmation(date=target_date)
    db_session.add(existing)
    db_session.commit()

    # Simulate flush raising IntegrityError (as would happen on race condition)
    with patch.object(db_session, "flush", side_effect=IntegrityError("duplicate key", params=None, orig=Exception())):
        record, created = service.confirm_attendance(target_date)
        assert created is False
        assert record.date == target_date
        assert record.id == existing.id

