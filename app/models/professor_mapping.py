"""Professor mapping model connecting subjects to faculty email addresses."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.subject import Subject


class ProfessorMapping(Base):
    """Mapping between a subject and the responsible professor."""

    __tablename__ = "professor_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    professor_name: Mapped[str] = mapped_column(String(150), nullable=False)
    professor_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    google_chat_space: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    subject: Mapped["Subject"] = relationship(
        "Subject",
        back_populates="professor_mapping",
    )

    def __repr__(self) -> str:
        return (
            f"<ProfessorMapping subject_id={self.subject_id} prof={self.professor_name} "
            f"email={self.professor_email} space={self.google_chat_space} active={self.is_active}>"
        )
