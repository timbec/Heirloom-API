from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_transcript
from app.models import Turn
from app.schemas.turn import TurnOut
from app.services.turn_scoring import rescore_transcript
from app.services.turns import TurnParseError

router = APIRouter(prefix="/transcripts/{transcript_id}/turns", tags=["turns"])


@router.post("/score", response_model=list[TurnOut], status_code=201)
async def score_transcript(transcript_id: int, db: DB, user: CurrentUser) -> list[TurnOut]:
    """Split the transcript into turns (replacing any earlier ones) and score each one.
    Turns that fail to score are kept unscored (scored_at null). Synchronous for now."""
    transcript = await get_owned_transcript(db, transcript_id, user)
    try:
        turns, scored = await rescore_transcript(db, transcript)
    except TurnParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not scored:
        raise HTTPException(status_code=502, detail="Scoring failed. Please try again.")
    return [TurnOut.model_validate(t) for t in turns]


@router.get("", response_model=list[TurnOut])
async def list_turns(transcript_id: int, db: DB, user: CurrentUser) -> list[TurnOut]:
    transcript = await get_owned_transcript(db, transcript_id, user)
    turns = await db.scalars(
        select(Turn).where(Turn.transcript_id == transcript.id).order_by(Turn.turn_index)
    )
    return [TurnOut.model_validate(t) for t in turns]
