"""Unit tests for the daily check scheduler orchestrator and CLI runner."""

import os
from datetime import date, datetime, time, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.config import Settings
from app.core.enums import AttendanceStatus, AuditEventType, CheckStatus, DecisionAction, DecisionReason
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.attendance_result import AttendanceResult
from app.models.audit_event import AuditEvent
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.dry_run import DryRunNotificationProvider
from app.services.confirmation import ConfirmationService
from app.services.daily_scheduler import DailyCheckResult, DailyCheckRunner
from scripts.run_daily_check import format_summary, main, parse_args


@pytest.fixture
def tz_kolkata() -> ZoneInfo:
    return ZoneInfo("Asia/Kolkata")


@pytest.fixture
def scheduler_settings() -> Settings:
    return Settings(
        timezone="Asia/Kolkata",
        cutoff_time="16:00",
        dry_run=True,
        portal_adapter="fake",
    )


class TestCutoffEnforcement:
    """Verifies that cutoff time rules are strictly enforced."""

    def test_before_cutoff_skips_execution(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        # 15:30 is before 16:00 cutoff
        check_time = datetime(2026, 9, 28, 15, 30, tzinfo=tz_kolkata)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            ignore_cutoff=False,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "BEFORE_CUTOFF_TIME"
        assert result.subjects_checked == 0

        # Check audit event
        audit = (
            db_session.query(AuditEvent)
            .filter(AuditEvent.action == "SCHEDULER_SKIPPED")
            .first()
        )
        assert audit is not None
        assert audit.details["reason"] == "BEFORE_CUTOFF_TIME"

    def test_before_cutoff_with_ignore_cutoff_flag_proceeds(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 15, 30, tzinfo=tz_kolkata)

        # Confirm attendance so it doesn't skip at confirmation stage
        ConfirmationService(db_session).confirm_attendance(test_date)

        adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_PRESENT)
        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            ignore_cutoff=True,
            adapter=adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked > 0

    def test_after_cutoff_proceeds(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        # 16:05 is after 16:00 cutoff
        check_time = datetime(2026, 9, 28, 16, 5, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date)

        adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_PRESENT)
        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            ignore_cutoff=False,
            adapter=adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked > 0

    def test_future_date_skips_execution(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        check_time = datetime(2026, 9, 28, 17, 0, tzinfo=tz_kolkata)
        future_date = date(2026, 9, 29)

        result = runner.run_daily_check(
            target_date=future_date,
            current_time=check_time,
            ignore_cutoff=False,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "FUTURE_DATE"

    def test_malformed_cutoff_string_falls_back_to_1600(
        self, db_session: Session, tz_kolkata: ZoneInfo
    ):
        bad_settings = Settings(cutoff_time="invalid_time", timezone="Asia/Kolkata")
        runner = DailyCheckRunner(db=db_session, settings=bad_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 15, 45, tzinfo=tz_kolkata)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            ignore_cutoff=False,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "BEFORE_CUTOFF_TIME"


class TestConfirmationGate:
    """Verifies that unconfirmed attendance exits safely with NO_ACTION."""

    def test_unconfirmed_attendance_skips_portal_check(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        # Mock adapter to ensure it is never called
        mock_adapter = MagicMock(spec=BasePortalAdapter)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "ATTENDANCE_NOT_CONFIRMED"
        mock_adapter.authenticate.assert_not_called()
        mock_adapter.get_attendance_for_date.assert_not_called()

        # Audit event recorded
        audit = (
            db_session.query(AuditEvent)
            .filter(
                AuditEvent.action == "SCHEDULER_SKIPPED",
            )
            .first()
        )
        assert audit is not None
        assert audit.details["reason"] == "ATTENDANCE_NOT_CONFIRMED"

    def test_confirmed_attendance_executes_portal_check(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date)

        adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_PRESENT)
        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked > 0


class TestAdapterExecutionAndFailClosed:
    """Verifies fail-closed behavior on portal adapter failures."""

    def test_portal_network_error_fails_closed_and_closes_resources(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date)

        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_failing_adapter"
        mock_adapter.get_attendance_for_date.side_effect = RuntimeError("Portal timeout: Bearer token_secret_123")

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "FAILED"
        assert "Portal timeout" in result.error_message
        # Verify secret was redacted
        assert "token_secret_123" not in result.error_message
        assert "[REDACTED" in result.error_message

        # Verify close was invoked
        mock_adapter.close.assert_called_once()

        # Verify DB check record was marked FAILED
        check_record = (
            db_session.query(AttendanceCheck)
            .filter(AttendanceCheck.run_id == result.run_id)
            .first()
        )
        assert check_record is not None
        assert check_record.status == CheckStatus.FAILED

        # Verify audit event
        audit = (
            db_session.query(AuditEvent)
            .filter(AuditEvent.action == "SCHEDULER_FAILED")
            .first()
        )
        assert audit is not None
        assert audit.details["adapter"] == "test_failing_adapter"


class TestDiscrepancyEvaluationAndDryRun:
    """Verifies decision evaluation and notification integration."""

    def test_discrepancy_evaluated_and_dry_run_dispatched(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        # 1. Setup subject and professor mapping
        subj = Subject(code="CS101", name="Python Programming")
        db_session.add(subj)
        db_session.flush()

        mapping = ProfessorMapping(
            subject_id=subj.id,
            professor_name="Prof. Turing",
            professor_email="turing@example.edu",
        )
        db_session.add(mapping)

        # 2. Confirm student attendance
        ConfirmationService(db_session).confirm_attendance(test_date)

        # 3. Use Fake adapter with PYTHON_ABSENT scenario (CS101 is ABSENT)
        adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_ABSENT)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=adapter,
            dry_run=True,
        )

        assert result.status == "SUCCESS"
        assert result.eligible_count == 1
        assert result.notifications_sent == 1
        assert result.dry_run is True

        # NotificationEvent recorded in DB with SKIPPED status (dry-run)
        notif_event = (
            db_session.query(NotificationEvent)
            .filter(
                NotificationEvent.date == test_date,
                NotificationEvent.subject_id == subj.id,
            )
            .first()
        )
        assert notif_event is not None
        assert notif_event.dry_run is True

    def test_duplicate_run_is_safe_and_does_not_duplicate_notification(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        subj = Subject(code="CS101", name="Python Programming")
        db_session.add(subj)
        db_session.flush()

        mapping = ProfessorMapping(
            subject_id=subj.id,
            professor_name="Prof. Turing",
            professor_email="turing@example.edu",
        )
        db_session.add(mapping)
        ConfirmationService(db_session).confirm_attendance(test_date)

        # Run 1: Should find discrepancy and record notification
        adapter1 = FakePortalAdapter(scenario=FakeScenario.PYTHON_ABSENT)
        result1 = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=adapter1,
            dry_run=True,
        )
        assert result1.eligible_count == 1
        assert result1.notifications_sent == 1

        # Run 2: Exact duplicate run on the same date
        adapter2 = FakePortalAdapter(scenario=FakeScenario.PYTHON_ABSENT)
        result2 = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=adapter2,
            dry_run=True,
        )
        assert result2.status == "SUCCESS"
        # Decision engine evaluates to ALREADY_NOTIFIED -> eligible_count is 0!
        assert result2.eligible_count == 0
        assert result2.notifications_sent == 0

        # Only one NotificationEvent exists in the database
        notif_count = (
            db_session.query(NotificationEvent)
            .filter(
                NotificationEvent.date == test_date,
                NotificationEvent.subject_id == subj.id,
            )
            .count()
        )
        assert notif_count == 1

    def test_unreliable_or_unknown_attendance_produces_no_action(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 28)
        check_time = datetime(2026, 9, 28, 16, 30, tzinfo=tz_kolkata)

        subj = Subject(code="CS101", name="Python Programming")
        db_session.add(subj)
        db_session.flush()
        ConfirmationService(db_session).confirm_attendance(test_date)

        # UNRELIABLE_ABSENT scenario
        adapter = FakePortalAdapter(scenario=FakeScenario.UNRELIABLE_ABSENT)
        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=adapter,
        )

        assert result.status == "SUCCESS"
        assert result.eligible_count == 0
        assert result.notifications_sent == 0


