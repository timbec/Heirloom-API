from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ThreadType


class TurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transcript_id: int
    turn_index: int
    question: str
    answer: str
    specificity: int | None
    emotional_charge: int | None
    thread_type: ThreadType | None
    is_gold: bool
    gold_quote: str | None
    open_thread: str | None
    scored_at: datetime | None
    created_at: datetime
    updated_at: datetime
