"""Attendance result model recording individual subject status from a check."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AttendanceStatus
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.attendance_check import AttendanceCheck
    from app.models.subject import Subject


class AttendanceResult(Base):
    """Subject attendance result obtained from an adapter run."""

    __tablename__ = "attendance_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attendance_checks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    subject_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    subject_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        SAEnum(AttendanceStatus, native_enum=False),
        default=AttendanceStatus.UNKNOWN,
        nullable=False,
    )
    raw_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_reliable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    check: Mapped["AttendanceCheck"] = relationship(
        "AttendanceCheck",
        back_populates="results",
    )
    subject: Mapped[Optional["Subject"]] = relationship(
        "Subject",
        back_populates="attendance_results",
    )

    def __repr__(self) -> str:
        return f"<AttendanceResult subject={self.subject_code} status={self.status} reliable={self.is_reliable}>"