class TestCLIRunner:
    """Verifies scripts/run_daily_check.py argument parsing and entrypoint."""

    def test_parse_args_defaults(self):
        args = parse_args([])
        assert args.date is None
        assert args.ignore_cutoff is False
        assert args.dry_run is None
        assert args.adapter is None
        assert args.verbose is False

    def test_parse_args_explicit_options(self):
        args = parse_args([
            "--date", "2026-09-28",
            "--ignore-cutoff",
            "--dry-run",
            "--adapter", "pwioi",
            "--verbose",
        ])
        assert args.date == date(2026, 9, 28)
        assert args.ignore_cutoff is True
        assert args.dry_run is True
        assert args.adapter == "pwioi"
        assert args.verbose is True

    def test_parse_args_live_flag(self):
        args = parse_args(["--live"])
        assert args.dry_run is False

    def test_format_summary_success(self):
        res = DailyCheckResult(
            run_id="run-123",
            target_date=date(2026, 9, 28),
            status="SUCCESS",
            subjects_checked=3,
            eligible_count=1,
            notifications_sent=1,
            dry_run=True,
        )
        summary = format_summary(res)
        assert "Run ID:            run-123" in summary
        assert "Status:            SUCCESS" in summary
        assert "Subjects Checked:  3" in summary
        assert "Dry Run:           True" in summary

    def test_format_summary_skipped(self):
        res = DailyCheckResult(
            run_id="run-456",
            target_date=date(2026, 9, 28),
            status="SKIPPED",
            reason="BEFORE_CUTOFF_TIME",
            dry_run=True,
        )
        summary = format_summary(res)
        assert "Status:            SKIPPED" in summary
        assert "Reason:            BEFORE_CUTOFF_TIME" in summary

    @patch("scripts.run_daily_check.DailyCheckRunner")
    def test_main_cli_returns_zero_on_success(self, mock_runner_cls):
        mock_runner = MagicMock()
        mock_runner.run_daily_check.return_value = DailyCheckResult(
            run_id="run-cli",
            target_date=date(2026, 9, 28),
            status="SUCCESS",
            subjects_checked=2,
            dry_run=True,
        )
        mock_runner_cls.return_value = mock_runner

        exit_code = main(["--ignore-cutoff", "--adapter", "fake"])
        assert exit_code == 0

    @patch("scripts.run_daily_check.DailyCheckRunner")
    def test_main_cli_returns_one_on_failure(self, mock_runner_cls):
        mock_runner = MagicMock()
        mock_runner.run_daily_check.return_value = DailyCheckResult(
            run_id="run-cli-fail",
            target_date=date(2026, 9, 28),
            status="FAILED",
            error_message="Portal session expired",
            dry_run=True,
        )
        mock_runner_cls.return_value = mock_runner

        exit_code = main(["--ignore-cutoff"])
        assert exit_code == 1


