"""Notification event model with date and subject deduplication."""

from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NotificationStatus
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.subject import Subject


class NotificationEvent(Base):
    """Record of a notification triggered for an absent subject.

    Enforces strict deduplication: at most one notification event per date + subject.
    """

    __tablename__ = "notification_events"
    __table_args__ = (
        UniqueConstraint("date", "subject_id", name="uq_notification_date_subject"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date_type] = mapped_column(Date, index=True, nullable=False)
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    subject_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, native_enum=False),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    template_name: Mapped[str] = mapped_column(
        String(100),
        default="attendance_correction",
        nullable=False,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    subject: Mapped["Subject"] = relationship(
        "Subject",
        back_populates="notification_events",
    )

    def __repr__(self) -> str:
        return f"<NotificationEvent date={self.date} subject={self.subject_code} status={self.status} dry_run={self.dry_run}>"
