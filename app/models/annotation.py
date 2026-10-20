from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.session import Transcript, Turn


class Annotation(Base):
    __tablename__ = "annotations"

    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[int] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(10))   # 'question' | 'answer'
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(10))  # 'system' | 'user'
    kind: Mapped[str] = mapped_column(String(10))    # 'keep'|'chase'|'leave'|'out'|'told'|'skip'|'note'
    body: Mapped[str | None] = mapped_column(Text)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    transcript: Mapped["Transcript"] = relationship(back_populates="annotations")
    turn: Mapped["Turn"] = relationship(back_populates="annotations")

    def __str__(self) -> str:
        return f"Annotation {self.id} ({self.kind})"
