"""Notification orchestration service.

This service sits between the decision engine output and the notification provider.
It enforces the critical safety invariant:

  Only records with action == ELIGIBLE_FOR_NOTIFICATION may be dispatched.

The service:
1. Validates eligibility from the DecisionResult
2. Generates the polite correction message
3. Dispatches through the configured NotificationProvider
4. Records the NotificationEvent in the database
5. Audit-logs the outcome
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType, DecisionAction, NotificationStatus
from app.models.notification_event import NotificationEvent
from app.models.subject import Subject
from app.notifications.base import (
    BaseNotificationProvider,
    NotificationOutcome,
    NotificationPayload,
    NotificationProviderError,
)
from app.notifications.message import generate_correction_body, generate_correction_subject
from app.security.redaction import redact_string
from app.services.audit import AuditService
from app.services.decision_engine import DecisionResult

logger = logging.getLogger(__name__)


class NotificationService:
    """Orchestrates notification dispatch for eligible attendance discrepancies.

    Safety rules enforced:
    - ONLY DecisionResults with action == ELIGIBLE_FOR_NOTIFICATION are processed.
    - provider.send() is called ONLY after eligibility is validated.
    - All outcomes (success, failure, rejection) are audit-logged.
    """

    def __init__(
        self,
        provider: BaseNotificationProvider,
        db: Session,
        student_name: Optional[str] = None,
    ) -> None:
        self.provider = provider
        self.db = db
        self.audit_service = AuditService(db)
        self.student_name = student_name

    def process_decision(
        self,
        decision: DecisionResult,
    ) -> Optional[NotificationOutcome]:
        """Process a single DecisionResult and dispatch notification if eligible.

        Args:
            decision: The decision engine outcome to process.

        Returns:
            NotificationOutcome if a notification was attempted (including dry-run),
            None if the decision was not eligible.
        """
        # ── SAFETY GATE: Only eligible decisions proceed ──
        if decision.action != DecisionAction.ELIGIBLE_FOR_NOTIFICATION:
            logger.debug(
                "Skipping notification for %s on %s: action=%s, reason=%s",
                decision.subject_code,
                decision.target_date,
                decision.action,
                decision.reason,
            )
            return None

        if not decision.professor_email:
            logger.warning(
                "Eligible decision for %s on %s has no professor email — skipping.",
                decision.subject_code,
                decision.target_date,
            )
            self.audit_service.log(
                event_type=AuditEventType.NOTIFICATION,
                action="NOTIFICATION_SKIPPED_MISSING_DESTINATION",
                entity_type="subjects",
                details={
                    "subject_code": decision.subject_code,
                    "target_date": decision.target_date.isoformat(),
                    "reason": "MISSING_PROFESSOR_EMAIL",
                },
            )
            return None

        # Resolve subject name from DB
        subject = (
            self.db.query(Subject)
            .filter(Subject.code == decision.subject_code)
            .first()
        )
        subject_name = subject.name if subject else decision.subject_code

        # Resolve professor name and Google Chat space from subject mapping
        professor_name = "Professor"
        chat_space = None
        if subject and subject.professor_mapping:
            if subject.professor_mapping.professor_name:
                professor_name = subject.professor_mapping.professor_name
            if getattr(subject.professor_mapping, "google_chat_space", None):
                chat_space = subject.professor_mapping.google_chat_space

        # Generate polite, factual message
        message_subject = generate_correction_subject(
            subject_code=decision.subject_code,
            subject_name=subject_name,
            target_date=decision.target_date,
        )
        message_body = generate_correction_body(
            subject_code=decision.subject_code,
            subject_name=subject_name,
            target_date=decision.target_date,
            professor_name=professor_name,
            student_name=self.student_name,
        )

        metadata: dict[str, str] = {}
        if chat_space:
            metadata["space_id"] = chat_space

        payload = NotificationPayload(
            subject_code=decision.subject_code,
            subject_name=subject_name,
            target_date=decision.target_date,
            recipient_email=decision.professor_email,
            professor_name=professor_name,
            message_subject=message_subject,
            message_body=message_body,
            student_name=self.student_name,
            metadata=metadata,
        )

        # Dispatch through provider
        try:
            outcome = self.provider.send(payload)
        except Exception as exc:
            safe_err = redact_string(str(exc))
            logger.error(
                "Provider %s failed for %s on %s: %s",
                self.provider.provider_name,
                decision.subject_code,
                decision.target_date,
                safe_err,
            )
            outcome = NotificationOutcome(
                success=False,
                provider_name=self.provider.provider_name,
                is_dry_run=self.provider.is_dry_run,
                message_preview=f"FAILED: {safe_err}",
                error_message=safe_err,
            )

        # Record notification event in DB
        self._record_event(decision, outcome, subject)

        # Audit log
        self._audit_log(decision, outcome)

        return outcome

    def _record_event(
        self,
        decision: DecisionResult,
        outcome: NotificationOutcome,
        subject: Optional[Subject],
    ) -> None:
        """Persist notification event for deduplication and history tracking."""
        if not subject:
            logger.warning(
                "Cannot record notification event — subject %s not found in DB.",
                decision.subject_code,
            )
            return

        status = NotificationStatus.PENDING
        if outcome.success and outcome.is_dry_run:
            status = NotificationStatus.SKIPPED
        elif outcome.success:
            status = NotificationStatus.SENT
        elif not outcome.success:
            status = NotificationStatus.FAILED

        event = NotificationEvent(
            date=decision.target_date,
            subject_id=subject.id,
            subject_code=decision.subject_code,
            recipient_email=decision.professor_email or "",
            status=status,
            template_name="attendance_correction",
            sent_at=datetime.now(timezone.utc) if outcome.success and not outcome.is_dry_run else None,
            error_message=outcome.error_message,
            dry_run=outcome.is_dry_run,
        )
        try:
            self.db.add(event)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "NotificationEvent already exists for %s on %s (deduplicated).",
                decision.subject_code,
                decision.target_date,
            )

    def _audit_log(
        self,
        decision: DecisionResult,
        outcome: NotificationOutcome,
    ) -> None:
        """Audit-log the notification outcome."""
        action = "NOTIFICATION_DRY_RUN" if outcome.is_dry_run else "NOTIFICATION_SENT"
        if not outcome.success:
            action = "NOTIFICATION_FAILED"

        self.audit_service.log(
            event_type=AuditEventType.NOTIFICATION,
            action=action,
            entity_type="notification_events",
            details={
                "subject_code": decision.subject_code,
                "target_date": decision.target_date.isoformat(),
                "provider": outcome.provider_name,
                "is_dry_run": outcome.is_dry_run,
                "success": outcome.success,
                "error": outcome.error_message,
            },
        )
