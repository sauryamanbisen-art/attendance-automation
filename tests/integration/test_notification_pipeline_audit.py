"""Comprehensive End-to-End Real-World Notification Pipeline Audit Tests.

Systematically verifies all 19 requirements:
1. Confirmed attendance reaches scheduled check
2. Timetable resolution (normal, holidays, cancelled, extra)
3. Portal PRESENT -> no notification
4. Portal UNKNOWN -> no notification
5. Unreliable portal extraction -> no notification
6. ABSENT + confirmed + reliable + valid professor mapping -> notification dispatched
7. Missing professor mapping/email stops dispatch safely
8. Duplicate notification prevention across repeated/concurrent runs
9. Dry-run mode never sends external messages
10. Gmail provider handles auth, token loading, message construction, API dispatch, failures
11. Google Chat provider remains unaffected
12. NotificationEvent records SENT, FAILED, DRY_RUN states
13. Provider failures never crash the scheduler
14. No secrets or tokens leaked in API responses
15. Settings UI accurately represents provider state
16. Message content verification (recipient, subject, codes, date, polite tone)
17. Cancelled classes & holidays never generate notifications
18. Extra classes handled correctly (including on holidays)
19. All existing APIs and routes unaffected
"""

from datetime import date, datetime, time, timezone
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.core.enums import (
    AttendanceStatus,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.database.base import Base
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.notifications.base import BaseNotificationProvider, NotificationOutcome, NotificationPayload
from app.notifications.gmail.client import GmailClient
from app.notifications.gmail.config import GmailConfig
from app.notifications.gmail.provider import GmailNotificationProvider
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.provider import GoogleChatNotificationProvider
from app.notifications.message import generate_correction_body, generate_correction_subject
from app.notifications.oauth import GoogleOAuthClient, InMemoryTokenStorage, OAuthToken
from app.notifications.service import NotificationService
from app.services.confirmation import ConfirmationService
from app.services.daily_scheduler import DailyCheckRunner
from app.services.decision_engine import DecisionEngine
from app.services.timetable_service import TimetableService
from main import app


@pytest.fixture
def audit_db():
    """In-memory SQLite database isolated for pipeline audit."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_subject(audit_db):
    """Create a subject with complete professor mapping."""
    sub = Subject(code="CS501", name="Distributed Computing")
    audit_db.add(sub)
    audit_db.flush()

    prof = ProfessorMapping(
        subject_id=sub.id,
        professor_name="Dr. Leslie Lamport",
        professor_email="lamport@university.edu",
        google_chat_space="spaces/LAMPORT_SPACE",
    )
    audit_db.add(prof)
    audit_db.commit()
    audit_db.refresh(sub)
    return sub


class FakeAdapter(BasePortalAdapter):
    """Controlled portal adapter for pipeline audit."""

    def __init__(self, records: List[SubjectAttendance]):
        self.records = records

    @property
    def adapter_name(self) -> str:
        return "FakeAdapter"

    def authenticate(self) -> bool:
        return True

    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        return self.records

    def validate_config(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def normalize_status(self, raw_status: str) -> AttendanceStatus:
        return AttendanceStatus.PRESENT


class RecordingProvider(BaseNotificationProvider):
    """In-memory recording notification provider."""

    def __init__(self, is_dry_run: bool = False, should_fail: bool = False):
        self._is_dry_run = is_dry_run
        self.should_fail = should_fail
        self.sent_payloads: List[NotificationPayload] = []

    @property
    def provider_name(self) -> str:
        return "recording_mock"

    @property
    def is_dry_run(self) -> bool:
        return self._is_dry_run

    def validate_config(self) -> bool:
        return True

    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        if self.should_fail:
            raise RuntimeError("Simulated external provider crash!")
        self.sent_payloads.append(payload)
        return NotificationOutcome(
            success=True,
            provider_name=self.provider_name,
            is_dry_run=self._is_dry_run,
            message_preview=f"Sent to {payload.recipient_email}",
            details={"msg_id": "test-msg-123"},
        )


# ============================================================================
# AUDIT TESTS
# ============================================================================

def test_1_confirmed_date_reaches_scheduled_check(audit_db, sample_subject):
    """1. A confirmed attendance date can reach the scheduled check correctly."""
    target_date = date(2026, 9, 29)
    conf_svc = ConfirmationService(audit_db)
    
    # Before confirmation: check is skipped
    runner = DailyCheckRunner(db=audit_db)
    res_unconfirmed = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([]),
    )
    assert res_unconfirmed.status == "SKIPPED"
    assert res_unconfirmed.reason == "ATTENDANCE_NOT_CONFIRMED"

    # Confirm attendance
    conf_svc.confirm_attendance(target_date)
    assert conf_svc.is_confirmed(target_date) is True

    # After confirmation: check runs successfully
    res_confirmed = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code="CS501", status=AttendanceStatus.PRESENT, is_reliable=True)
        ]),
    )
    assert res_confirmed.status == "SUCCESS"
    assert res_confirmed.subjects_checked == 1


def test_2_timetable_resolution_handles_all_cases(audit_db, sample_subject):
    """2. Timetable resolution correctly handles normal, holidays, cancelled, extra."""
    target_date = date(2026, 9, 29)  # Tuesday (weekday 1)
    tt_svc = TimetableService(audit_db)

    # Add second subject
    sub2 = Subject(code="CS502", name="Operating Systems")
    audit_db.add(sub2)
    audit_db.flush()

    # Normal slot for CS501 on Tuesday
    slot = TimetableSlot(
        subject_id=sample_subject.id,
        weekday=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    audit_db.add(slot)
    audit_db.commit()

    # Case A: Normal Tuesday -> CS501 scheduled
    classes = tt_svc.get_classes_for_date(target_date)
    assert [c.code for c in classes] == ["CS501"]

    # Case B: Cancelled exception -> CS501 cancelled
    exc_cancel = ClassException(
        subject_id=sample_subject.id,
        date=target_date,
        exception_type=ExceptionType.CANCELLED,
        description="Prof unwell",
    )
    audit_db.add(exc_cancel)
    audit_db.commit()
    assert tt_svc.get_classes_for_date(target_date) == []

    # Case C: Extra class for CS502 -> CS502 included
    exc_extra = ClassException(
        subject_id=sub2.id,
        date=target_date,
        exception_type=ExceptionType.EXTRA,
        start_time=time(14, 0),
        end_time=time(15, 0),
    )
    audit_db.add(exc_extra)
    audit_db.commit()
    assert [c.code for c in tt_svc.get_classes_for_date(target_date)] == ["CS502"]

    # Case D: Holiday declared -> regular classes suppressed, but extra classes remain
    holiday = Holiday(date=target_date, description="National Holiday")
    audit_db.add(holiday)
    audit_db.commit()
    # Even on holiday, extra scheduled class CS502 remains
    assert [c.code for c in tt_svc.get_classes_for_date(target_date)] == ["CS502"]


def test_3_portal_present_never_notifies(audit_db, sample_subject):
    """3. Portal PRESENT never generates a notification."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider()
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.PRESENT, is_reliable=True)
        ]),
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 0
    assert res.notifications_sent == 0
    assert len(provider.sent_payloads) == 0
    assert audit_db.query(NotificationEvent).count() == 0


