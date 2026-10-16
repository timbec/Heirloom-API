from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_session
from app.models import JobStatus, SessionStatus, Transcript, TranscriptSource, Turn
from app.schemas.transcript import ManualTranscriptCreate, TranscriptOut

router = APIRouter(prefix="/sessions/{session_id}", tags=["transcripts"])


@router.post("/transcript", response_model=TranscriptOut, status_code=201)
async def save_manual_transcript(
    session_id: int, payload: ManualTranscriptCreate, db: DB, user: CurrentUser, response: Response
) -> TranscriptOut:
    """Save a typed-in transcript. A session has one transcript, so posting again replaces it
    (200 instead of 201) and clears its turns, which no longer match the text."""
    session = await get_owned_session(db, session_id, user)
    transcript = await db.scalar(select(Transcript).where(Transcript.session_id == session.id))

    if transcript is None:
        transcript = Transcript(session_id=session.id)
        db.add(transcript)
    else:
        await db.execute(delete(Turn).where(Turn.transcript_id == transcript.id))
        response.status_code = 200

    transcript.transcript_text = payload.transcript_text
    transcript.source = TranscriptSource.MANUAL
    transcript.status = JobStatus.COMPLETED
    session.status = SessionStatus.TRANSCRIBED
    await db.commit()
    return TranscriptOut.model_validate(transcript)


@router.get("/transcript", response_model=TranscriptOut)
async def get_transcript(session_id: int, db: DB, user: CurrentUser) -> TranscriptOut:
    session = await get_owned_session(db, session_id, user)
    transcript = await db.scalar(select(Transcript).where(Transcript.session_id == session.id))
    if transcript is None:
        raise HTTPException(status_code=404, detail="No transcript found")
    return TranscriptOut.model_validate(transcript)
