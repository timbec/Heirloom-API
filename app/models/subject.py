from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.narrative import Narrative
    from app.models.session import InterviewSession
    from app.models.user import User


class Subject(Base):
    """The person whose life story is being recorded. Owns everything below it."""

    __tablename__ = "subjects"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    # Free-text profile fields, fed to the scoring prompt.
    places_lived: Mapped[str | None] = mapped_column(Text)
    education_profession: Mapped[str | None] = mapped_column(Text)
    family_structure: Mapped[str | None] = mapped_column(Text)
    life_chapters: Mapped[str | None] = mapped_column(Text)
    interests: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="subjects")
    sessions: Mapped[list["InterviewSession"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InterviewSession.id",
    )
    narratives: Mapped[list["Narrative"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan", passive_deletes=True
    )

    def __str__(self) -> str:
        return self.name