class TestWeekdayAndWeekendScheduling:
    """Verifies that scheduling rules apply equally to weekdays, Saturdays, and Sundays.

    The explicit student attendance confirmation ('I WENT TO COLLEGE') is the primary
    safety gate. Weekends are never assumed to be free of classes, and unconfirmed
    days are always safely skipped.
    """

    def test_confirmed_weekday_portal_check_allowed(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        # Wednesday (weekday == 2)
        test_date = date(2026, 9, 23)
        assert test_date.weekday() < 5, "Date must be a weekday"
        check_time = datetime(2026, 9, 23, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date)

        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_adapter"
        mock_adapter.get_attendance_for_date.return_value = [
            SubjectAttendance(
                subject_code="CS101",
                subject_name="Python",
                status=AttendanceStatus.PRESENT,
                raw_status="Present",
                is_reliable=True,
            )
        ]

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked == 1
        mock_adapter.get_attendance_for_date.assert_called_once_with(test_date)

    def test_unconfirmed_weekday_skipped(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 23)
        assert test_date.weekday() < 5, "Date must be a weekday"
        check_time = datetime(2026, 9, 23, 16, 30, tzinfo=tz_kolkata)

        mock_adapter = MagicMock(spec=BasePortalAdapter)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "ATTENDANCE_NOT_CONFIRMED"
        mock_adapter.get_attendance_for_date.assert_not_called()

    def test_confirmed_saturday_portal_check_allowed(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        # Saturday (weekday == 5)
        test_date = date(2026, 9, 26)
        assert test_date.weekday() == 5, "Date must be Saturday"
        check_time = datetime(2026, 9, 26, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date, note="Extra Saturday lab")

        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_adapter"
        mock_adapter.get_attendance_for_date.return_value = [
            SubjectAttendance(
                subject_code="CS101",
                subject_name="Python Lab",
                status=AttendanceStatus.PRESENT,
                raw_status="Present",
                is_reliable=True,
            )
        ]

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked == 1
        mock_adapter.get_attendance_for_date.assert_called_once_with(test_date)

    def test_unconfirmed_saturday_skipped(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 26)
        assert test_date.weekday() == 5, "Date must be Saturday"
        check_time = datetime(2026, 9, 26, 16, 30, tzinfo=tz_kolkata)

        mock_adapter = MagicMock(spec=BasePortalAdapter)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "ATTENDANCE_NOT_CONFIRMED"
        mock_adapter.get_attendance_for_date.assert_not_called()

    def test_confirmed_sunday_portal_check_allowed(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        # Sunday (weekday == 6)
        test_date = date(2026, 9, 27)
        assert test_date.weekday() == 6, "Date must be Sunday"
        check_time = datetime(2026, 9, 27, 16, 30, tzinfo=tz_kolkata)

        ConfirmationService(db_session).confirm_attendance(test_date, note="Sunday makeup lecture")

        mock_adapter = MagicMock(spec=BasePortalAdapter)
        mock_adapter.adapter_name = "test_adapter"
        mock_adapter.get_attendance_for_date.return_value = [
            SubjectAttendance(
                subject_code="CS101",
                subject_name="Python",
                status=AttendanceStatus.PRESENT,
                raw_status="Present",
                is_reliable=True,
            )
        ]

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SUCCESS"
        assert result.subjects_checked == 1
        mock_adapter.get_attendance_for_date.assert_called_once_with(test_date)

    def test_unconfirmed_sunday_skipped(
        self, db_session: Session, scheduler_settings: Settings, tz_kolkata: ZoneInfo
    ):
        runner = DailyCheckRunner(db=db_session, settings=scheduler_settings)
        test_date = date(2026, 9, 27)
        assert test_date.weekday() == 6, "Date must be Sunday"
        check_time = datetime(2026, 9, 27, 16, 30, tzinfo=tz_kolkata)

        mock_adapter = MagicMock(spec=BasePortalAdapter)

        result = runner.run_daily_check(
            target_date=test_date,
            current_time=check_time,
            adapter=mock_adapter,
        )

        assert result.status == "SKIPPED"
        assert result.reason == "ATTENDANCE_NOT_CONFIRMED"
        mock_adapter.get_attendance_for_date.assert_not_called()

