"""Timetable models representing the regular class schedule."""

from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.subject import Subject


class TimetableSlot(Base):
    """A regularly scheduled class period."""

    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    period_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Semester/date-range applicability
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship("Subject", back_populates="timetable_slots")

    def __repr__(self) -> str:
        return f"<TimetableSlot subject_id={self.subject_id} weekday={self.weekday} time={self.start_time}-{self.end_time}>"
