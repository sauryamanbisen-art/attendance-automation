"""Comprehensive Integration and Safety Tests for Professor Notification & Google Chat Integration.

Verifies all 14 required conditions:
1. Subject → professor mapping CRUD (including name, email, google_chat_space, is_active)
2. Professor notification configuration & active toggle
3. Google Chat destination configuration & resolution precedence
4. Missing professor mapping → NO_ACTION & audit recorded
5. Missing notification destination → fail closed & audit recorded
6. Portal PRESENT → NO_ACTION (no notification)
7. Portal UNKNOWN / unreliable / error → fail closed (no notification)
8. ABSENT without daily confirmation → NO_ACTION (no notification)
9. ABSENT with daily confirmation → ELIGIBLE_FOR_NOTIFICATION & Google Chat dispatch
10. Duplicate notification prevention (idempotency across runs)
11. DRY_RUN behavior (no external network calls, SKIPPED state in DB)
12. Fake Google Chat adapter behavior & message tracking
13. Notification failure handling (safe error recording, no scheduler crash)
14. Fail-closed behavior under all edge cases
"""

from datetime import date, datetime, time, timezone
from typing import List
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    CheckStatus,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.database.base import Base
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.attendance_result import AttendanceResult
from app.models.audit_event import AuditEvent
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.base import NotificationOutcome, NotificationPayload
from app.notifications.google_chat.client import GoogleChatClient
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.exceptions import (
    GoogleChatApiError,
    GoogleChatPermissionError,
    GoogleChatRecipientError,
)
from app.notifications.google_chat.fake import FakeGoogleChatClient
from app.notifications.google_chat.provider import GoogleChatNotificationProvider
from app.notifications.service import NotificationService
from app.services.confirmation import ConfirmationService
from app.services.daily_scheduler import DailyCheckRunner
from app.services.decision_engine import DecisionEngine, DecisionResult
from main import app


