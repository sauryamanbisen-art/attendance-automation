"""Daily scheduled attendance check orchestrator.

Coordinates:
1. Cutoff time enforcement (default 16:00 / 4 PM)
2. Attendance confirmation check ('I WENT TO COLLEGE')
3. Portal adapter execution (PWIOI or configured adapter)
4. Decision Engine discrepancy evaluation
5. Notification dispatch (Dry-Run by default)
6. Comprehensive audit logging
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.adapters.factory import get_portal_adapter
from app.config import Settings, get_settings
from app.core.enums import AttendanceStatus, AuditEventType, CheckStatus, DecisionAction
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_result import AttendanceResult
from app.models.subject import Subject
from app.notifications.base import BaseNotificationProvider
from app.notifications.dry_run import DryRunNotificationProvider
from app.notifications.service import NotificationService
from app.security.redaction import redact_string
from app.services.audit import AuditService
from app.services.confirmation import ConfirmationService
from app.services.decision_engine import DecisionEngine, DecisionResult
from app.services.timetable_service import TimetableService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyCheckResult:
    """Structured outcome of a scheduled daily check execution."""

    run_id: str
    target_date: date
    status: str  # "SUCCESS", "SKIPPED", "FAILED"
    reason: Optional[str] = None
    subjects_checked: int = 0
    eligible_count: int = 0
    decisions: List[DecisionResult] = field(default_factory=list)
    notifications_sent: int = 0
    error_message: Optional[str] = None
    dry_run: bool = True


class DailyCheckRunner:
    """Orchestrator for automated daily attendance checks and decision evaluations."""

    def __init__(
        self,
        db: Session,
        settings: Optional[Settings] = None,
        notification_provider: Optional[BaseNotificationProvider] = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.notification_provider = notification_provider
        self.audit_service = AuditService(db)
        self.confirmation_service = ConfirmationService(db)
        self.decision_engine = DecisionEngine()

    def run_daily_check(
        self,
        target_date: Optional[date] = None,
        current_time: Optional[datetime] = None,
        ignore_cutoff: bool = False,
        adapter: Optional[BasePortalAdapter] = None,
        adapter_name: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> DailyCheckResult:
        """Execute the scheduled daily attendance workflow safely.

        Safety Invariants:
        1. If before cutoff time (default 16:00) and ignore_cutoff=False: safely SKIPPED.
        2. If student did not confirm attendance for target date: safely SKIPPED.
        3. Never modifies attendance records.
        4. Decision Engine invariants strictly preserved (no duplicated logic).
        5. Fails closed to SKIPPED / FAILED without dispatching unauthorized notifications.
        """
        # Resolve timezone and current execution timestamp
        tz_name = self.settings.timezone or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        now = current_time or datetime.now(tz)
        eff_date = target_date or now.date()
        is_dry_run = dry_run if dry_run is not None else self.settings.dry_run
        run_id = str(uuid.uuid4())

        # 1. Parse and check cutoff time
        cutoff_str = getattr(self.settings, "cutoff_time", "16:00")
        try:
            parts = cutoff_str.strip().split(":")
            cutoff_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        except Exception:
            cutoff_t = time(16, 0)

        # Audit log scheduler start
        self.audit_service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="SCHEDULER_START",
            entity_type="attendance_checks",
            run_id=run_id,
            details={
                "date": eff_date.isoformat(),
                "time": now.isoformat(),
                "cutoff_time": str(cutoff_t),
                "ignore_cutoff": ignore_cutoff,
                "dry_run": is_dry_run,
            },
        )

        if eff_date > now.date():
            logger.info("Target date %s is in the future. Skipping check.", eff_date.isoformat())
            self.audit_service.log(
                event_type=AuditEventType.ATTENDANCE_CHECK,
                action="SCHEDULER_SKIPPED",
                entity_type="attendance_checks",
                run_id=run_id,
                details={
                    "reason": "FUTURE_DATE",
                    "date": eff_date.isoformat(),
                    "today": now.date().isoformat(),
                },
            )
            return DailyCheckResult(
                run_id=run_id,
                target_date=eff_date,
                status="SKIPPED",
                reason="FUTURE_DATE",
                dry_run=is_dry_run,
            )

        if not ignore_cutoff and eff_date == now.date() and now.time() < cutoff_t:
            logger.info(
                "Current time %s is before configured cutoff %s. Skipping check for %s.",
                now.time().strftime("%H:%M"),
                cutoff_t.strftime("%H:%M"),
                eff_date.isoformat(),
            )
            self.audit_service.log(
                event_type=AuditEventType.ATTENDANCE_CHECK,
                action="SCHEDULER_SKIPPED",
                entity_type="attendance_checks",
                run_id=run_id,
                details={
                    "reason": "BEFORE_CUTOFF_TIME",
                    "current_time": str(now.time()),
                    "cutoff_time": str(cutoff_t),
                    "date": eff_date.isoformat(),
                },
            )
            return DailyCheckResult(
                run_id=run_id,
                target_date=eff_date,
                status="SKIPPED",
                reason="BEFORE_CUTOFF_TIME",
                dry_run=is_dry_run,
            )

        # 2. Check student daily attendance confirmation ('I WENT TO COLLEGE')
        if not self.confirmation_service.is_confirmed(eff_date):
            logger.info(
                "Student did not confirm attendance for %s. Skipping portal check.",
                eff_date.isoformat(),
            )
            self.audit_service.log(
                event_type=AuditEventType.ATTENDANCE_CHECK,
                action="SCHEDULER_SKIPPED",
                entity_type="attendance_checks",
                run_id=run_id,
                details={
                    "reason": "ATTENDANCE_NOT_CONFIRMED",
                    "date": eff_date.isoformat(),
                },
            )
            return DailyCheckResult(
                run_id=run_id,
                target_date=eff_date,
                status="SKIPPED",
                reason="ATTENDANCE_NOT_CONFIRMED",
                dry_run=is_dry_run,
            )

        # 3. Instantiate portal adapter if not injected
        portal_adapter = adapter or get_portal_adapter(
            adapter_name=adapter_name,
            settings=self.settings,
        )
        adapter_name_resolved = portal_adapter.adapter_name

        check_record = AttendanceCheck(
            run_id=run_id,
            check_date=eff_date,
            checked_at=datetime.now(timezone.utc),
            adapter_name=adapter_name_resolved,
            status=CheckStatus.SUCCESS,
        )
        self.db.add(check_record)
        self.db.flush()

        records: List[SubjectAttendance] = []
        try:
            portal_adapter.validate_config()
            portal_adapter.authenticate()
            records = portal_adapter.get_attendance_for_date(eff_date)
        except Exception as exc:
            self.db.rollback()
            safe_err = redact_string(str(exc))
            logger.error("Portal adapter execution failed for %s: %s", adapter_name_resolved, safe_err)

            check_record.status = CheckStatus.FAILED
            check_record.error_message = safe_err
            self.db.add(check_record)
            self.db.commit()

            self.audit_service.log(
                event_type=AuditEventType.ATTENDANCE_CHECK,
                action="SCHEDULER_FAILED",
                entity_type="attendance_checks",
                run_id=run_id,
                details={"error": safe_err, "adapter": adapter_name_resolved, "date": eff_date.isoformat()},
            )
            return DailyCheckResult(
                run_id=run_id,
                target_date=eff_date,
                status="FAILED",
                error_message=safe_err,
                dry_run=is_dry_run,
            )
        finally:
            portal_adapter.close()

        # 4. Fetch expected classes from TimetableService
        timetable_service = TimetableService(self.db)
        expected_subjects = timetable_service.get_classes_for_date(eff_date)
        expected_subject_codes = {s.code: s for s in expected_subjects}

        # 5. Evaluate decisions and save results
        decisions: List[DecisionResult] = []
        processed_codes = set()

        for rec in records:
            processed_codes.add(rec.subject_code)
            subject = self.db.query(Subject).filter(Subject.code == rec.subject_code).first()
            subject_id = subject.id if subject else None

            res_record = AttendanceResult(
                check_id=check_record.id,
                subject_id=subject_id,
                subject_code=rec.subject_code,
                status=rec.status,
                raw_status=rec.raw_status,
                is_reliable=rec.is_reliable,
                notes=str(rec.metadata) if rec.metadata else None,
            )
            self.db.add(res_record)

            dec = self.decision_engine.evaluate_subject_record(
                db=self.db,
                target_date=eff_date,
                subject_code=rec.subject_code,
                status=rec.status,
                is_reliable=rec.is_reliable,
            )
            decisions.append(dec)

        # 6. Evaluate expected classes missing from the portal response
        for code, subject in expected_subject_codes.items():
            if code not in processed_codes:
                res_record = AttendanceResult(
                    check_id=check_record.id,
                    subject_id=subject.id,
                    subject_code=code,
                    status=AttendanceStatus.UNKNOWN,
                    raw_status="MISSING_FROM_PORTAL",
                    is_reliable=False,
                    notes="Expected from timetable but missing from portal response",
                )
                self.db.add(res_record)

                dec = self.decision_engine.evaluate_subject_record(
                    db=self.db,
                    target_date=eff_date,
                    subject_code=code,
                    status=AttendanceStatus.UNKNOWN,
                    is_reliable=False,
                )
                decisions.append(dec)

        self.db.commit()

        # 5. Process notifications (Dry-Run by default)
        provider = self.notification_provider
        if provider is None:
            if is_dry_run:
                provider = DryRunNotificationProvider()
            else:
                provider_type = getattr(self.settings, "email_provider", "google_chat")
                
                if provider_type == "gmail" and getattr(self.settings, "gmail_client_id", None):
                    from app.notifications.gmail import GmailConfig, GmailClient, GmailNotificationProvider
                    from app.notifications.oauth import FileTokenStorage, GoogleOAuthClient
                    
                    token_file = self.settings.gmail_token_file if hasattr(self.settings, 'gmail_token_file') and self.settings.gmail_token_file else "credentials/gmail_token.json"
                    gmail_config = GmailConfig(
                        client_id=self.settings.gmail_client_id or "",
                        client_secret=self.settings.gmail_client_secret or "",
                        redirect_uri=self.settings.gmail_redirect_uri,
                        sender_email=self.settings.notification_sender_email,
                        token_file=token_file,
                    )
                    oauth_client = GoogleOAuthClient(config=gmail_config, token_storage=FileTokenStorage(token_file))
                    gmail_client = GmailClient(config=gmail_config, oauth_client=oauth_client)
                    provider = GmailNotificationProvider(client=gmail_client, is_dry_run=is_dry_run)
                
                elif provider_type == "google_chat" and getattr(self.settings, "google_chat_client_id", None):
                    from app.notifications.google_chat import (
                        GoogleChatConfig,
                        GoogleChatNotificationProvider,
                    )

                    chat_config = GoogleChatConfig(
                        client_id=self.settings.google_chat_client_id or "",
                        client_secret=self.settings.google_chat_client_secret or "",
                        redirect_uri=self.settings.google_chat_redirect_uri,
                        token_file=self.settings.google_chat_token_file,
                        default_space=self.settings.google_chat_default_space,
                    )
                    # Note: GoogleChatNotificationProvider manages its own OAuthClient internally or takes config
                    provider = GoogleChatNotificationProvider(config=chat_config)
                else:
                    provider = DryRunNotificationProvider()

        notif_service = NotificationService(provider=provider, db=self.db)
        eligible_count = 0
        notifications_sent = 0

        for dec in decisions:
            if dec.is_eligible:
                eligible_count += 1
                try:
                    outcome = notif_service.process_decision(dec)
                    if outcome and outcome.success:
                        notifications_sent += 1
                except Exception as exc:
                    safe_err = redact_string(str(exc))
                    logger.error(
                        "Error processing notification for %s on %s: %s",
                        dec.subject_code,
                        eff_date.isoformat(),
                        safe_err,
                    )

        self.audit_service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="SCHEDULER_COMPLETED",
            entity_type="attendance_checks",
            run_id=run_id,
            details={
                "date": eff_date.isoformat(),
                "subjects_checked": len(records),
                "eligible_count": eligible_count,
                "notifications_sent": notifications_sent,
                "dry_run": is_dry_run,
            },
        )

        return DailyCheckResult(
            run_id=run_id,
            target_date=eff_date,
            status="SUCCESS",
            subjects_checked=len(records),
            eligible_count=eligible_count,
            decisions=decisions,
            notifications_sent=notifications_sent,
            dry_run=is_dry_run,
        )
