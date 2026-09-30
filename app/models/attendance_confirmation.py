"""Attendance confirmation model for explicit daily student check-in."""

from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AttendanceConfirmation(Base):
    """Daily confirmation by the student: 'I went to college'.

    Enforces strict uniqueness: one attendance confirmation per date.
    """

    __tablename__ = "attendance_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date_type] = mapped_column(
        Date,
        unique=True,
        index=True,
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AttendanceConfirmation date={self.date} confirmed_at={self.confirmed_at}>"
