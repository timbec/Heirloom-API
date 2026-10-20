from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.session import Transcript


class SessionPlan(Base):
    __tablename__ = "session_plans"
    __table_args__ = (UniqueConstraint("transcript_id"),)

    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE")
    )
    content: Mapped[dict] = mapped_column(JSON)
    user_selections: Mapped[dict] = mapped_column(JSON, default=dict)

    transcript: Mapped["Transcript"] = relationship(back_populates="plan")

    def __str__(self) -> str:
        return f"SessionPlan {self.id}"
