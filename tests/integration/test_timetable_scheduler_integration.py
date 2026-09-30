"""Integration tests for DailyCheckRunner and TimetableService."""

from datetime import date, datetime, time, timezone
import pytest
from sqlalchemy.orm import Session

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.core.enums import AttendanceStatus, DecisionAction
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.notifications.base import BaseNotificationProvider, NotificationOutcome, NotificationPayload
from app.services.daily_scheduler import DailyCheckRunner
from app.services.decision_engine import DecisionResult


class MockNotificationProvider(BaseNotificationProvider):
    def __init__(self) -> None:
        self.sent_decisions: list[NotificationPayload] = []
        
    @property
    def provider_name(self) -> str:
        return "mock"
        
    @property
    def is_dry_run(self) -> bool:
        return False
        
    def validate_config(self) -> bool:
        return True
        
    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        self.sent_decisions.append(payload)
        return NotificationOutcome(success=True, provider_name="mock", is_dry_run=False, message_preview="test")


class MockAdapter(BasePortalAdapter):
    def __init__(self, records: list[SubjectAttendance]):
        self.records = records

    @property
    def adapter_name(self) -> str:
        return "mock"

    def validate_config(self) -> bool:
        return True

    def authenticate(self) -> bool:
        return True

    def get_attendance_for_date(self, target_date: date) -> list[SubjectAttendance]:
        return self.records

    def normalize_status(self, raw_status: str | None) -> AttendanceStatus:
        return AttendanceStatus.UNKNOWN

    def close(self) -> None:
        pass


@pytest.fixture
def test_context(db_session: Session) -> dict:
    subj1 = Subject(code="CS101", name="CS101")
    subj2 = Subject(code="CS102", name="CS102")
    subj3 = Subject(code="CS103", name="CS103") # Unscheduled
    db_session.add_all([subj1, subj2, subj3])
    db_session.flush()

    prof1 = ProfessorMapping(subject_id=subj1.id, professor_name="Prof 1", professor_email="prof1@test.com")
    prof2 = ProfessorMapping(subject_id=subj2.id, professor_name="Prof 2", professor_email="prof2@test.com")
    db_session.add_all([prof1, prof2])
    db_session.commit()

    return {
        "subj1": subj1,
        "subj2": subj2,
        "subj3": subj3,
    }


def test_missing_portal_record_evaluates_unknown(db_session: Session, test_context: dict) -> None:
    """Test that a scheduled class missing from portal response evaluates to UNKNOWN and NO_ACTION."""
    subj1 = test_context["subj1"]
    subj2 = test_context["subj2"]
    
    target = date(2026, 9, 28) # Monday
    
    # Schedule CS101 and CS102
    db_session.add(TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9), end_time=time(10)))
    db_session.add(TimetableSlot(subject_id=subj2.id, weekday=0, start_time=time(10), end_time=time(11)))
    db_session.add(AttendanceConfirmation(date=target))
    db_session.commit()

    # Portal only returns CS101
    adapter = MockAdapter([
        SubjectAttendance("CS101", AttendanceStatus.PRESENT, True),
    ])

    provider = MockNotificationProvider()
    runner = DailyCheckRunner(db_session, notification_provider=provider)
    result = runner.run_daily_check(
        target_date=target,
        current_time=datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc),
        adapter=adapter,
        dry_run=False
    )
    
    # We should have 2 decisions: one from portal, one synthesized missing
    assert len(result.decisions) == 2
    cs101_dec = next(d for d in result.decisions if d.subject_code == "CS101")
    cs102_dec = next(d for d in result.decisions if d.subject_code == "CS102")
    
    assert cs101_dec.status == AttendanceStatus.PRESENT
    assert cs101_dec.action == DecisionAction.NO_ACTION
    
    assert cs102_dec.status == AttendanceStatus.UNKNOWN
    assert cs102_dec.is_reliable is False
    assert cs102_dec.action == DecisionAction.NO_ACTION


def test_unscheduled_subject_evaluates(db_session: Session, test_context: dict) -> None:
    """Test that an unscheduled class returned by portal is still evaluated correctly."""
    subj3 = test_context["subj3"]
    
    target = date(2026, 9, 28)
    db_session.add(AttendanceConfirmation(date=target))
    # Note: NO timetable slots added
    db_session.commit()

    # Portal returns CS103 which has NO professor mapping and is NOT scheduled
    adapter = MockAdapter([
        SubjectAttendance("CS103", AttendanceStatus.ABSENT, True),
    ])

    provider = MockNotificationProvider()
    runner = DailyCheckRunner(db_session, notification_provider=provider)
    result = runner.run_daily_check(
        target_date=target,
        current_time=datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc),
        adapter=adapter,
        dry_run=False
    )
    
    assert len(result.decisions) == 1
    dec = result.decisions[0]
    assert dec.subject_code == "CS103"
    assert dec.status == AttendanceStatus.ABSENT
    assert dec.action == DecisionAction.NO_ACTION # Missing professor mapping


