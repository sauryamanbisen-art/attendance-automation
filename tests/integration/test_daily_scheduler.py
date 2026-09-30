"""Integration tests for the daily check scheduler orchestration layer."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.config import Settings
from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    CheckStatus,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.attendance_result import AttendanceResult
from app.models.audit_event import AuditEvent
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.services.confirmation import ConfirmationService
from app.services.daily_scheduler import DailyCheckResult, DailyCheckRunner


@pytest.fixture
def tz_kolkata() -> ZoneInfo:
    return ZoneInfo("Asia/Kolkata")


class TestDailySchedulerIntegrationPipeline:
    """End-to-end integration tests for DailyCheckRunner."""

    def test_full_pipeline_multi_subject_discrepancy_and_audit_trail(
        self, db_session: Session, tz_kolkata: ZoneInfo
    ):
        """Verify full lifecycle:

        Confirmation -> Cutoff check -> Portal retrieval -> Decision Engine -> Notification -> Audit
        """
        target_date = date(2026, 9, 28)
        run_time = datetime(2026, 9, 28, 16, 15, tzinfo=tz_kolkata)

        # 1. Create subjects
        # Subj 1: Has professor mapping with email -> will be eligible when absent
        subj1 = Subject(code="CS101", name="Data Structures")
        # Subj 2: Has NO professor mapping -> missing mapping
        subj2 = Subject(code="CS102", name="Computer Networks")
        # Subj 3: Has mapping -> will be marked PRESENT
        subj3 = Subject(code="CS103", name="Operating Systems")
        # Subj 4: Has mapping -> will be marked UNKNOWN/unreliable
        subj4 = Subject(code="CS104", name="Database Systems")

        db_session.add_all([subj1, subj2, subj3, subj4])
        db_session.flush()

        map1 = ProfessorMapping(
            subject_id=subj1.id,
            professor_name="Prof. Alice",
            professor_email="alice@university.edu",
            google_chat_space="spaces/alice_space",
        )
        map3 = ProfessorMapping(
            subject_id=subj3.id,
            professor_name="Prof. Charlie",
            professor_email="charlie@university.edu",
        )
        map4 = ProfessorMapping(
            subject_id=subj4.id,
            professor_name="Prof. Dana",
            professor_email="dana@university.edu",
        )
        db_session.add_all([map1, map3, map4])
        db_session.commit()

        # 2. Student confirms daily attendance
        conf_service = ConfirmationService(db_session)
        conf_record, created = conf_service.confirm_attendance(target_date, note="Attended all lectures")
        assert created is True

        # 3. Setup mock adapter returning diverse records
        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_portal_adapter"
        mock_adapter.get_attendance_for_date.return_value = [
            SubjectAttendance(
                subject_code="CS101",
                subject_name="Data Structures",
                status=AttendanceStatus.ABSENT,
                raw_status="Absent",
                is_reliable=True,
            ),
            SubjectAttendance(
                subject_code="CS102",
                subject_name="Computer Networks",
                status=AttendanceStatus.ABSENT,
                raw_status="Absent",
                is_reliable=True,
            ),
            SubjectAttendance(
                subject_code="CS103",
                subject_name="Operating Systems",
                status=AttendanceStatus.PRESENT,
                raw_status="Present",
                is_reliable=True,
            ),
            SubjectAttendance(
                subject_code="CS104",
                subject_name="Database Systems",
                status=AttendanceStatus.UNKNOWN,
                raw_status="Not Marked",
                is_reliable=False,
            ),
        ]

        settings = Settings(
            timezone="Asia/Kolkata",
            cutoff_time="16:00",
            dry_run=True,
        )
        runner = DailyCheckRunner(db=db_session, settings=settings)

        # 4. Execute scheduled check
        result = runner.run_daily_check(
            target_date=target_date,
            current_time=run_time,
            ignore_cutoff=False,
            adapter=mock_adapter,
            dry_run=True,
        )

        # 5. Verify results
        assert result.status == "SUCCESS"
        assert result.subjects_checked == 4
        assert result.eligible_count == 1  # Only CS101 is eligible
        assert result.notifications_sent == 1
        assert result.dry_run is True

        # Verify decisions list
        decision_map = {d.subject_code: d for d in result.decisions}
        assert decision_map["CS101"].action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
        assert decision_map["CS101"].reason == DecisionReason.ABSENT_AND_CONFIRMED

        assert decision_map["CS102"].action == DecisionAction.NO_ACTION
        assert decision_map["CS102"].reason == DecisionReason.MISSING_PROFESSOR_MAPPING

        assert decision_map["CS103"].action == DecisionAction.NO_ACTION
        assert decision_map["CS103"].reason == DecisionReason.STATUS_PRESENT

        assert decision_map["CS104"].action == DecisionAction.NO_ACTION
        assert decision_map["CS104"].reason == DecisionReason.STATUS_UNKNOWN

        # 6. Verify database records
        # AttendanceCheck
        check = (
            db_session.query(AttendanceCheck)
            .filter(AttendanceCheck.run_id == result.run_id)
            .first()
        )
        assert check is not None
        assert check.status == CheckStatus.SUCCESS

        # AttendanceResults
        db_results = (
            db_session.query(AttendanceResult)
            .filter(AttendanceResult.check_id == check.id)
            .all()
        )
        assert len(db_results) == 4

        # NotificationEvent: Exactly 1 event created for CS101
        notif_events = (
            db_session.query(NotificationEvent)
            .filter(NotificationEvent.date == target_date)
            .all()
        )
        assert len(notif_events) == 1
        assert notif_events[0].subject_code == "CS101"
        assert notif_events[0].dry_run is True
        assert notif_events[0].status == NotificationStatus.SKIPPED

        # Audit events: Verify complete audit trail
        audit_actions = [
            a.action
            for a in db_session.query(AuditEvent)
            .filter(AuditEvent.run_id == result.run_id)
            .all()
        ]
        assert "SCHEDULER_START" in audit_actions
        assert "SCHEDULER_COMPLETED" in audit_actions

        # 7. Execute DUPLICATE run: verify idempotency and zero duplicate notifications
        result2 = runner.run_daily_check(
            target_date=target_date,
            current_time=run_time,
            ignore_cutoff=False,
            adapter=mock_adapter,
            dry_run=True,
        )
        assert result2.status == "SUCCESS"
        assert result2.eligible_count == 0  # CS101 is now ALREADY_NOTIFIED
        assert result2.notifications_sent == 0

        # Verify still only 1 NotificationEvent
        total_notifs = (
            db_session.query(NotificationEvent)
            .filter(NotificationEvent.date == target_date)
            .count()
        )
        assert total_notifs == 1

    def test_pwioi_adapter_unauthenticated_fails_closed_safely(
        self, db_session: Session, tz_kolkata: ZoneInfo
    ):
        """Verify that selecting pwioi adapter in headless mode without session fails closed safely."""
        target_date = date(2026, 9, 28)
        run_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(target_date)

        # Configure pwioi adapter pointing to non-existent storage state
        settings = Settings(
            timezone="Asia/Kolkata",
            cutoff_time="16:00",
            portal_adapter="pwioi",
            pwioi_storage_state="storage_state/non_existent_session.json",
            portal_headless=True,
        )
        runner = DailyCheckRunner(db=db_session, settings=settings)

        result = runner.run_daily_check(
            target_date=target_date,
            current_time=run_time,
            adapter_name="pwioi",
        )

        assert result.status == "FAILED"
        assert (
            "session storage" in result.error_message.lower()
            or "authenticate" in result.error_message.lower()
            or "browser" in result.error_message.lower()
        )

        # Verify audit event for failure was logged
        audit = (
            db_session.query(AuditEvent)
            .filter(
                AuditEvent.run_id == result.run_id,
                AuditEvent.action == "SCHEDULER_FAILED",
            )
            .first()
        )
        assert audit is not None
        assert audit.details["adapter"] == "pwioi"

    def test_pipeline_holiday_and_cancellation_prevent_notifications(
        self, db_session: Session, tz_kolkata: ZoneInfo
    ):
        """Verify that holidays and cancelled classes prevent notifications in DailyCheckRunner."""
        from app.models.calendar import ClassException, ExceptionType, Holiday

        target_date = date(2026, 10, 2)
        run_time = datetime(2026, 10, 2, 16, 30, tzinfo=tz_kolkata)

        # 1. Subject with professor mapping and student confirmation
        subj = Subject(code="CS301", name="Software Engineering")
        db_session.add(subj)
        db_session.flush()

        mapping = ProfessorMapping(
            subject_id=subj.id,
            professor_name="Prof. Somervell",
            professor_email="somervell@univ.edu",
        )
        db_session.add(mapping)
        db_session.commit()

        ConfirmationService(db_session).confirm_attendance(target_date)

        # Declare today as Holiday
        holiday = Holiday(date=target_date, description="National Holiday")
        db_session.add(holiday)
        db_session.commit()

        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_adapter"
        mock_adapter.get_attendance_for_date.return_value = [
            SubjectAttendance(
                subject_code="CS301",
                subject_name="Software Engineering",
                status=AttendanceStatus.ABSENT,
                raw_status="Absent",
                is_reliable=True,
            )
        ]

        settings = Settings(timezone="Asia/Kolkata", cutoff_time="16:00", dry_run=True)
        runner = DailyCheckRunner(db=db_session, settings=settings)

        # Case A: Holiday -> NO_ACTION, reason: HOLIDAY, no notifications sent
        result = runner.run_daily_check(
            target_date=target_date,
            current_time=run_time,
            adapter=mock_adapter,
        )
        assert result.status == "SUCCESS"
        assert result.eligible_count == 0
        assert result.notifications_sent == 0
        assert result.decisions[0].action == DecisionAction.NO_ACTION
        assert result.decisions[0].reason == DecisionReason.HOLIDAY

        # Verify no NotificationEvent in DB
        events = db_session.query(NotificationEvent).filter(NotificationEvent.date == target_date).all()
        assert len(events) == 0

        # Case B: Remove holiday, add CANCELLED exception -> NO_ACTION, reason: CLASS_CANCELLED
        db_session.delete(holiday)
        cancel_exc = ClassException(
            subject_id=subj.id,
            date=target_date,
            exception_type=ExceptionType.CANCELLED,
        )
        db_session.add(cancel_exc)
        db_session.commit()

        result_cancel = runner.run_daily_check(
            target_date=target_date,
            current_time=run_time,
            adapter=mock_adapter,
        )
        assert result_cancel.status == "SUCCESS"
        assert result_cancel.eligible_count == 0
        assert result_cancel.notifications_sent == 0
        assert result_cancel.decisions[0].action == DecisionAction.NO_ACTION
        assert result_cancel.decisions[0].reason == DecisionReason.CLASS_CANCELLED

