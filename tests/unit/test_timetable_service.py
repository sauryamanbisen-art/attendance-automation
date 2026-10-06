"""Unit tests for the TimetableService and domain models."""

from datetime import date, time
import pytest
from sqlalchemy.orm import Session

from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.services.timetable_service import TimetableService


def test_regular_weekday_schedule(db_session: Session) -> None:
    """Test retrieving subjects based on a regular weekday schedule."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    subj2 = Subject(code="CS102", name="Data Structures")
    db_session.add_all([subj1, subj2])
    db_session.flush()

    # Monday (weekday 0)
    slot1 = TimetableSlot(
        subject_id=subj1.id, weekday=0, start_time=time(9, 0), end_time=time(10, 0)
    )
    # Tuesday (weekday 1)
    slot2 = TimetableSlot(
        subject_id=subj2.id, weekday=1, start_time=time(10, 0), end_time=time(11, 0)
    )
    db_session.add_all([slot1, slot2])
    db_session.commit()

    # Sep 28, 2026 is a Monday
    monday = date(2026, 9, 28)
    tuesday = date(2026, 9, 29)

    mon_classes = service.get_classes_for_date(monday)
    assert len(mon_classes) == 1
    assert mon_classes[0].subject.code == "CS101"

    tue_classes = service.get_classes_for_date(tuesday)
    assert len(tue_classes) == 1
    assert tue_classes[0].subject.code == "CS102"

    assert service.is_class_scheduled("CS101", monday) is True
    assert service.is_class_scheduled("CS102", monday) is False


def test_holiday_skips_regular_classes(db_session: Session) -> None:
    """Test that a holiday returns no regular classes."""
    service = TimetableService(db_session)
    
    subj = Subject(code="CS101", name="Intro to CS")
    db_session.add(subj)
    db_session.flush()

    monday = date(2026, 9, 28)
    slot = TimetableSlot(
        subject_id=subj.id, weekday=0, start_time=time(9, 0), end_time=time(10, 0)
    )
    holiday = Holiday(date=monday, description="National Holiday")
    db_session.add_all([slot, holiday])
    db_session.commit()

    assert service.is_holiday(monday) is True
    classes = service.get_classes_for_date(monday)
    assert len(classes) == 0
    assert service.is_class_scheduled("CS101", monday) is False


def test_cancelled_classes(db_session: Session) -> None:
    """Test that cancelled classes are excluded from the day's schedule."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    subj2 = Subject(code="CS102", name="Data Structures")
    db_session.add_all([subj1, subj2])
    db_session.flush()

    monday = date(2026, 9, 28)
    slot1 = TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9, 0), end_time=time(10, 0))
    slot2 = TimetableSlot(subject_id=subj2.id, weekday=0, start_time=time(10, 0), end_time=time(11, 0))
    
    # Cancel CS101 on this specific Monday
    cancel = ClassException(
        subject_id=subj1.id, date=monday, exception_type=ExceptionType.CANCELLED
    )
    db_session.add_all([slot1, slot2, cancel])
    db_session.commit()

    classes = service.get_classes_for_date(monday)
    assert len(classes) == 1
    assert classes[0].subject.code == "CS102"


def test_extra_classes(db_session: Session) -> None:
    """Test that extra classes are added to the day's schedule."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    db_session.add(subj1)
    db_session.flush()

    monday = date(2026, 9, 28)
    
    # Add CS101 as an extra class (even if not normally scheduled on Monday)
    extra = ClassException(
        subject_id=subj1.id, date=monday, exception_type=ExceptionType.EXTRA,
        start_time=time(14, 0), end_time=time(15, 0)
    )
    db_session.add(extra)
    db_session.commit()

    classes = service.get_classes_for_date(monday)
    assert len(classes) == 1
    assert classes[0].subject.code == "CS101"


def test_holiday_with_extra_class(db_session: Session) -> None:
    """Test that a holiday clears regular classes but allows explicitly scheduled extra classes."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    subj2 = Subject(code="CS102", name="Extra Class")
    db_session.add_all([subj1, subj2])
    db_session.flush()

    monday = date(2026, 9, 28)
    
    # Regular class
    slot = TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9, 0), end_time=time(10, 0))
    
    holiday = Holiday(date=monday, description="National Holiday")
    
    # Extra class on holiday
    extra = ClassException(
        subject_id=subj2.id, date=monday, exception_type=ExceptionType.EXTRA
    )
    db_session.add_all([slot, holiday, extra])
    db_session.commit()

    classes = service.get_classes_for_date(monday)
    assert len(classes) == 1
    assert classes[0].subject.code == "CS102"


def test_date_range_applicability(db_session: Session) -> None:
    """Test that semester valid_from and valid_to filters correctly."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    db_session.add(subj1)
    db_session.flush()

    # Slot valid only from Oct 1 to Oct 31
    slot = TimetableSlot(
        subject_id=subj1.id, 
        weekday=0, 
        start_time=time(9, 0), 
        end_time=time(10, 0),
        valid_from=date(2026, 10, 1),
        valid_to=date(2026, 10, 31)
    )
    db_session.add(slot)
    db_session.commit()

    # Sep 28 is Monday, out of range
    sep_monday = date(2026, 9, 28)
    assert len(service.get_classes_for_date(sep_monday)) == 0

    # Oct 5 is Monday, in range
    oct_monday = date(2026, 10, 5)
    assert len(service.get_classes_for_date(oct_monday)) == 1
    
    # Nov 2 is Monday, out of range
    nov_monday = date(2026, 11, 2)
    assert len(service.get_classes_for_date(nov_monday)) == 0


def test_multiple_periods_deduplication(db_session: Session) -> None:
    """Test that multiple slots for the same subject return unique subjects."""
    service = TimetableService(db_session)
    
    subj1 = Subject(code="CS101", name="Intro to CS")
    db_session.add(subj1)
    db_session.flush()

    monday = date(2026, 9, 28)
    # Two slots for CS101 on Monday
    slot1 = TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9, 0), end_time=time(10, 0))
    slot2 = TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(10, 0), end_time=time(11, 0))
    
    db_session.add_all([slot1, slot2])
    db_session.commit()

    classes = service.get_classes_for_date(monday)
    # Should only return one instance of the Subject
    assert len(classes) == 1
    assert classes[0].subject.code == "CS101"