@pytest.fixture
def db():
    """Isolated in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def configured_subject(db):
    """Create a subject with complete professor and Google Chat destination mapping."""
    sub = Subject(code="CS301", name="Database Systems")
    db.add(sub)
    db.flush()

    mapping = ProfessorMapping(
        subject_id=sub.id,
        professor_name="Dr. Edgar Codd",
        professor_email="codd@university.edu",
        google_chat_space="spaces/DATABASE_FACULTY",
        is_active=True,
    )
    db.add(mapping)
    db.commit()
    db.refresh(sub)
    return sub


class ControlledAdapter(BasePortalAdapter):
    """Test adapter returning predetermined attendance records."""

    def __init__(self, records: List[SubjectAttendance]):
        self.records = records

    @property
    def adapter_name(self) -> str:
        return "ControlledAdapter"

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


# ==============================================================================
# 1. Subject → Professor Mapping CRUD (including Google Chat space & is_active)
# ==============================================================================


def test_subject_professor_mapping_crud(client: TestClient):
    """Verify Subject and ProfessorMapping API handles name, email, google_chat_space, and is_active."""

    # CREATE subject with full professor notification details
    create_payload = {
        "code": "TEST101",
        "name": "Testing Fundamentals",
        "professor_name": "Prof. Ada Lovelace",
        "professor_email": "ada@university.edu",
        "google_chat_space": "spaces/TESTING_SPACE",
        "is_active": True,
    }
    create_res = client.post("/api/subjects", json=create_payload)
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["code"] == "TEST101"
    assert created["professor_name"] == "Prof. Ada Lovelace"
    assert created["professor_email"] == "ada@university.edu"
    assert created["google_chat_space"] == "spaces/TESTING_SPACE"
    assert created["is_active"] is True

    # READ subject list
    list_res = client.get("/api/subjects")
    assert list_res.status_code == 200
    sub_item = next(s for s in list_res.json() if s["code"] == "TEST101")
    assert sub_item["google_chat_space"] == "spaces/TESTING_SPACE"
    assert sub_item["is_active"] is True

    # UPDATE mapping via dedicated mapping endpoint
    mapping_payload = {
        "professor_name": "Prof. Ada Lovelace",
        "professor_email": "ada@university.edu",
        "google_chat_space": "spaces/UPDATED_SPACE",
        "is_active": False,
    }
    map_res = client.post("/api/subjects/TEST101/mapping", json=mapping_payload)
    assert map_res.status_code == 200
    mapped = map_res.json()
    assert mapped["google_chat_space"] == "spaces/UPDATED_SPACE"
    assert mapped["is_active"] is False

    # UPDATE subject via PUT
    update_payload = {
        "code": "TEST101",
        "name": "Advanced Testing",
        "professor_name": "Prof. Ada Lovelace",
        "professor_email": "ada@university.edu",
        "google_chat_space": "spaces/FINAL_SPACE",
        "is_active": True,
    }
    put_res = client.put("/api/subjects/TEST101", json=update_payload)
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["name"] == "Advanced Testing"
    assert updated["google_chat_space"] == "spaces/FINAL_SPACE"
    assert updated["is_active"] is True

    # DELETE subject
    del_res = client.delete("/api/subjects/TEST101")
    assert del_res.status_code == 204


# ==============================================================================
# 2. Professor Notification Configuration & Active Toggle
# ==============================================================================


def test_professor_notification_configuration_active_toggle(db, configured_subject):
    """Verify toggling is_active disables/enables notification eligibility in DecisionEngine."""
    target_date = date(2026, 9, 30)
    engine = DecisionEngine()

    # Active = True: absent + confirmed -> ELIGIBLE_FOR_NOTIFICATION
    dec_active = engine.evaluate_subject_record(
        db=db,
        target_date=target_date,
        subject_code=configured_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    # Without daily confirmation: NO_ACTION
    assert dec_active.action == DecisionAction.NO_ACTION
    assert dec_active.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED

    # Add confirmation
    ConfirmationService(db).confirm_attendance(target_date)

    dec_active_conf = engine.evaluate_subject_record(
        db=db,
        target_date=target_date,
        subject_code=configured_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert dec_active_conf.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert dec_active_conf.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert dec_active_conf.is_eligible is True

    # Toggle is_active to False
    configured_subject.professor_mapping.is_active = False
    db.commit()

    dec_inactive = engine.evaluate_subject_record(
        db=db,
        target_date=target_date,
        subject_code=configured_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert dec_inactive.action == DecisionAction.NO_ACTION
    assert dec_inactive.reason == DecisionReason.MISSING_PROFESSOR_MAPPING
    assert dec_inactive.is_eligible is False


# ==============================================================================
# 3. Google Chat Destination Configuration & Resolution Precedence
# ==============================================================================


def test_google_chat_destination_configuration():
    """Verify Google Chat destination resolves in proper precedence: metadata -> recipient map -> default."""
    cfg = GoogleChatConfig(
        default_space="spaces/DEFAULT_FALLBACK",
        recipient_space_mapping={"codd@university.edu": "spaces/MAPPED_SPACE"},
    )
    provider = GoogleChatNotificationProvider(config=cfg)

    # 1. Subject-level override in metadata has highest priority
    p_meta = NotificationPayload(
        subject_code="CS301",
        subject_name="Database Systems",
        target_date=date(2026, 9, 30),
        recipient_email="codd@university.edu",
        professor_name="Dr. Edgar Codd",
        message_subject="Review",
        message_body="Body",
        metadata={"space_id": "spaces/METADATA_SPACE"},
    )
    assert provider.resolve_space(p_meta) == "spaces/METADATA_SPACE"

    # 2. Recipient mapping has second priority
    p_recipient = NotificationPayload(
        subject_code="CS301",
        subject_name="Database Systems",
        target_date=date(2026, 9, 30),
        recipient_email="codd@university.edu",
        professor_name="Dr. Edgar Codd",
        message_subject="Review",
        message_body="Body",
    )
    assert provider.resolve_space(p_recipient) == "spaces/MAPPED_SPACE"

    # 3. Default space has fallback priority
    p_unknown = NotificationPayload(
        subject_code="CS301",
        subject_name="Database Systems",
        target_date=date(2026, 9, 30),
        recipient_email="other@university.edu",
        professor_name="Other Prof",
        message_subject="Review",
        message_body="Body",
    )
    assert provider.resolve_space(p_unknown) == "spaces/DEFAULT_FALLBACK"


# ==============================================================================
# 4. Missing Professor Mapping
# ==============================================================================


def test_missing_professor_mapping_no_notification(db):
    """Verify missing professor mapping prevents notification and records audit event."""
    sub = Subject(code="UNMAPPED", name="Unmapped Subject")
    db.add(sub)
    db.commit()

    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    chat_provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
    )

    runner = DailyCheckRunner(db=db, notification_provider=chat_provider)
    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code="UNMAPPED", status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    assert result.status == "SUCCESS"
    assert result.eligible_count == 0
    assert result.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0
    assert db.query(NotificationEvent).count() == 0

    # Audit event recorded for missing mapping
    skipped_audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "NOTIFICATION_SKIPPED_MISSING_MAPPING")
        .first()
    )
    assert skipped_audit is not None
    assert skipped_audit.details["subject_code"] == "UNMAPPED"
    assert skipped_audit.details["reason"] == "MISSING_PROFESSOR_MAPPING"


# ==============================================================================
# 5. Missing Notification Destination
# ==============================================================================


def test_missing_notification_destination_recorded_in_audit_and_notification(db):
    """Verify missing Google Chat destination safely fails closed, logs error, and records event."""
    sub = Subject(code="NODEST", name="Subject Without Space")
    db.add(sub)
    db.flush()

    mapping = ProfessorMapping(
        subject_id=sub.id,
        professor_name="Dr. No Space",
        professor_email="nospace@university.edu",
        google_chat_space=None,  # No space configured!
    )
    db.add(mapping)
    db.commit()

    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    # Provider with NO default space and NO recipient mapping
    empty_cfg = GoogleChatConfig(default_space=None, recipient_space_mapping={})
    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(config=empty_cfg, api_client=fake_client)

    runner = DailyCheckRunner(db=db, notification_provider=provider)
    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code="NODEST", status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    assert result.status == "SUCCESS"
    assert result.eligible_count == 1
    assert result.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0  # No message sent!

    # NotificationEvent persisted with status=FAILED and error recorded
    event = db.query(NotificationEvent).filter_by(subject_id=sub.id).first()
    assert event is not None
    assert event.status == NotificationStatus.FAILED
    assert "No Google Chat space configured" in event.error_message

    # Audit event recorded with NOTIFICATION_FAILED
    audit = db.query(AuditEvent).filter_by(action="NOTIFICATION_FAILED").first()
    assert audit is not None
    assert "No Google Chat space configured" in audit.details["error"]


# ==============================================================================
# 6. PRESENT → No Notification
# ==============================================================================


def test_portal_present_no_notification(db, configured_subject):
    """Verify portal PRESENT produces NO_ACTION and 0 notifications."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.PRESENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    assert result.status == "SUCCESS"
    assert result.eligible_count == 0
    assert result.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0
    assert db.query(NotificationEvent).count() == 0