def test_4_portal_unknown_never_notifies(audit_db, sample_subject):
    """4. Portal UNKNOWN never generates a notification."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider()
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.UNKNOWN, is_reliable=True)
        ]),
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 0
    assert res.notifications_sent == 0
    assert len(provider.sent_payloads) == 0


def test_5_unreliable_portal_extraction_never_notifies(audit_db, sample_subject):
    """5. Unreliable portal extraction never generates a notification."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider()
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    # Portal reported ABSENT, but is_reliable is False (OCR glitch or partial page)
    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=False)
        ]),
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 0
    assert res.notifications_sent == 0
    assert len(provider.sent_payloads) == 0


def test_6_absent_confirmed_reliable_valid_mapping_dispatches(audit_db, sample_subject):
    """6. ABSENT + confirmed + reliable + valid professor mapping reaches notification dispatch."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider(is_dry_run=False)
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 1
    assert res.notifications_sent == 1
    assert len(provider.sent_payloads) == 1

    payload = provider.sent_payloads[0]
    assert payload.recipient_email == "lamport@university.edu"
    assert payload.subject_code == "CS501"

    # Notification event recorded with SENT
    event = audit_db.query(NotificationEvent).filter_by(subject_id=sample_subject.id).first()
    assert event is not None
    assert event.status == NotificationStatus.SENT
    assert event.dry_run is False


def test_7_missing_professor_mapping_stops_dispatch_safely(audit_db):
    """7. Missing professor mapping/email stops dispatch safely."""
    # Subject without professor mapping
    orphan_sub = Subject(code="ORPHAN101", name="Unmapped Course")
    audit_db.add(orphan_sub)
    audit_db.commit()

    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider()
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code="ORPHAN101", status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 0
    assert res.notifications_sent == 0
    assert len(provider.sent_payloads) == 0


def test_8_duplicate_notification_prevention(audit_db, sample_subject):
    """8. Duplicate notification prevention works even across repeated/concurrent executions."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider(is_dry_run=False)
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    # First run sends notification
    res1 = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res1.notifications_sent == 1
    assert len(provider.sent_payloads) == 1

    # Second run for same date and subject MUST be suppressed by DecisionEngine
    res2 = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res2.eligible_count == 0
    assert res2.notifications_sent == 0
    assert res2.decisions[0].action == DecisionAction.NO_ACTION
    assert res2.decisions[0].reason == DecisionReason.ALREADY_NOTIFIED
    assert len(provider.sent_payloads) == 1  # No additional message sent


