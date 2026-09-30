"""Safety and invariant tests for Gmail notification provider and DecisionEngine integration."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.base import NotificationOutcome, NotificationPayload
from app.notifications.gmail.client import GmailClient
from app.notifications.gmail.config import GmailConfig
from app.notifications.gmail.provider import GmailNotificationProvider
from app.notifications.service import NotificationService
from app.services.decision_engine import DecisionEngine, DecisionResult


@pytest.fixture
def sample_subject(db_session: Session) -> Subject:
    """Create test subject with assigned professor."""
    subj = Subject(code="CS202", name="Operating Systems")
    db_session.add(subj)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subj.id,
        professor_name="Prof. Linus Torvalds",
        professor_email="linus@university.edu",
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(subj)
    return subj


@pytest.fixture
def mock_gmail_client() -> MagicMock:
    client = MagicMock(spec=GmailClient)
    client.config = GmailConfig(client_id="cid", client_secret="csec")
    client.send_email.return_value = {"id": "test_msg_id_123"}
    return client


def test_gmail_never_called_when_decision_is_present(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """When student is PRESENT, DecisionEngine returns NO_ACTION and Gmail provider is never called."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.STATUS_PRESENT

    outcome = service.process_decision(decision)
    assert outcome is None
    mock_gmail_client.send_email.assert_not_called()


def test_gmail_never_called_when_attendance_is_unknown(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """When attendance status is UNKNOWN, fail-closed: NO_ACTION and no Gmail sent."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.UNKNOWN,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.STATUS_UNKNOWN

    outcome = service.process_decision(decision)
    assert outcome is None
    mock_gmail_client.send_email.assert_not_called()


def test_gmail_never_called_when_unconfirmed(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """When student has not confirmed attendance, NO_ACTION and no Gmail sent."""
    target_date = date(2026, 9, 29)
    # Note: NO AttendanceConfirmation added to DB

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED

    outcome = service.process_decision(decision)
    assert outcome is None
    mock_gmail_client.send_email.assert_not_called()


def test_gmail_never_called_when_unreliable(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """When data is unreliable, fail-closed: NO_ACTION and no Gmail sent."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=False,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT

    outcome = service.process_decision(decision)
    assert outcome is None
    mock_gmail_client.send_email.assert_not_called()


def test_gmail_never_called_when_missing_professor_mapping(
    db_session: Session,
    mock_gmail_client: MagicMock,
):
    """When professor email is not configured, NO_ACTION and no Gmail sent."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    unmapped_subj = Subject(code="UNMAPPED101", name="Unmapped Course")
    db_session.add(unmapped_subj)
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=unmapped_subj.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )

    assert decision.action == DecisionAction.NO_ACTION
    assert decision.reason == DecisionReason.MISSING_PROFESSOR_MAPPING

    outcome = service.process_decision(decision)
    assert outcome is None
    mock_gmail_client.send_email.assert_not_called()


def test_gmail_duplicate_notification_blocked(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """Once a notification is dispatched, second attempt on the same date is blocked by DecisionEngine."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=False)
    service = NotificationService(provider=provider, db=db_session)

    # 1. First evaluation is ELIGIBLE
    d1 = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert d1.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION

    outcome1 = service.process_decision(d1)
    assert outcome1 is not None
    assert outcome1.success is True
    assert mock_gmail_client.send_email.call_count == 1

    # 2. Second evaluation on same date is blocked as ALREADY_NOTIFIED
    d2 = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert d2.action == DecisionAction.NO_ACTION
    assert d2.reason == DecisionReason.ALREADY_NOTIFIED

    outcome2 = service.process_decision(d2)
    assert outcome2 is None
    # Gmail API call count remains 1 — second call NEVER happened
    assert mock_gmail_client.send_email.call_count == 1


def test_gmail_dry_run_mode_blocks_sending(
    db_session: Session,
    sample_subject: Subject,
    mock_gmail_client: MagicMock,
):
    """In dry-run mode, NotificationService processes decision, records SKIPPED event, but NEVER calls API."""
    target_date = date(2026, 9, 29)
    db_session.add(AttendanceConfirmation(date=target_date))
    db_session.commit()

    engine = DecisionEngine()
    provider = GmailNotificationProvider(client=mock_gmail_client, is_dry_run=True)
    service = NotificationService(provider=provider, db=db_session)

    decision = engine.evaluate_subject_record(
        db=db_session,
        target_date=target_date,
        subject_code=sample_subject.code,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert decision.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION

    outcome = service.process_decision(decision)
    assert outcome is not None
    assert outcome.success is True
    assert outcome.is_dry_run is True
    mock_gmail_client.send_email.assert_not_called()

    # Event in DB recorded as SKIPPED
    event = (
        db_session.query(NotificationEvent)
        .filter(
            NotificationEvent.subject_code == sample_subject.code,
            NotificationEvent.date == target_date,
        )
        .first()
    )
    assert event is not None
    assert event.status == NotificationStatus.SKIPPED
    assert event.dry_run is True
