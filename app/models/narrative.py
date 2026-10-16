import secrets
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import JobStatus, NarrativeFormat

if TYPE_CHECKING:
    from app.models.subject import Subject


def new_share_token() -> str:
    return secrets.token_urlsafe(24)  # 32 URL-safe characters


class Narrative(Base):
    """One generated version of a subject's narrative. Every generation adds a row (history
    is kept, failures included); the newest completed one per format is the current one."""

    __tablename__ = "narratives"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[NarrativeFormat] = mapped_column(
        str_enum(NarrativeFormat), default=NarrativeFormat.MEMOIR
    )
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.PENDING)
    # Empty until generation finishes.
    narrative_text: Mapped[str | None] = mapped_column(Text)
    share_token: Mapped[str] = mapped_column(String(32), unique=True, default=new_share_token)

    # Which sessions this version was written from, in order. Plain ids rather than a link
    # table: it's a record of what went in, and stays meaningful if a session is later deleted.
    session_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default=text("'{}'")
    )
    # The model that wrote it, for comparing versions; and why it failed, if it did.
    model: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)

    subject: Mapped["Subject"] = relationship(back_populates="narratives")

    def __str__(self) -> str:
        return f"{self.format} #{self.id}"
