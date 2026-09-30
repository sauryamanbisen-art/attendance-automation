"""Calendar models representing holidays, cancelled classes, and extra classes."""

import enum
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.subject import Subject


class Holiday(Base):
    """A full-day college holiday where no regular classes are held."""

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Holiday date={self.date} desc='{self.description}'>"


class ExceptionType(str, enum.Enum):
    """Type of class exception."""

    CANCELLED = "CANCELLED"
    EXTRA = "EXTRA"


class ClassException(Base):
    """An exception to the regular timetable (e.g., cancelled or extra class)."""

    __tablename__ = "class_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    exception_type: Mapped[ExceptionType] = mapped_column(Enum(ExceptionType), nullable=False)

    # Required for EXTRA classes, optional for CANCELLED (if identifying a specific slot)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship("Subject", back_populates="class_exceptions")

    def __repr__(self) -> str:
        return f"<ClassException type={self.exception_type} subject_id={self.subject_id} date={self.date}>"
