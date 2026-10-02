"""Portal Academic Attendance model storing authoritative attendance extracted from PWIOI portal."""

from datetime import datetime, timezone
import json
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PortalAttendanceSummary(Base):
    """Authoritative academic attendance record extracted directly from PWIOI Student Portal.
    
    Invariants:
    - Never stores synthetic, estimated, or fabricated percentages.
    - Captures overall portal attendance %, total classes, attended classes, and course-level stats.
    - If unextracted or awaiting sync, sync_status reflects 'AWAITING_PORTAL_SYNC' and values are None.
    """

    __tablename__ = "portal_academic_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    overall_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_classes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attended_classes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    missed_classes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    course_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    academic_term: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sync_status: Mapped[str] = mapped_column(
        String(50), default="AWAITING_PORTAL_SYNC", nullable=False
    )
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    courses_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def get_course_stats(self) -> dict[str, Any]:
        """Return parsed dictionary of course-level portal attendance stats."""
        if not self.courses_json:
            return {}
        try:
            return json.loads(self.courses_json)
        except Exception:
            return {}

    def set_course_stats(self, stats: dict[str, Any]) -> None:
        """Serialize course-level portal attendance stats."""
        self.courses_json = json.dumps(stats)

    def __repr__(self) -> str:
        return f"<PortalAttendanceSummary status={self.sync_status} rate={self.overall_rate} synced_at={self.synced_at}>"