# ==============================================================================
# 7. UNKNOWN / Error → No Notification (Fail Closed)
# ==============================================================================


def test_portal_unknown_or_error_fail_closed_no_notification(db, configured_subject):
    """Verify portal UNKNOWN or unreliable result fails closed with NO_ACTION."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    # Case A: Explicit UNKNOWN status
    res_unknown = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.UNKNOWN, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res_unknown.eligible_count == 0
    assert res_unknown.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0

    # Case B: ABSENT but unreliable extraction
    res_unreliable = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=False)
        ]),
        dry_run=False,
    )
    assert res_unreliable.eligible_count == 0
    assert res_unreliable.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0


# ==============================================================================
# 8. ABSENT Without Daily Confirmation → No Notification
# ==============================================================================


def test_absent_without_confirmation_no_notification(db, configured_subject):
    """Verify portal ABSENT without user confirmation skips check safely."""
    target_date = date(2026, 9, 30)
    assert ConfirmationService(db).is_confirmed(target_date) is False

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    assert result.status == "SKIPPED"
    assert result.reason == "ATTENDANCE_NOT_CONFIRMED"
    assert result.notifications_sent == 0
    assert len(fake_client.sent_messages) == 0


# ==============================================================================
# 9. ABSENT With Daily Confirmation → Eligible Notification & Message Content
# ==============================================================================


def test_absent_with_confirmation_dispatches_google_chat(db, configured_subject):
    """Verify confirmed discrepancy dispatches formatted Google Chat message with complete context."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
        is_dry_run=False,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    assert result.status == "SUCCESS"
    assert result.eligible_count == 1
    assert result.notifications_sent == 1
    assert len(fake_client.sent_messages) == 1

    msg = fake_client.sent_messages[0]
    assert msg["space_name"] == "spaces/DATABASE_FACULTY"
    # Verify required message contents
    text = msg["text"]
    assert "CS301" in text  # Subject code
    assert "Database Systems" in text  # Subject name
    assert "Dr. Edgar Codd" in text  # Professor name
    assert "30 September 2026" in text  # Attendance date
    assert "Absent" in text  # Portal status
    assert "attendance discrepancy" in text.lower()  # Reason for notification
    assert "attended the above class" in text.lower()  # Relevant confirmation context

    # Verify database persistence
    event = db.query(NotificationEvent).filter_by(subject_id=configured_subject.id).first()
    assert event is not None
    assert event.status == NotificationStatus.SENT
    assert event.dry_run is False
    assert event.sent_at is not None


