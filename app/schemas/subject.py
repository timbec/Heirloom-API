from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import OptionalText, Stripped

Name = Annotated[str, Stripped, Field(min_length=1, max_length=255)]


class SubjectProfile(BaseModel):
    """The optional profile fields shared by create and update."""

    birth_year: int | None = None
    places_lived: OptionalText = None
    education_profession: OptionalText = None
    family_structure: OptionalText = None
    life_chapters: OptionalText = None
    interests: OptionalText = None

    @field_validator("birth_year")
    @classmethod
    def plausible_birth_year(cls, value: int | None) -> int | None:
        if value is not None and not 1900 <= value <= datetime.now(UTC).year:
            raise ValueError(f"must be between 1900 and {datetime.now(UTC).year}")
        return value


class SubjectCreate(SubjectProfile):
    name: Name


class SubjectUpdate(SubjectProfile):
    """Partial update: only the fields sent are changed."""

    name: Name | None = None


class SubjectFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    birth_year: int | None
    places_lived: str | None
    education_profession: str | None
    family_structure: str | None
    life_chapters: str | None
    interests: str | None
    created_at: datetime
    updated_at: datetime


class SubjectOut(SubjectFields):
    sessions_count: int