def test_holiday_does_not_synthesize_missing(db_session: Session, test_context: dict) -> None:
    """Test that on a holiday, scheduled classes are not expected and missing classes aren't synthesized."""
    subj1 = test_context["subj1"]
    
    target = date(2026, 9, 28)
    db_session.add(TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9), end_time=time(10)))
    db_session.add(Holiday(date=target, description="Test Holiday"))
    db_session.add(AttendanceConfirmation(date=target))
    db_session.commit()

    # Portal returns nothing
    adapter = MockAdapter([])

    runner = DailyCheckRunner(db_session, notification_provider=MockNotificationProvider())
    result = runner.run_daily_check(
        target_date=target,
        current_time=datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc),
        adapter=adapter,
        dry_run=False
    )
    
    assert len(result.decisions) == 0


def test_cancelled_class_does_not_synthesize_missing(db_session: Session, test_context: dict) -> None:
    """Test that a cancelled class isn't expected."""
    subj1 = test_context["subj1"]
    
    target = date(2026, 9, 28)
    db_session.add(TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9), end_time=time(10)))
    db_session.add(ClassException(subject_id=subj1.id, date=target, exception_type=ExceptionType.CANCELLED))
    db_session.add(AttendanceConfirmation(date=target))
    db_session.commit()

    adapter = MockAdapter([])
    runner = DailyCheckRunner(db_session, notification_provider=MockNotificationProvider())
    result = runner.run_daily_check(
        target_date=target,
        current_time=datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc),
        adapter=adapter,
        dry_run=False
    )
    
    assert len(result.decisions) == 0


def test_extra_class_synthesizes_missing(db_session: Session, test_context: dict) -> None:
    """Test that an extra class is expected."""
    subj1 = test_context["subj1"]
    
    target = date(2026, 9, 28)
    db_session.add(ClassException(subject_id=subj1.id, date=target, exception_type=ExceptionType.EXTRA))
    db_session.add(AttendanceConfirmation(date=target))
    db_session.commit()

    adapter = MockAdapter([])
    runner = DailyCheckRunner(db_session, notification_provider=MockNotificationProvider())
    result = runner.run_daily_check(
        target_date=target,
        current_time=datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc),
        adapter=adapter,
        dry_run=False
    )
    
    assert len(result.decisions) == 1
    assert result.decisions[0].subject_code == "CS101"
    assert result.decisions[0].status == AttendanceStatus.UNKNOWN


def test_comprehensive_safety_rules(db_session: Session, test_context: dict) -> None:
    """
    Test scheduled + PRESENT
    Test scheduled + ABSENT + confirmed
    Test scheduled + ABSENT + unconfirmed
    Test duplicate notification prevention
    """
    subj1 = test_context["subj1"]
    subj2 = test_context["subj2"]
    
    target = date(2026, 9, 28)
    db_session.add(TimetableSlot(subject_id=subj1.id, weekday=0, start_time=time(9), end_time=time(10)))
    db_session.add(TimetableSlot(subject_id=subj2.id, weekday=0, start_time=time(10), end_time=time(11)))
    db_session.commit()
    
    # 1. Unconfirmed => SKIPPED
    adapter = MockAdapter([
        SubjectAttendance("CS101", AttendanceStatus.PRESENT, True),
        SubjectAttendance("CS102", AttendanceStatus.ABSENT, True),
    ])
    provider = MockNotificationProvider()
    runner = DailyCheckRunner(db_session, notification_provider=provider)
    res1 = runner.run_daily_check(target_date=target, adapter=adapter, ignore_cutoff=True)
    assert res1.status == "SKIPPED"
    assert res1.reason == "ATTENDANCE_NOT_CONFIRMED"
    
    # 2. Confirmed
    db_session.add(AttendanceConfirmation(date=target))
    db_session.commit()
    
    res2 = runner.run_daily_check(target_date=target, adapter=adapter, ignore_cutoff=True, dry_run=False)
    assert res2.status == "SUCCESS"
    assert len(res2.decisions) == 2
    
    cs101 = next(d for d in res2.decisions if d.subject_code == "CS101")
    cs102 = next(d for d in res2.decisions if d.subject_code == "CS102")
    
    assert cs101.status == AttendanceStatus.PRESENT
    assert cs101.action == DecisionAction.NO_ACTION
    
    assert cs102.status == AttendanceStatus.ABSENT
    assert cs102.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    
    assert len(provider.sent_decisions) == 1
    assert provider.sent_decisions[0].subject_code == "CS102"
    
    # 3. Duplicate prevention
    res3 = runner.run_daily_check(target_date=target, adapter=adapter, ignore_cutoff=True, dry_run=False)
    cs102_dup = next(d for d in res3.decisions if d.subject_code == "CS102")
    assert cs102_dup.action == DecisionAction.NO_ACTION
    assert len(provider.sent_decisions) == 1 # Still 1
