"""Integration tests verifying portal adapter results fed into the Decision Engine and Notification Service.

Critical Invariant Verified:
CONFIRMED DAY + RELIABLE PORTAL ABSENCE + VALID PROFESSOR MAPPING + NOT ALREADY NOTIFIED
= ELIGIBLE_FOR_NOTIFICATION
All other combinations fail closed to NO_ACTION.
"""

import socket
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.base.adapter import SubjectAttendance
from app.adapters.playwright.adapter import GenericPlaywrightPortalAdapter
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.config import PlaywrightPortalConfig
from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.database.base import Base
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.audit_event import AuditEvent
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.dry_run import DryRunNotificationProvider
from app.notifications.service import NotificationService
from app.services.decision_engine import DecisionEngine


@pytest.fixture(name="db_session")
def fixture_db_session():
    """In-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="guard_network", autouse=True)
def fixture_guard_network():
    """Verify that tests NEVER make real outbound network connections."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        raise AssertionError(f"Outbound network connection attempted to {address} during test execution!")

    with patch.object(socket.socket, "connect", guarded_connect):
        yield


@pytest.fixture(name="sample_course")
def fixture_sample_course(db_session: Session) -> Subject:
    """Register CS101 with professor mapping."""
    sub = Subject(code="CS101", name="Python Programming")
    db_session.add(sub)
    db_session.flush()

    prof = ProfessorMapping(
        subject_id=sub.id,
        professor_name="Dr. Alan Turing",
        professor_email="turing@university.edu",
        google_chat_space="spaces/CS101",
    )
    db_session.add(prof)
    db_session.commit()
    db_session.refresh(sub)
    return sub


def test_portal_attendance_to_decision_pipeline(
    db_session: Session,
    sample_course: Subject,
):
    """End-to-end integration: Playwright parsed results evaluated through DecisionEngine and NotificationService."""
    target_date = date(2026, 9, 27)

    # 1. Student confirmed attendance for today
    conf = AttendanceConfirmation(date=target_date, note="Attended CS101")
    db_session.add(conf)
    db_session.commit()

    # 2. Mock Playwright adapter extracting an explicit, reliable ABSENT record
    cfg = PlaywrightPortalConfig(portal_url="https://portal.university.edu/attendance")
    mock_bm = MagicMock(spec=PlaywrightBrowserManager)
    mock_page = MagicMock()

    # Table with 1 row: CS101 - Absent
    table_loc = MagicMock()
    table_loc.count.return_value = 1
    row_loc = MagicMock()
    row_loc.locator.return_value.all_inner_texts.return_value = ["CS101", "Python Programming", "Absent"]

    rows_loc = MagicMock()
    rows_loc.count.return_value = 1
    rows_loc.nth.return_value = row_loc

    def mock_locator(sel):
        if "table" in sel and "tr" not in sel:
            return table_loc
        if "tbody tr" in sel:
            return rows_loc
        loc = MagicMock()
        loc.count.return_value = 0
        return loc

    mock_page.locator.side_effect = mock_locator
    mock_bm.get_page.return_value = mock_page

    adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
    attendance_records = adapter.get_attendance_for_date(target_date)

    assert len(attendance_records) == 1
    record = attendance_records[0]
    assert record.subject_code == "CS101"
    assert record.status == AttendanceStatus.ABSENT
    assert record.is_reliable is True

    # 3. Evaluate Decision Engine with real adapter output
    engine = DecisionEngine()
    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=record.subject_code,
        status=record.status,
        is_reliable=record.is_reliable,
    )

    # Invariant holds: Confirmed + Reliable Absent + Valid Mapping + Not Notified = ELIGIBLE
    assert decision.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert decision.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert decision.professor_email == "turing@university.edu"

    # 4. Process through NotificationService with DryRun provider (safe default)
    dry_run_provider = DryRunNotificationProvider()
    service = NotificationService(provider=dry_run_provider, db=db_session, student_name="Alice")

    outcome = service.process_decision(decision)
    assert outcome is not None
    assert outcome.success is True
    assert outcome.is_dry_run is True

    # Notification event recorded as SKIPPED (dry run)
    event = db_session.query(NotificationEvent).filter(NotificationEvent.subject_code == "CS101").first()
    assert event is not None
    assert event.status == NotificationStatus.SKIPPED
    assert event.dry_run is True

    # Audit log recorded
    audit = db_session.query(AuditEvent).filter(AuditEvent.event_type == AuditEventType.NOTIFICATION).first()
    assert audit is not None
    assert audit.action == "NOTIFICATION_DRY_RUN"


def test_unreliable_portal_absence_fails_closed(
    db_session: Session,
    sample_course: Subject,
):
    """When portal status contains an ambiguity keyword, decision engine MUST fail closed."""
    target_date = date(2026, 9, 27)

    # Confirmed day
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    # Unreliable absence
    engine = DecisionEngine()
    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=False,  # Unreliable
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT

    # NotificationService skips
    dry_run = DryRunNotificationProvider()
    service = NotificationService(provider=dry_run, db=db_session)
    outcome = service.process_decision(decision)
    assert outcome is None


def test_portal_present_requires_no_action(
    db_session: Session,
    sample_course: Subject,
):
    """When portal status is PRESENT, decision engine must be NO_ACTION."""
    target_date = date(2026, 9, 27)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code="CS101",
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.STATUS_PRESENT


def test_unconfirmed_absence_requires_no_action(
    db_session: Session,
    sample_course: Subject,
):
    """If the student did NOT confirm attendance, absence on portal must NOT trigger notification."""
    target_date = date(2026, 9, 27)
    # No confirmation record added!

    engine = DecisionEngine()
    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED
