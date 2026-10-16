from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import JobStatus, NarrativeFormat


class NarrativeCreate(BaseModel):
    format: NarrativeFormat = NarrativeFormat.MEMOIR
    # Sent by the frontend but ignored: a narrative always covers all of the subject's sessions.
    transcript_id: int | None = None


class NarrativeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    format: NarrativeFormat
    status: JobStatus
    narrative_text: str | None
    share_token: str
    session_ids: list[int]
    model: str | None
    created_at: datetime
    updated_at: datetime


class SharedNarrativeOut(BaseModel):
    """What a public share link shows: the story, nothing about the account behind it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    format: NarrativeFormat
    narrative_text: str | None
    created_at: datetime
