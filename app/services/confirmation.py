"""Attendance confirmation service: 'I WENT TO COLLEGE'."""

import uuid
from datetime import date, datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.audit_event import AuditEvent


class ConfirmationService:
    """Service managing explicit student daily attendance confirmation."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def is_confirmed(self, target_date: date) -> bool:
        """Check if attendance has been confirmed for the exact target date."""
        record = (
            self.db.query(AttendanceConfirmation)
            .filter(AttendanceConfirmation.date == target_date)
            .first()
        )
        return record is not None

    def get_confirmation(self, target_date: date) -> Optional[AttendanceConfirmation]:
        """Retrieve confirmation for the exact target date."""
        return (
            self.db.query(AttendanceConfirmation)
            .filter(AttendanceConfirmation.date == target_date)
            .first()
        )

    def confirm_attendance(
        self,
        target_date: date,
        note: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Tuple[AttendanceConfirmation, bool]:
        """Confirm student attendance for a specific target date.

        Guarantees:
        - Date-specific: applies ONLY to target_date, never previous or future dates.
        - Idempotent: duplicate calls return the existing confirmation without creating new rows.
        - Audited: creates an audit event upon new confirmation.

        Returns:
            Tuple[AttendanceConfirmation, bool]: (record, created_flag)
        """
        existing = (
            self.db.query(AttendanceConfirmation)
            .filter(AttendanceConfirmation.date == target_date)
            .first()
        )
        if existing:
            return existing, False

        now = datetime.now(timezone.utc)
        record = AttendanceConfirmation(
            date=target_date,
            confirmed_at=now,
            note=note,
            created_at=now,
        )
        try:
            self.db.add(record)
            self.db.flush()

            # Record audit event
            audit = AuditEvent(
                run_id=run_id or str(uuid.uuid4()),
                event_type=AuditEventType.CONFIRMATION,
                action="CONFIRM_ATTENDANCE",
                entity_type="attendance_confirmations",
                entity_id=str(record.id),
                details={
                    "date": target_date.isoformat(),
                    "confirmed_at": now.isoformat(),
                    "note": note,
                },
                timestamp=now,
            )
            self.db.add(audit)
            self.db.commit()
            self.db.refresh(record)
            return record, True
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(AttendanceConfirmation)
                .filter(AttendanceConfirmation.date == target_date)
                .first()
            )
            if existing:
                return existing, False
            raise
