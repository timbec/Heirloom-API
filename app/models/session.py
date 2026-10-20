from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import JobStatus, Sensitivity, SessionStatus, ThreadType, TranscriptSource

if TYPE_CHECKING:
    from app.models.annotation import Annotation
    from app.models.plan import SessionPlan
    from app.models.subject import Subject


class InterviewSession(Base):
    """One recorded interview. Called a "session" in the API; renamed here to avoid
    confusion with database sessions."""

    __tablename__ = "sessions"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[SessionStatus] = mapped_column(
        str_enum(SessionStatus), default=SessionStatus.PENDING
    )
    audio_path: Mapped[str | None] = mapped_column(String(1024))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    subject: Mapped["Subject"] = relationship(back_populates="sessions")
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    def __str__(self) -> str:
        return self.title or f"Session {self.id}"


class Transcript(Base):
    __tablename__ = "transcripts"

    # One transcript per session.
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    transcript_text: Mapped[str] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.PENDING)
    source: Mapped[TranscriptSource] = mapped_column(str_enum(TranscriptSource))
    language: Mapped[str] = mapped_column(String(10), default="en", server_default="en")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[InterviewSession] = relationship(back_populates="transcript")
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Turn.turn_index",
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    plan: Mapped["SessionPlan | None"] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    def __str__(self) -> str:
        return f"Transcript {self.id}"


class Turn(Base):
    """One question/answer pair from a transcript, with its scores once scored."""

    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("transcript_id", "turn_index"),
        CheckConstraint("specificity BETWEEN 0 AND 10", name="specificity_range"),
        CheckConstraint("emotional_charge BETWEEN 0 AND 10", name="emotional_charge_range"),
    )

    # Indexed by the (transcript_id, turn_index) unique constraint.
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"))
    turn_index: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)

    specificity: Mapped[int | None] = mapped_column(SmallInteger)
    emotional_charge: Mapped[int | None] = mapped_column(SmallInteger)
    thread_type: Mapped[ThreadType | None] = mapped_column(str_enum(ThreadType))
    is_gold: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    gold_quote: Mapped[str | None] = mapped_column(Text)
    open_thread: Mapped[str | None] = mapped_column(Text)
    sensitivity: Mapped[Sensitivity | None] = mapped_column(str_enum(Sensitivity))
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which model and prompt version produced the scores, e.g. "openai/gpt-oss-120b, prompt v2".
    scored_with: Mapped[str | None] = mapped_column(String(150))

    # Review-phase fields — populated by the reviewer, not the scorer.
    retracted: Mapped[bool | None] = mapped_column(Boolean)
    unable_to_recall: Mapped[bool | None] = mapped_column(Boolean)
    repeat_of: Mapped[int | None] = mapped_column(Integer)  # turn_index of the earlier turn
    thread_anchor: Mapped[str | None] = mapped_column(Text)

    transcript: Mapped[Transcript] = relationship(back_populates="turns")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="turn",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __str__(self) -> str:
        return f"Turn {self.turn_index}"