# ==============================================================================
# 10. Duplicate Notification Prevention
# ==============================================================================


def test_duplicate_notification_prevention(db, configured_subject):
    """Verify executing multiple checks prevents duplicate notifications for the same event."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
        is_dry_run=False,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    # First check dispatches
    res1 = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res1.notifications_sent == 1
    assert len(fake_client.sent_messages) == 1

    # Second check for the same date and subject MUST be suppressed
    res2 = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )
    assert res2.eligible_count == 0
    assert res2.notifications_sent == 0
    assert res2.decisions[0].action == DecisionAction.NO_ACTION
    assert res2.decisions[0].reason == DecisionReason.ALREADY_NOTIFIED
    assert len(fake_client.sent_messages) == 1  # Still exactly 1 message sent!

    total_events = db.query(NotificationEvent).filter_by(subject_id=configured_subject.id).count()
    assert total_events == 1


# ==============================================================================
# 11. DRY_RUN Behavior
# ==============================================================================


def test_dry_run_behavior_google_chat(db, configured_subject):
    """Verify DRY_RUN mode validates space, returns success, persists SKIPPED event, and sends no messages."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=fake_client,
        is_dry_run=True,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=True,
    )

    assert result.status == "SUCCESS"
    assert result.dry_run is True
    # Zero real API calls made
    assert len(fake_client.sent_messages) == 0

    # NotificationEvent recorded as SKIPPED and dry_run=True
    event = db.query(NotificationEvent).filter_by(subject_id=configured_subject.id).first()
    assert event is not None
    assert event.status == NotificationStatus.SKIPPED
    assert event.dry_run is True
    assert event.sent_at is None

    # Audit event recorded with NOTIFICATION_DRY_RUN
    audit = db.query(AuditEvent).filter_by(action="NOTIFICATION_DRY_RUN").first()
    assert audit is not None
    assert audit.details["is_dry_run"] is True


# ==============================================================================
# 12. Fake Google Chat Adapter Behavior
# ==============================================================================


def test_fake_google_chat_adapter_behavior():
    """Verify FakeGoogleChatClient records messages and supports failure simulation."""
    fake = FakeGoogleChatClient()
    resp = fake.send_message(space_name="spaces/TEST_SPACE", text="Hello faculty")
    assert resp["name"] == "spaces/TEST_SPACE/messages/fake_msg_1"
    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0]["text"] == "Hello faculty"

    # Simulate failure
    failing_fake = FakeGoogleChatClient(should_fail=True)
    with pytest.raises(GoogleChatApiError, match="Simulated Google Chat API delivery failure"):
        failing_fake.send_message(space_name="spaces/TEST", text="Hi")

    # Custom exception simulation
    perm_fake = FakeGoogleChatClient(should_fail=True, fail_exception=GoogleChatPermissionError("Custom 403"))
    with pytest.raises(GoogleChatPermissionError, match="Custom 403"):
        perm_fake.send_message(space_name="spaces/TEST", text="Hi")


# ==============================================================================
# 13. Notification Failure Handling
# ==============================================================================


