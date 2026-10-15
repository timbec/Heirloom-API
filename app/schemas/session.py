from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import SessionStatus
from app.schemas.common import OptionalShortText
from app.schemas.subject import SubjectFields


class SessionCreate(BaseModel):
    subject_id: int
    title: OptionalShortText = None
    duration_seconds: Annotated[int | None, Field(ge=0)] = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    title: str | None
    status: SessionStatus
    audio_path: str | None
    duration_seconds: int | None
    created_at: datetime
    updated_at: datetime
    subject: SubjectFields
