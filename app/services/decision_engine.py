"""Isolated, deterministic decision engine for attendance discrepancy evaluation."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.enums import AttendanceStatus, DecisionAction, DecisionReason
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.notification_event import NotificationEvent
from app.models.subject import Subject


@dataclass(frozen=True)
class DecisionResult:
    """Outcome of the decision engine evaluation."""

    action: DecisionAction
    reason: DecisionReason
    subject_code: str
    target_date: date
    is_confirmed: bool
    status: AttendanceStatus
    is_reliable: bool
    professor_email: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_eligible(self) -> bool:
        """True if this subject is eligible for correction notification."""
        return self.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION


class DecisionEngine:
    """Isolated, deterministic decision engine evaluating attendance safety rules.

    Safety Logic:
    IF attendance was NOT confirmed:
        NO_ACTION (reason: ATTENDANCE_NOT_CONFIRMED)

    IF attendance status is PRESENT:
        NO_ACTION (reason: STATUS_PRESENT)

    IF attendance status is UNKNOWN:
        NO_ACTION (reason: STATUS_UNKNOWN)

    IF attendance result is UNRELIABLE (not is_reliable):
        NO_ACTION (reason: UNRELIABLE_ATTENDANCE_RESULT)

    IF attendance status is ABSENT:
        IF professor mapping is missing:
            NO_ACTION (reason: MISSING_PROFESSOR_MAPPING)

        IF notification already exists for date + subject:
            NO_ACTION (reason: ALREADY_NOTIFIED)

        OTHERWISE:
            ELIGIBLE_FOR_NOTIFICATION (reason: ABSENT_AND_CONFIRMED)
    """

    @staticmethod
    def evaluate(
        is_confirmed: bool,
        status: AttendanceStatus,
        is_reliable: bool,
        has_professor_mapping: bool,
        already_notified: bool,
        subject_code: str,
        target_date: date,
        professor_email: Optional[str] = None,
        is_holiday: bool = False,
        is_cancelled: bool = False,
        is_extra: bool = False,
        details: Optional[dict[str, Any]] = None,
    ) -> DecisionResult:
        """Evaluate attendance safety invariant with pure domain inputs.

        This method is completely decoupled from databases, network, and browsers,
        enabling rigorous isolated unit testing.
        """
        extra_details = dict(details or {})

        # Rule 1: Student did NOT confirm attendance for the day -> fail closed
        if not is_confirmed:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.ATTENDANCE_NOT_CONFIRMED,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 1b: Class was cancelled on this date -> no discrepancy, no action
        if is_cancelled:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.CLASS_CANCELLED,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 1c: College holiday and not an extra scheduled class -> no regular classes held
        if is_holiday and not is_extra:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.HOLIDAY,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 2: Portal marked student PRESENT -> no discrepancy, no action
        if status == AttendanceStatus.PRESENT:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.STATUS_PRESENT,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 3: Portal status is UNKNOWN / ambiguous / error -> fail closed
        if status == AttendanceStatus.UNKNOWN:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.STATUS_UNKNOWN,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 4: Portal result is unreliable -> fail closed
        if not is_reliable:
            return DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=DecisionReason.UNRELIABLE_ATTENDANCE_RESULT,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Rule 5: Portal status is explicit ABSENT and reliable
        if status == AttendanceStatus.ABSENT:
            # Sub-rule 5a: Missing professor mapping or email -> cannot notify
            if not has_professor_mapping or not professor_email:
                return DecisionResult(
                    action=DecisionAction.NO_ACTION,
                    reason=DecisionReason.MISSING_PROFESSOR_MAPPING,
                    subject_code=subject_code,
                    target_date=target_date,
                    is_confirmed=is_confirmed,
                    status=status,
                    is_reliable=is_reliable,
                    professor_email=None,
                    details=extra_details,
                )

            # Sub-rule 5b: Already notified for date + subject -> prevent spam/duplicates
            if already_notified:
                return DecisionResult(
                    action=DecisionAction.NO_ACTION,
                    reason=DecisionReason.ALREADY_NOTIFIED,
                    subject_code=subject_code,
                    target_date=target_date,
                    is_confirmed=is_confirmed,
                    status=status,
                    is_reliable=is_reliable,
                    professor_email=professor_email,
                    details=extra_details,
                )

            # Sub-rule 5c: All prerequisites met -> ELIGIBLE_FOR_NOTIFICATION
            return DecisionResult(
                action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
                reason=DecisionReason.ABSENT_AND_CONFIRMED,
                subject_code=subject_code,
                target_date=target_date,
                is_confirmed=is_confirmed,
                status=status,
                is_reliable=is_reliable,
                professor_email=professor_email,
                details=extra_details,
            )

        # Catch-all: Any unexpected enum fails closed
        return DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.STATUS_UNKNOWN,
            subject_code=subject_code,
            target_date=target_date,
            is_confirmed=is_confirmed,
            status=AttendanceStatus.UNKNOWN,
            is_reliable=is_reliable,
            details=extra_details,
        )

    def evaluate_subject_record(
        self,
        db: Session,
        target_date: date,
        subject_code: str,
        status: AttendanceStatus,
        is_reliable: bool,
    ) -> DecisionResult:
        """Evaluate a subject record using the current database state."""
        # 1. Check daily confirmation
        is_confirmed = (
            db.query(AttendanceConfirmation)
            .filter(AttendanceConfirmation.date == target_date)
            .first()
            is not None
        )

        # 2. Check if date is a college holiday
        is_holiday = (
            db.query(Holiday)
            .filter(Holiday.date == target_date)
            .first()
            is not None
        )

        # 3. Check subject & professor mapping
        subject = (
            db.query(Subject)
            .filter(Subject.code == subject_code)
            .first()
        )

        has_mapping = False
        prof_email: Optional[str] = None
        already_notified = False
        is_cancelled = False
        is_extra = False

        if subject:
            if (
                subject.professor_mapping
                and subject.professor_mapping.professor_email
                and getattr(subject.professor_mapping, "is_active", True)
            ):
                has_mapping = True
                prof_email = subject.professor_mapping.professor_email

            # 4. Check for existing notification event for date + subject
            existing_notification = (
                db.query(NotificationEvent)
                .filter(
                    NotificationEvent.date == target_date,
                    NotificationEvent.subject_id == subject.id,
                )
                .first()
            )
            if existing_notification:
                already_notified = True

            # 5. Check class exceptions for date + subject
            exceptions = (
                db.query(ClassException)
                .filter(
                    ClassException.date == target_date,
                    ClassException.subject_id == subject.id,
                )
                .all()
            )
            is_cancelled = any(e.exception_type == ExceptionType.CANCELLED for e in exceptions)
            is_extra = any(e.exception_type == ExceptionType.EXTRA for e in exceptions)

        return self.evaluate(
            is_confirmed=is_confirmed,
            status=status,
            is_reliable=is_reliable,
            has_professor_mapping=has_mapping,
            already_notified=already_notified,
            subject_code=subject_code,
            target_date=target_date,
            professor_email=prof_email,
            is_holiday=is_holiday,
            is_cancelled=is_cancelled,
            is_extra=is_extra,
        )