def test_notification_failure_handling(db, configured_subject):
    """Verify delivery errors fail safely, record FAILED state, and do not crash scheduler."""
    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    # Crashing client
    crashing_client = FakeGoogleChatClient(
        should_fail=True,
        fail_exception=GoogleChatApiError("Google Chat Service Unavailable (503)"),
    )
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(default_space="spaces/DEFAULT"),
        api_client=crashing_client,
        is_dry_run=False,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code=configured_subject.code, status=AttendanceStatus.ABSENT, is_reliable=True)
        ]),
        dry_run=False,
    )

    # Scheduler does not crash; finishes with status SUCCESS
    assert result.status == "SUCCESS"
    assert result.eligible_count == 1
    assert result.notifications_sent == 0

    # NotificationEvent recorded as FAILED
    event = db.query(NotificationEvent).filter_by(subject_id=configured_subject.id).first()
    assert event is not None
    assert event.status == NotificationStatus.FAILED
    assert "Service Unavailable" in event.error_message

    # AuditEvent recorded as NOTIFICATION_FAILED
    audit = db.query(AuditEvent).filter_by(action="NOTIFICATION_FAILED").first()
    assert audit is not None
    assert "Service Unavailable" in audit.details["error"]


# ==============================================================================
# 14. Fail-Closed Behavior
# ==============================================================================


def test_fail_closed_behavior(db):
    """Verify safety engine fails closed under missing subjects, corrupt entries, or unconfirmed states."""
    engine = DecisionEngine()
    target_date = date(2026, 9, 30)

    # Missing confirmation -> NO_ACTION
    r1 = engine.evaluate(
        is_confirmed=False,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS999",
        target_date=target_date,
        professor_email="prof@uni.edu",
    )
    assert r1.action == DecisionAction.NO_ACTION
    assert r1.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED

    # Missing email -> NO_ACTION
    r2 = engine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS999",
        target_date=target_date,
        professor_email=None,
    )
    assert r2.action == DecisionAction.NO_ACTION
    assert r2.reason == DecisionReason.MISSING_PROFESSOR_MAPPING

    # Ineligible decision passed to NotificationService -> returns None, never calls provider
    mock_provider = MagicMock(spec=GoogleChatNotificationProvider)
    service = NotificationService(provider=mock_provider, db=db)
    outcome = service.process_decision(r1)
    assert outcome is None
    mock_provider.send.assert_not_called()


# ==============================================================================
# 15. Shared Google Chat Space Support (Multiple Subjects/Professors)
# ==============================================================================


def test_multiple_subjects_share_same_google_chat_space(db):
    """Verify multiple subjects/professors can share the exact same Google Chat space without collision."""
    shared_space = "spaces/DEPARTMENT_SHARED_SPACE"

    # Subject 1
    sub1 = Subject(code="CS401", name="Operating Systems")
    db.add(sub1)
    db.flush()
    m1 = ProfessorMapping(
        subject_id=sub1.id,
        professor_name="Prof. Linus",
        professor_email="linus@university.edu",
        google_chat_space=shared_space,
        is_active=True,
    )
    db.add(m1)

    # Subject 2 with different professor but SAME Google Chat Space
    sub2 = Subject(code="CS402", name="Distributed Systems")
    db.add(sub2)
    db.flush()
    m2 = ProfessorMapping(
        subject_id=sub2.id,
        professor_name="Prof. Leslie",
        professor_email="leslie@university.edu",
        google_chat_space=shared_space,
        is_active=True,
    )
    db.add(m2)
    db.commit()

    target_date = date(2026, 9, 30)
    ConfirmationService(db).confirm_attendance(target_date)

    fake_client = FakeGoogleChatClient()
    provider = GoogleChatNotificationProvider(
        config=GoogleChatConfig(),
        api_client=fake_client,
        is_dry_run=False,
    )
    runner = DailyCheckRunner(db=db, notification_provider=provider)

    result = runner.run_daily_check(
        target_date=target_date,
        ignore_cutoff=True,
        adapter=ControlledAdapter([
            SubjectAttendance(subject_code="CS401", status=AttendanceStatus.ABSENT, is_reliable=True),
            SubjectAttendance(subject_code="CS402", status=AttendanceStatus.ABSENT, is_reliable=True),
        ]),
        dry_run=False,
    )

    assert result.status == "SUCCESS"
    assert result.eligible_count == 2
    assert result.notifications_sent == 2
    assert len(fake_client.sent_messages) == 2

    # Both messages delivered to the EXACT same space
    assert fake_client.sent_messages[0]["space_name"] == shared_space
    assert fake_client.sent_messages[1]["space_name"] == shared_space

    # Each message has its own professor and subject details
    texts = [msg["text"] for msg in fake_client.sent_messages]
    assert any("Operating Systems" in t and "Prof. Linus" in t for t in texts)
    assert any("Distributed Systems" in t and "Prof. Leslie" in t for t in texts)

