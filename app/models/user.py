from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.subject import Subject


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    tokens: Mapped[list["ApiToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @validates("email")
    def normalise_email(self, key: str, value: str) -> str:
        # Stored lowercased so lookups and the unique constraint are case-insensitive.
        return value.strip().lower()

    def __str__(self) -> str:
        return self.email


class ApiToken(Base):
    """A bearer token. Only the sha256 of the token is stored."""

    __tablename__ = "api_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tokens")
