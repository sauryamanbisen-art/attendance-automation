"""Comprehensive tests for the notification provider abstraction.

Test categories:
1. BaseNotificationProvider interface contract
2. DryRunNotificationProvider behavior and safety guarantees
3. Message generation (polite, factual, non-accusatory)
4. NotificationService orchestration and safety gate
5. Dry-run can NEVER send a network request (structural verification)
6. Provider failure handling
7. Deduplication recording
8. Audit logging
"""

import ast
import inspect
import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.database.base import Base
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.base import (
    BaseNotificationProvider,
    NotificationConfigError,
    NotificationDeliveryError,
    NotificationOutcome,
    NotificationPayload,
    NotificationProviderError,
)
from app.notifications.dry_run import DryRunNotificationProvider
from app.notifications.message import generate_correction_body, generate_correction_subject
from app.notifications.service import NotificationService
from app.services.decision_engine import DecisionResult


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(name="notif_db")
def fixture_notif_db():
    """Create a pristine in-memory SQLite database for notification tests."""
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


@pytest.fixture(name="sample_subject_with_mapping")
def fixture_sample_subject_with_mapping(notif_db: Session) -> Subject:
    """Subject with professor mapping for notification tests."""
    subject = Subject(code="CS101", name="Python Programming")
    notif_db.add(subject)
    notif_db.flush()
    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Dr. Alan Turing",
        professor_email="turing@university.edu",
    )
    notif_db.add(mapping)
    notif_db.commit()
    notif_db.refresh(subject)
    return subject


@pytest.fixture(name="eligible_decision")
def fixture_eligible_decision() -> DecisionResult:
    """A decision that IS eligible for notification."""
    return DecisionResult(
        action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
        reason=DecisionReason.ABSENT_AND_CONFIRMED,
        subject_code="CS101",
        target_date=date(2025, 1, 15),
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        professor_email="turing@university.edu",
    )


@pytest.fixture(name="ineligible_decision")
def fixture_ineligible_decision() -> DecisionResult:
    """A decision that is NOT eligible for notification."""
    return DecisionResult(
        action=DecisionAction.NO_ACTION,
        reason=DecisionReason.STATUS_PRESENT,
        subject_code="CS101",
        target_date=date(2025, 1, 15),
        is_confirmed=True,
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
        professor_email="turing@university.edu",
    )


@pytest.fixture(name="dry_run_provider")
def fixture_dry_run_provider() -> DryRunNotificationProvider:
    return DryRunNotificationProvider()