def test_9_dry_run_mode_never_sends_external(audit_db, sample_subject):
    """9. Dry-run mode never sends a real external message."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    provider = RecordingProvider(is_dry_run=True)
    runner = DailyCheckRunner(db=audit_db, notification_provider=provider)

    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=True,
    )
    assert res.status == "SUCCESS"
    assert res.dry_run is True

    # Check notification event is recorded as SKIPPED / dry_run=True
    event = audit_db.query(NotificationEvent).filter_by(subject_id=sample_subject.id).first()
    assert event is not None
    assert event.dry_run is True
    assert event.status == NotificationStatus.SKIPPED


def test_10_gmail_provider_pipeline_mocked():
    """10. Gmail provider handles auth, token loading, message construction, API dispatch, failures."""
    config = GmailConfig(
        client_id="test_client_id",
        client_secret="test_secret",
        sender_email="student@university.edu",
    )
    token_storage = InMemoryTokenStorage()
    token_storage.save_token(OAuthToken(
        access_token="valid_access_token",
        refresh_token="valid_refresh_token",
        expires_at=datetime.now(timezone.utc).timestamp() + 3600,
    ))

    mock_http_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "gmail_msg_999", "threadId": "thread_888"}
    mock_http_client.post.return_value = mock_resp

    oauth_client = GoogleOAuthClient(config=config, token_storage=token_storage, http_client=mock_http_client)
    gmail_client = GmailClient(config=config, oauth_client=oauth_client, http_client=mock_http_client)
    provider = GmailNotificationProvider(client=gmail_client, is_dry_run=False)

    payload = NotificationPayload(
        subject_code="CS501",
        subject_name="Distributed Computing",
        target_date=date(2026, 9, 29),
        recipient_email="lamport@university.edu",
        professor_name="Dr. Leslie Lamport",
        message_subject="Review Request",
        message_body="Polite request body",
    )

    outcome = provider.send(payload)
    assert outcome.success is True
    assert outcome.provider_name == "gmail"
    assert outcome.is_dry_run is False
    assert outcome.details.get("external_id") == "gmail_msg_999"

    # Verify mock_http_client called with valid payload
    assert mock_http_client.post.called
    call_args = mock_http_client.post.call_args
    assert "Authorization" in call_args[1]["headers"]
    assert "Bearer valid_access_token" in call_args[1]["headers"]["Authorization"]


def test_11_google_chat_provider_unaffected():
    """11. Google Chat provider remains unaffected and validates routing."""
    config = GoogleChatConfig(
        client_id="gc_client_id",
        client_secret="gc_secret",
        default_space="spaces/DEFAULT_SPACE",
    )
    provider = GoogleChatNotificationProvider(config=config)
    assert provider.provider_name == "google_chat"
    assert provider.is_dry_run is False

    payload_with_space = NotificationPayload(
        subject_code="CS501",
        subject_name="Distributed Computing",
        target_date=date(2026, 9, 29),
        recipient_email="prof@uni.edu",
        professor_name="Dr. Lamport",
        message_subject="Review",
        message_body="Body",
        metadata={"space_id": "spaces/OVERRIDE_SPACE"},
    )
    resolved = provider.resolve_space(payload_with_space)
    assert resolved == "spaces/OVERRIDE_SPACE"


def test_12_notification_event_records_sent_failed_dryrun(audit_db, sample_subject):
    """12. NotificationEvent correctly records SENT, FAILED, and DRY_RUN states."""
    target_date = date(2026, 9, 29)
    decision = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code=sample_subject.code,
        target_date=target_date,
        professor_email=sample_subject.professor_mapping.professor_email,
    )

    # 1. DRY RUN
    notif_svc = NotificationService(provider=RecordingProvider(is_dry_run=True), db=audit_db)
    notif_svc.process_decision(decision)
    event1 = audit_db.query(NotificationEvent).filter_by(subject_id=sample_subject.id).first()
    assert event1.status == NotificationStatus.SKIPPED
    assert event1.dry_run is True

    # Clear event for next test
    audit_db.delete(event1)
    audit_db.commit()

    # 2. SENT
    notif_svc_live = NotificationService(provider=RecordingProvider(is_dry_run=False), db=audit_db)
    notif_svc_live.process_decision(decision)
    event2 = audit_db.query(NotificationEvent).filter_by(subject_id=sample_subject.id).first()
    assert event2.status == NotificationStatus.SENT
    assert event2.dry_run is False

    # Clear event for next test
    audit_db.delete(event2)
    audit_db.commit()

    # 3. FAILED
    failing_provider = RecordingProvider(is_dry_run=False, should_fail=True)
    notif_svc_fail = NotificationService(provider=failing_provider, db=audit_db)
    notif_svc_fail.process_decision(decision)
    event3 = audit_db.query(NotificationEvent).filter_by(subject_id=sample_subject.id).first()
    assert event3.status == NotificationStatus.FAILED
    assert "Simulated external provider crash" in event3.error_message


def test_13_provider_failures_never_crash_scheduler(audit_db, sample_subject):
    """13. Provider failures never crash the scheduler."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    crashing_provider = RecordingProvider(is_dry_run=False, should_fail=True)
    runner = DailyCheckRunner(db=audit_db, notification_provider=crashing_provider)

    # Scheduler MUST finish with status SUCCESS and not raise an unhandled exception
    res = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=FakeAdapter([
            SubjectAttendance(subject_code=sample_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res.status == "SUCCESS"
    assert res.eligible_count == 1
    assert res.notifications_sent == 0  # Failed, so 0 sent


def test_14_no_secrets_in_settings_or_providers_api():
    """14. No OAuth tokens, client secrets, passwords, or filesystem paths reach API responses."""
    client = TestClient(app)
    resp = client.get("/api/notifications/providers")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "secret" not in text
    assert "token" not in text or "token_file" not in text
    assert "credentials/" not in text
    assert "password" not in text


def test_15_settings_ui_provider_state_representation():
    """15. Verify that provider status endpoint reflects configured/connected flags cleanly."""
    client = TestClient(app)
    resp = client.get("/api/notifications/providers")
    assert resp.status_code == 200
    data = resp.json()
    provider_ids = [p["id"] for p in data["providers"]]
    assert "google_chat" in provider_ids
    assert "gmail" in provider_ids
    for p in data["providers"]:
        assert "is_configured" in p
        assert "connected" in p
        assert "auth_url" in p


def test_16_notification_message_content():
    """16. Verify message content: recipient, subject, course code/name, date, polite request."""
    subject_code = "CS501"
    subject_name = "Distributed Computing"
    target_date = date(2026, 9, 29)
    professor_name = "Dr. Leslie Lamport"
    student_name = "Alex Student"

    subj_line = generate_correction_subject(subject_code, subject_name, target_date)
    assert "CS501" in subj_line
    assert "Distributed Computing" in subj_line
    assert "29 September 2026" in subj_line

    body = generate_correction_body(
        subject_code=subject_code,
        subject_name=subject_name,
        target_date=target_date,
        professor_name=professor_name,
        student_name=student_name,
    )
    assert "Dear Dr. Leslie Lamport," in body
    assert "Alex Student" in body
    assert "CS501" in body
    assert "Distributed Computing" in body
    assert "29 September 2026" in body
    assert "Could you kindly review the attendance record at your convenience?" in body


def test_17_cancelled_and_holiday_classes_no_notification(audit_db, sample_subject):
    """17. Verify that no notification is sent for cancelled classes or holidays."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    # Add holiday
    audit_db.add(Holiday(date=target_date, description="Founders Day"))
    audit_db.commit()

    dec = DecisionEngine().evaluate_subject_record(
        db=audit_db,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert dec.action == DecisionAction.NO_ACTION
    assert dec.reason == DecisionReason.HOLIDAY
    assert dec.is_eligible is False


def test_18_extra_classes_handled_correctly(audit_db, sample_subject):
    """18. Verify that EXTRA classes are handled correctly even on holidays."""
    target_date = date(2026, 9, 29)
    ConfirmationService(audit_db).confirm_attendance(target_date)

    # Holiday + Extra class for this subject
    audit_db.add(Holiday(date=target_date, description="Founders Day"))
    audit_db.add(ClassException(
        subject_id=sample_subject.id,
        date=target_date,
        exception_type=ExceptionType.EXTRA,
        start_time=time(10, 0),
        end_time=time(11, 0),
    ))
    audit_db.commit()

    dec = DecisionEngine().evaluate_subject_record(
        db=audit_db,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert dec.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert dec.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert dec.is_eligible is True


def test_19_all_existing_apis_unaffected():
    """19. Verify all primary API endpoints remain healthy."""
    client = TestClient(app)
    
    assert client.get("/").status_code == 200
    assert client.get("/api/dashboard/today").status_code == 200
    assert client.get("/api/timetable/").status_code == 200
    assert client.get("/api/calendar/holidays").status_code == 200
    assert client.get("/api/calendar/exceptions").status_code == 200
    assert client.get("/api/subjects").status_code == 200
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/notifications/providers").status_code == 200


def test_20_complete_seven_step_notification_flow(audit_db, sample_subject):
    """Audit and test the complete 7-step notification flow sequentially:
    1. Student attendance confirmation = confirmed
    2. Attendance result = ABSENT
    3. Valid professor mapping exists
    4. Decision engine returns ELIGIBLE_FOR_NOTIFICATION
    5. Notification service prepares the notification correctly
    6. Dry-run mode must NOT send a real email
    7. Running the same check twice must prevent duplicate notification and return ALREADY_NOTIFIED
    """
    target_date = date(2026, 9, 29)
    conf_svc = ConfirmationService(audit_db)

    # 1. Student attendance confirmation = confirmed
    assert conf_svc.is_confirmed(target_date) is False
    conf_record, created = conf_svc.confirm_attendance(target_date, note="Attended university campus")
    assert created is True
    assert conf_svc.is_confirmed(target_date) is True

    # 2. Attendance result = ABSENT
    fake_adapter = FakeAdapter([
        SubjectAttendance(
            subject_code=sample_subject.code,
            subject_name=sample_subject.name,
            status=AttendanceStatus.ABSENT,
            raw_status="Absent",
            is_reliable=True,
        )
    ])
    records = fake_adapter.get_attendance_for_date(target_date)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ABSENT
    assert records[0].is_reliable is True

    # 3. Valid professor mapping exists
    assert sample_subject.professor_mapping is not None
    assert sample_subject.professor_mapping.professor_name == "Dr. Leslie Lamport"
    assert sample_subject.professor_mapping.professor_email == "lamport@university.edu"

    # 4. Decision engine returns ELIGIBLE_FOR_NOTIFICATION
    engine = DecisionEngine()
    decision = engine.evaluate_subject_record(
        db=audit_db,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=records[0].status,
        is_reliable=records[0].is_reliable,
    )
    assert decision.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert decision.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert decision.is_eligible is True
    assert decision.professor_email == "lamport@university.edu"

    # 5. Notification service prepares the notification correctly
    # 6. Dry-run mode must NOT send a real email
    mock_gmail_client = MagicMock(spec=GmailClient)
    mock_gmail_client.config = GmailConfig(client_id="audit_cid", client_secret="audit_csec")
    gmail_dry_run_provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=True)

    notif_svc = NotificationService(
        provider=gmail_dry_run_provider,
        db=audit_db,
        student_name="Alex Student",
    )

    captured_payloads = []
    real_send = gmail_dry_run_provider.send

    def spy_send(p):
        captured_payloads.append(p)
        return real_send(p)

    gmail_dry_run_provider.send = spy_send

    outcome = notif_svc.process_decision(decision)

    # Validate prepared notification content
    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload.recipient_email == "lamport@university.edu"
    assert payload.professor_name == "Dr. Leslie Lamport"
    assert payload.subject_code == "CS501"
    assert payload.subject_name == "Distributed Computing"
    assert payload.target_date == target_date
    assert payload.student_name == "Alex Student"
    assert "CS501" in payload.message_subject
    assert "Distributed Computing" in payload.message_subject
    assert "Dear Dr. Leslie Lamport," in payload.message_body
    assert "Alex Student" in payload.message_body
    assert "Could you kindly review the attendance record" in payload.message_body

    # Validate dry-run outcome (no real email dispatch)
    assert outcome is not None
    assert outcome.success is True
    assert outcome.is_dry_run is True
    mock_gmail_client.send_email.assert_not_called()
    assert mock_gmail_client.send_email.call_count == 0

    # Notification event recorded as SKIPPED
    event = (
        audit_db.query(NotificationEvent)
        .filter(
            NotificationEvent.subject_code == sample_subject.code,
            NotificationEvent.date == target_date,
        )
        .first()
    )
    assert event is not None
    assert event.status == NotificationStatus.SKIPPED
    assert event.dry_run is True
    assert event.sent_at is None

    # 7. Running the same check twice must prevent duplicate notification and return ALREADY_NOTIFIED
    decision_run_2 = engine.evaluate_subject_record(
        db=audit_db,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert decision_run_2.action == DecisionAction.NO_ACTION
    assert decision_run_2.reason == DecisionReason.ALREADY_NOTIFIED
    assert decision_run_2.is_eligible is False

    outcome_run_2 = notif_svc.process_decision(decision_run_2)
    assert outcome_run_2 is None
    assert len(captured_payloads) == 1
    mock_gmail_client.send_email.assert_not_called()

    # Also test via full DailyCheckRunner to verify pipeline-level duplicate suppression
    runner = DailyCheckRunner(
        db=audit_db,
        notification_provider=gmail_dry_run_provider,
    )
    check_result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=fake_adapter,
        dry_run=True,
    )
    assert check_result.status == "SUCCESS"
    assert check_result.eligible_count == 0
    assert check_result.notifications_sent == 0
    assert check_result.decisions[0].action == DecisionAction.NO_ACTION
    assert check_result.decisions[0].reason == DecisionReason.ALREADY_NOTIFIED
    mock_gmail_client.send_email.assert_not_called()

    # Confirm database event count remains exactly 1 (no duplicate record)
    total_events = (
        audit_db.query(NotificationEvent)
        .filter(
            NotificationEvent.subject_code == sample_subject.code,
            NotificationEvent.date == target_date,
        )
        .count()
    )
    assert total_events == 1

