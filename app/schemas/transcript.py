from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import JobStatus, TranscriptSource
from app.schemas.common import Stripped


class ManualTranscriptCreate(BaseModel):
    transcript_text: Annotated[str, Stripped, Field(min_length=50)]


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    transcript_text: str
    status: JobStatus
    source: TranscriptSource
    language: str
    duration_seconds: int | None
    created_at: datetime
    updated_at: datetime
