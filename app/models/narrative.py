import secrets
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import JobStatus, NarrativeFormat

if TYPE_CHECKING:
    from app.models.subject import Subject


def new_share_token() -> str:
    return secrets.token_urlsafe(24)  # 32 URL-safe characters


class Narrative(Base):
    """An AI-written narrative of a subject's story. One per (subject, format);
    regenerating overwrites it."""

    __tablename__ = "narratives"
    __table_args__ = (UniqueConstraint("subject_id", "format"),)

    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    format: Mapped[NarrativeFormat] = mapped_column(
        str_enum(NarrativeFormat), default=NarrativeFormat.MEMOIR
    )
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.PENDING)
    # Empty until generation finishes (generation moves to a background job in step 10).
    narrative_text: Mapped[str | None] = mapped_column(Text)
    share_token: Mapped[str] = mapped_column(String(32), unique=True, default=new_share_token)

    subject: Mapped["Subject"] = relationship(back_populates="narratives")
