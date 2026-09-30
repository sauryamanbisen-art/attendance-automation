"""Integration tests connecting PWIOIPortalAdapter to the Decision Engine and Notification pipeline."""

import uuid
from datetime import date
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.base.adapter import SubjectAttendance
from app.adapters.pwioi.adapter import PWIOIPortalAdapter
from app.adapters.pwioi.config import PWIOIPortalConfig
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
from app.notifications.base import NotificationPayload
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


class TestPWIOIDecisionPipeline:
    """Prove that PWIOIPortalAdapter outputs feed cleanly into the Decision Engine."""

    TARGET_DATE = date(2026, 8, 4)

    def test_pwioi_reliable_absent_confirmed_day_is_eligible(self, db_session: Session):
        """Invariant: Confirmed + Reliable PWIOI Absent + Valid Prof + Not Notified = ELIGIBLE."""
        # Setup student confirmation
        conf = AttendanceConfirmation(date=self.TARGET_DATE, confirmed_at=None)
        db_session.add(conf)

        subj = Subject(code="302OPS", name="Operating System")
        db_session.add(subj)
        db_session.flush()

        # Setup professor and subject mapping
        prof = ProfessorMapping(subject_id=subj.id, professor_name="Dr. Smith", professor_email="smith@college.edu")
        db_session.add(prof)
        db_session.commit()

        # Simulate PWIOI adapter output
        pwioi_records = [
            SubjectAttendance(
                subject_code="302OPS",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
                subject_name="Operating System",
                raw_status="period 1: ABSENT",
                metadata={"periods": [{"period": "period 1", "status": "ABSENT"}], "academic_term": "3"},
            )
        ]

        engine = DecisionEngine()
        rec = pwioi_records[0]
        decision = engine.evaluate_subject_record(
            db=db_session,
            target_date=self.TARGET_DATE,
            subject_code=rec.subject_code,
            status=rec.status,
            is_reliable=rec.is_reliable,
        )

        assert decision.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
        assert decision.reason == DecisionReason.ABSENT_AND_CONFIRMED
        assert decision.is_eligible is True
        assert decision.professor_email == "smith@college.edu"

        # Dispatch via NotificationService in dry-run mode
        dry_run = DryRunNotificationProvider()
        notif_service = NotificationService(provider=dry_run, db=db_session)
        outcome = notif_service.process_decision(decision)

        assert outcome is not None
        assert outcome.success is True
        assert outcome.is_dry_run is True

        # Notification event recorded as SKIPPED (dry-run)
        event = db_session.query(NotificationEvent).filter(NotificationEvent.subject_code == "302OPS").first()
        assert event is not None
        assert event.status == NotificationStatus.SKIPPED
        assert event.dry_run is True

    def test_pwioi_present_is_no_action(self, db_session: Session):
        """When PWIOI marks student PRESENT, DecisionEngine yields NO_ACTION."""
        conf = AttendanceConfirmation(date=self.TARGET_DATE, confirmed_at=None)
        db_session.add(conf)
        subj = Subject(code="302OPS", name="Operating System")
        db_session.add(subj)
        db_session.flush()
        prof = ProfessorMapping(subject_id=subj.id, professor_name="Dr. Smith", professor_email="smith@college.edu")
        db_session.add(prof)
        db_session.commit()

        engine = DecisionEngine()
        decision = engine.evaluate_subject_record(
            db=db_session,
            target_date=self.TARGET_DATE,
            subject_code="302OPS",
            status=AttendanceStatus.PRESENT,
            is_reliable=True,
        )

        assert decision.action == DecisionAction.NO_ACTION
        assert decision.reason == DecisionReason.STATUS_PRESENT
        assert decision.is_eligible is False

    def test_pwioi_unreliable_unknown_fails_closed(self, db_session: Session):
        """When PWIOI marks student UNKNOWN or unreliable, DecisionEngine fails closed."""
        conf = AttendanceConfirmation(date=self.TARGET_DATE, confirmed_at=None)
        db_session.add(conf)
        subj = Subject(code="302OPS", name="Operating System")
        db_session.add(subj)
        db_session.flush()
        prof = ProfessorMapping(subject_id=subj.id, professor_name="Dr. Smith", professor_email="smith@college.edu")
        db_session.add(prof)
        db_session.commit()

        engine = DecisionEngine()
        decision = engine.evaluate_subject_record(
            db=db_session,
            target_date=self.TARGET_DATE,
            subject_code="302OPS",
            status=AttendanceStatus.UNKNOWN,
            is_reliable=False,
        )

        assert decision.action == DecisionAction.NO_ACTION
        assert decision.reason == DecisionReason.STATUS_UNKNOWN
        assert decision.is_eligible is False

    def test_pwioi_unconfirmed_day_fails_closed(self, db_session: Session):
        """If the student did not confirm attendance for the day, PWIOI ABSENT yields NO_ACTION."""
        subj = Subject(code="302OPS", name="Operating System")
        db_session.add(subj)
        db_session.flush()
        prof = ProfessorMapping(subject_id=subj.id, professor_name="Dr. Smith", professor_email="smith@college.edu")
        db_session.add(prof)
        db_session.commit()

        engine = DecisionEngine()
        decision = engine.evaluate_subject_record(
            db=db_session,
            target_date=self.TARGET_DATE,
            subject_code="302OPS",
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
        )

        assert decision.action == DecisionAction.NO_ACTION
        assert decision.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED
        assert decision.is_eligible is False
