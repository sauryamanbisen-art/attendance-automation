"""Service managing authoritative academic attendance records extracted from PWIOI portal."""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.portal_attendance import PortalAttendanceSummary

logger = logging.getLogger(__name__)


class PortalAttendanceService:
    """Service to query, persist, and synchronize real academic attendance from the portal."""

    def __init__(self, db: Session):
        self.db = db

    def get_summary(self) -> Optional[PortalAttendanceSummary]:
        """Retrieve the authoritative portal academic attendance record.
        
        Returns None or PortalAttendanceSummary. If none exists, callers must
        display truthful 'Awaiting Portal Sync' or 'N/A' states.
        """
        return self.db.query(PortalAttendanceSummary).order_by(PortalAttendanceSummary.id.desc()).first()

    def get_or_create_awaiting_summary(self) -> PortalAttendanceSummary:
        """Get existing summary or create a truthful default awaiting sync record."""
        summary = self.get_summary()
        if not summary:
            summary = PortalAttendanceSummary(
                sync_status="AWAITING_PORTAL_SYNC",
                overall_rate=None,
                total_classes=None,
                attended_classes=None,
                missed_classes=None,
                course_count=None,
                synced_at=None,
            )
            self.db.add(summary)
            self.db.commit()
            self.db.refresh(summary)
        return summary

    def update_summary(
        self,
        overall_rate: Optional[float] = None,
        total_classes: Optional[int] = None,
        attended_classes: Optional[int] = None,
        missed_classes: Optional[int] = None,
        course_count: Optional[int] = None,
        academic_term: Optional[str] = None,
        course_stats: Optional[dict[str, Any]] = None,
        sync_status: str = "SYNCED",
    ) -> PortalAttendanceSummary:
        """Persist verified portal attendance values from extraction.
        
        Invariant: Never accepts or saves synthetic/invented data.
        """
        summary = self.get_summary()
        now = datetime.now(timezone.utc)
        if not summary:
            summary = PortalAttendanceSummary(created_at=now)
            self.db.add(summary)

        summary.overall_rate = overall_rate
        summary.total_classes = total_classes
        summary.attended_classes = attended_classes
        summary.missed_classes = missed_classes
        summary.course_count = course_count
        summary.academic_term = academic_term
        summary.sync_status = sync_status
        summary.synced_at = now if sync_status == "SYNCED" else None
        if course_stats is not None:
            summary.set_course_stats(course_stats)

        self.db.commit()
        self.db.refresh(summary)
        return summary
