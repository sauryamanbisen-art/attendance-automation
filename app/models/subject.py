"""Subject model representing enrolled courses/classes."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.attendance_result import AttendanceResult
    from app.models.calendar import ClassException
    from app.models.notification_event import NotificationEvent
    from app.models.professor_mapping import ProfessorMapping
    from app.models.timetable import TimetableSlot

# Authoritative curriculum course codes for PWIOI SOT25 Term 3
VALID_CURRICULUM_CODES = {
    "301ADS",  # Advance Data Structures and Algorithms
    "302OPS",  # Operating System
    "303PDS",  # Python for Data Science
    "304ELS",  # Essential Language Skills
    "304VEP",  # Data Visualization using Excel and Powerbi
    "306JWD",  # OJT / Java Web Developer (Spring Boot)
}


def is_valid_curriculum_code(code: str) -> bool:
    """Validate whether a course code belongs to the authoritative curriculum."""
    if not code or not isinstance(code, str):
        return False
    return code.strip().upper() in VALID_CURRICULUM_CODES


class Subject(Base):
    """Subject/course entity."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
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

    # Relationships
    professor_mapping: Mapped[Optional["ProfessorMapping"]] = relationship(
        "ProfessorMapping",
        back_populates="subject",
        uselist=False,
        cascade="all, delete-orphan",
    )
    attendance_results: Mapped[List["AttendanceResult"]] = relationship(
        "AttendanceResult",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    notification_events: Mapped[List["NotificationEvent"]] = relationship(
        "NotificationEvent",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    timetable_slots: Mapped[List["TimetableSlot"]] = relationship(
        "TimetableSlot",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    class_exceptions: Mapped[List["ClassException"]] = relationship(
        "ClassException",
        back_populates="subject",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Subject code={self.code} name={self.name}>"