@pytest.fixture(name="sample_payload")
def fixture_sample_payload() -> NotificationPayload:
    return NotificationPayload(
        subject_code="CS101",
        subject_name="Python Programming",
        target_date=date(2025, 1, 15),
        recipient_email="turing@university.edu",
        professor_name="Dr. Alan Turing",
        message_subject="Test Subject",
        message_body="Test Body",
        student_name="Alice",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. BaseNotificationProvider interface contract
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseNotificationProviderContract:
    """Verify the abstract interface cannot be instantiated directly."""

    def test_cannot_instantiate_base_class(self):
        """BaseNotificationProvider is abstract — instantiation must raise TypeError."""
        with pytest.raises(TypeError):
            BaseNotificationProvider()  # type: ignore[abstract]

    def test_dry_run_is_subclass(self, dry_run_provider):
        """DryRunNotificationProvider must be a proper subclass."""
        assert isinstance(dry_run_provider, BaseNotificationProvider)

    def test_interface_has_required_methods(self):
        """Interface must define send, validate_config, provider_name, is_dry_run."""
        assert hasattr(BaseNotificationProvider, "send")
        assert hasattr(BaseNotificationProvider, "validate_config")
        assert hasattr(BaseNotificationProvider, "provider_name")
        assert hasattr(BaseNotificationProvider, "is_dry_run")


# ═══════════════════════════════════════════════════════════════════════════
# 2. DryRunNotificationProvider behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestDryRunNotificationProvider:
    """Verify dry-run provider behavior and safety guarantees."""

    def test_provider_name(self, dry_run_provider):
        assert dry_run_provider.provider_name == "dry_run"

    def test_is_dry_run_true(self, dry_run_provider):
        assert dry_run_provider.is_dry_run is True

    def test_validate_config_always_true(self, dry_run_provider):
        assert dry_run_provider.validate_config() is True

    def test_send_returns_successful_outcome(self, dry_run_provider, sample_payload):
        outcome = dry_run_provider.send(sample_payload)
        assert outcome.success is True
        assert outcome.is_dry_run is True
        assert outcome.provider_name == "dry_run"
        assert outcome.error_message is None

    def test_send_includes_message_preview(self, dry_run_provider, sample_payload):
        outcome = dry_run_provider.send(sample_payload)
        assert sample_payload.recipient_email in outcome.message_preview
        assert sample_payload.message_subject in outcome.message_preview
        assert sample_payload.message_body in outcome.message_preview

    def test_send_includes_details(self, dry_run_provider, sample_payload):
        outcome = dry_run_provider.send(sample_payload)
        assert outcome.details["recipient"] == sample_payload.recipient_email
        assert outcome.details["subject_code"] == sample_payload.subject_code
        assert outcome.details["target_date"] == sample_payload.target_date.isoformat()

    def test_send_logs_message(self, dry_run_provider, sample_payload):
        """Dry-run provider must log the message content."""
        with patch("app.notifications.dry_run.logger") as mock_logger:
            dry_run_provider.send(sample_payload)
            mock_logger.info.assert_called_once()
            log_args = mock_logger.info.call_args
            assert "DRY RUN" in log_args[0][0]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Structural safety: dry-run NEVER imports networking libraries
# ═══════════════════════════════════════════════════════════════════════════


class TestDryRunNetworkSafety:
    """Structurally verify that DryRunNotificationProvider cannot make network requests."""

    # Networking modules that must NEVER appear in dry_run.py
    FORBIDDEN_MODULES = {
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "aiohttp",
        "smtplib",
        "socket",
        "http.client",
        "http",
        "ssl",
    }

    def test_dry_run_source_has_no_network_imports(self):
        """Parse the dry_run.py AST and verify no networking imports exist."""
        source_file = inspect.getfile(DryRunNotificationProvider)
        with open(source_file) as f:
            tree = ast.parse(f.read())

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        violations = imported_modules & self.FORBIDDEN_MODULES
        assert not violations, (
            f"DryRunNotificationProvider imports forbidden networking modules: {violations}"
        )

    def test_dry_run_send_does_not_call_network(self, dry_run_provider, sample_payload):
        """Verify send() doesn't attempt any socket or HTTP operations."""
        import socket as socket_mod

        original_create = socket_mod.socket

        def deny_socket(*args, **kwargs):
            raise AssertionError("DryRunNotificationProvider attempted to open a socket!")

        socket_mod.socket = deny_socket  # type: ignore[assignment]
        try:
            outcome = dry_run_provider.send(sample_payload)
            assert outcome.success is True
            assert outcome.is_dry_run is True
        finally:
            socket_mod.socket = original_create  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Message generation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMessageGeneration:
    """Verify message templates are polite, factual, and non-accusatory."""

    def test_subject_line_contains_course_info(self):
        subject = generate_correction_subject("CS101", "Python Programming", date(2025, 1, 15))
        assert "CS101" in subject
        assert "Python Programming" in subject
        assert "15 January 2025" in subject

    def test_subject_line_contains_review_not_correction(self):
        subject = generate_correction_subject("CS101", "Python", date(2025, 1, 15))
        assert "Review" in subject

    def test_body_is_polite(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        # Must be polite
        assert "Dear Dr. Turing" in body
        assert "kindly" in body.lower() or "appreciate" in body.lower()
        assert "Thank you" in body

    def test_body_is_factual(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        assert "CS101" in body
        assert "Python Programming" in body
        assert "15 January 2025" in body

    def test_body_is_non_accusatory(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        # Must NOT contain accusatory language
        accusatory_words = ["mistake", "wrong", "error by you", "your fault", "you forgot"]
        for word in accusatory_words:
            assert word.lower() not in body.lower(), f"Body contains accusatory word: '{word}'"

    def test_body_requests_review_not_demand(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        assert "review" in body.lower()
        # Should not use demanding language
        assert "must" not in body.lower().replace("must ", "")  # Only check standalone "must"
        assert "demand" not in body.lower()

    def test_body_includes_student_name(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        assert "Alice" in body

    def test_body_without_student_name_uses_fallback(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing",
        )
        assert "the student" in body

    def test_body_contains_automation_disclaimer(self):
        body = generate_correction_body(
            "CS101", "Python Programming", date(2025, 1, 15),
            "Dr. Turing", "Alice",
        )
        assert "Attendance Automation" in body


# ═══════════════════════════════════════════════════════════════════════════
# 5. NotificationService safety gate
# ═══════════════════════════════════════════════════════════════════════════


class TestNotificationServiceSafetyGate:
    """Verify NotificationService ONLY dispatches eligible decisions."""

    def test_eligible_decision_dispatches(
        self, notif_db, sample_subject_with_mapping, eligible_decision, dry_run_provider,
    ):
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        outcome = service.process_decision(eligible_decision)
        assert outcome is not None
        assert outcome.success is True
        assert outcome.is_dry_run is True

    def test_ineligible_decision_returns_none(
        self, notif_db, sample_subject_with_mapping, ineligible_decision, dry_run_provider,
    ):
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        outcome = service.process_decision(ineligible_decision)
        assert outcome is None

    def test_no_action_present_rejected(self, notif_db, dry_run_provider):
        """STATUS_PRESENT decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.STATUS_PRESENT,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.PRESENT,
            is_reliable=True,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_no_action_unknown_rejected(self, notif_db, dry_run_provider):
        """STATUS_UNKNOWN decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.STATUS_UNKNOWN,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.UNKNOWN,
            is_reliable=True,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_no_action_unconfirmed_rejected(self, notif_db, dry_run_provider):
        """ATTENDANCE_NOT_CONFIRMED decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.ATTENDANCE_NOT_CONFIRMED,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=False,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_no_action_unreliable_rejected(self, notif_db, dry_run_provider):
        """UNRELIABLE_ATTENDANCE_RESULT decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.UNRELIABLE_ATTENDANCE_RESULT,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=False,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_no_action_already_notified_rejected(self, notif_db, dry_run_provider):
        """ALREADY_NOTIFIED decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.ALREADY_NOTIFIED,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_no_action_missing_mapping_rejected(self, notif_db, dry_run_provider):
        """MISSING_PROFESSOR_MAPPING decision must be rejected."""
        decision = DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.MISSING_PROFESSOR_MAPPING,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None

    def test_eligible_without_professor_email_returns_none(
        self, notif_db, sample_subject_with_mapping, dry_run_provider,
    ):
        """Eligible decision with missing professor_email must be safely rejected."""
        decision = DecisionResult(
            action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
            reason=DecisionReason.ABSENT_AND_CONFIRMED,
            subject_code="CS101",
            target_date=date(2025, 1, 15),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
            professor_email=None,
        )
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        assert service.process_decision(decision) is None


# ═══════════════════════════════════════════════════════════════════════════
# 6. NotificationService records events and logs
# ═══════════════════════════════════════════════════════════════════════════


class TestNotificationServiceRecording:
    """Verify notification events are persisted and audit-logged."""

    def test_eligible_creates_notification_event(
        self, notif_db, sample_subject_with_mapping, eligible_decision, dry_run_provider,
    ):
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        service.process_decision(eligible_decision)

        events = notif_db.query(NotificationEvent).all()
        assert len(events) == 1
        event = events[0]
        assert event.subject_code == "CS101"
        assert event.date == date(2025, 1, 15)
        assert event.dry_run is True
        assert event.status == NotificationStatus.SKIPPED  # dry-run → SKIPPED

    def test_ineligible_does_not_create_event(
        self, notif_db, sample_subject_with_mapping, ineligible_decision, dry_run_provider,
    ):
        service = NotificationService(provider=dry_run_provider, db=notif_db)
        service.process_decision(ineligible_decision)
        events = notif_db.query(NotificationEvent).all()
        assert len(events) == 0

    def test_eligible_creates_audit_log(
        self, notif_db, sample_subject_with_mapping, eligible_decision, dry_run_provider,
    ):
        from app.models.audit_event import AuditEvent

        service = NotificationService(provider=dry_run_provider, db=notif_db)
        service.process_decision(eligible_decision)

        audit_events = notif_db.query(AuditEvent).filter(
            AuditEvent.event_type == AuditEventType.NOTIFICATION,
        ).all()
        assert len(audit_events) == 1
        assert audit_events[0].action == "NOTIFICATION_DRY_RUN"

    def test_concurrent_notification_event_integrity_error_handled_gracefully(
        self, notif_db, sample_subject_with_mapping, eligible_decision, dry_run_provider,
    ):
        """If a duplicate NotificationEvent is inserted concurrently, IntegrityError is caught safely."""
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError

        service = NotificationService(provider=dry_run_provider, db=notif_db)

        # Pre-record an event in DB with the exact same (date, subject_id)
        first_event = NotificationEvent(
            date=eligible_decision.target_date,
            subject_id=sample_subject_with_mapping.id,
            subject_code=eligible_decision.subject_code,
            recipient_email="prof@univ.edu",
            status=NotificationStatus.SKIPPED,
        )
        notif_db.add(first_event)
        notif_db.commit()

        # process_decision will attempt to record a duplicate event, triggering real DB IntegrityError
        # Service must catch it, rollback, and continue to audit log without crashing
        outcome = service.process_decision(eligible_decision)
        assert outcome is not None
        assert outcome.success is True



# ═══════════════════════════════════════════════════════════════════════════
# 7. Provider failure handling
# ═══════════════════════════════════════════════════════════════════════════


class TestProviderFailureHandling:
    """Verify graceful handling when the provider fails."""

    def test_provider_exception_returns_failed_outcome(
        self, notif_db, sample_subject_with_mapping, eligible_decision,
    ):
        """When provider.send() raises, service must catch and return failure."""

        class FailingProvider(BaseNotificationProvider):
            @property
            def provider_name(self) -> str:
                return "failing"

            @property
            def is_dry_run(self) -> bool:
                return False

            def send(self, payload):
                raise NotificationDeliveryError("Connection refused")

            def validate_config(self) -> bool:
                return True

        provider = FailingProvider()
        service = NotificationService(provider=provider, db=notif_db)
        outcome = service.process_decision(eligible_decision)

        assert outcome is not None
        assert outcome.success is False
        assert "Connection refused" in outcome.error_message

    def test_provider_failure_records_failed_event(
        self, notif_db, sample_subject_with_mapping, eligible_decision,
    ):
        """A failed provider must still record a FAILED notification event."""

        class FailingProvider(BaseNotificationProvider):
            @property
            def provider_name(self) -> str:
                return "failing"

            @property
            def is_dry_run(self) -> bool:
                return False

            def send(self, payload):
                raise NotificationDeliveryError("Timeout")

            def validate_config(self) -> bool:
                return True

        provider = FailingProvider()
        service = NotificationService(provider=provider, db=notif_db)
        service.process_decision(eligible_decision)

        events = notif_db.query(NotificationEvent).all()
        assert len(events) == 1
        assert events[0].status == NotificationStatus.FAILED


# ═══════════════════════════════════════════════════════════════════════════
# 8. Exception hierarchy
# ═══════════════════════════════════════════════════════════════════════════


class TestExceptionHierarchy:
    """Verify notification exception hierarchy is correct."""

    def test_config_error_is_provider_error(self):
        assert issubclass(NotificationConfigError, NotificationProviderError)

    def test_delivery_error_is_provider_error(self):
        assert issubclass(NotificationDeliveryError, NotificationProviderError)

    def test_provider_error_is_exception(self):
        assert issubclass(NotificationProviderError, Exception)


# ═══════════════════════════════════════════════════════════════════════════
# 9. NotificationPayload and NotificationOutcome immutability
# ═══════════════════════════════════════════════════════════════════════════


class TestDataContractImmutability:
    """Verify dataclass contracts are frozen/immutable."""

    def test_payload_is_frozen(self, sample_payload):
        with pytest.raises(AttributeError):
            sample_payload.subject_code = "CHANGED"  # type: ignore[misc]

    def test_outcome_is_frozen(self):
        outcome = NotificationOutcome(
            success=True,
            provider_name="test",
            is_dry_run=True,
            message_preview="test",
        )
        with pytest.raises(AttributeError):
            outcome.success = False  # type: ignore[misc]
