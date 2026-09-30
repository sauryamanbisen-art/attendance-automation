"""Attendance check model recording runs against portal adapters."""

import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CheckStatus
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.attendance_result import AttendanceResult


class AttendanceCheck(Base):
    """Execution record of an automated or manual portal attendance check."""

    __tablename__ = "attendance_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    check_date: Mapped[date_type] = mapped_column(Date, index=True, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    adapter_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[CheckStatus] = mapped_column(
        SAEnum(CheckStatus, native_enum=False),
        default=CheckStatus.SUCCESS,
        nullable=False,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    results: Mapped[List["AttendanceResult"]] = relationship(
        "AttendanceResult",
        back_populates="check",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AttendanceCheck run_id={self.run_id} date={self.check_date} status={self.status}>"
