from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_session
from app.config import get_settings
from app.models import (
    InterviewSession,
    JobStatus,
    SessionStatus,
    Transcript,
    TranscriptSource,
    Turn,
)
from app.schemas.transcript import ManualTranscriptCreate, TranscriptOut
from app.services.groq import AIError, transcribe_audio
from app.services.storage import FileTooLargeError, absolute_path, save_upload

router = APIRouter(prefix="/sessions/{session_id}", tags=["transcripts"])

AUDIO_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
TRANSCRIPTION_TIMEOUT_SECONDS = 300


async def _save_transcript(
    db: DB,
    session: InterviewSession,
    text: str,
    source: TranscriptSource,
    response: Response,
    duration_seconds: int | None = None,
) -> Transcript:
    """Create the session's transcript, or replace it (200 instead of 201), clearing its turns,
    which no longer match the text. Marks the session transcribed."""
    transcript = await db.scalar(select(Transcript).where(Transcript.session_id == session.id))
    if transcript is None:
        transcript = Transcript(session_id=session.id)
        db.add(transcript)
    else:
        await db.execute(delete(Turn).where(Turn.transcript_id == transcript.id))
        response.status_code = 200

    transcript.transcript_text = text
    transcript.source = source
    transcript.status = JobStatus.COMPLETED
    transcript.duration_seconds = duration_seconds
    session.status = SessionStatus.TRANSCRIBED
    await db.commit()
    return transcript


def _audio_error(message: str) -> JSONResponse:
    return JSONResponse({"message": message, "errors": {"audio": [message]}}, status_code=422)


@router.post("/transcript", response_model=TranscriptOut, status_code=201)
async def save_manual_transcript(
    session_id: int, payload: ManualTranscriptCreate, db: DB, user: CurrentUser, response: Response
) -> TranscriptOut:
    """Save a typed-in transcript (replaces any existing one)."""
    session = await get_owned_session(db, session_id, user)
    transcript = await _save_transcript(
        db, session, payload.transcript_text, TranscriptSource.MANUAL, response
    )
    return TranscriptOut.model_validate(transcript)


@router.post("/transcribe", response_model=TranscriptOut, status_code=201)
async def transcribe_session_audio(
    session_id: int,
    audio: Annotated[UploadFile, File()],
    db: DB,
    user: CurrentUser,
    response: Response,
) -> TranscriptOut | JSONResponse:
    """Upload a recording, keep the original, and transcribe it with Whisper (replaces any
    existing transcript). Synchronous for now; moves to a background job later."""
    session = await get_owned_session(db, session_id, user)
    settings = get_settings()

    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in AUDIO_EXTENSIONS))
        return _audio_error(f"The audio must be a file of type: {allowed}.")

    # Keep the original before transcribing, so it survives a failed transcription.
    try:
        session.audio_path = await save_upload(
            audio, f"audio/session-{session.id}", suffix, settings.max_audio_mb * 1024 * 1024
        )
    except FileTooLargeError:
        return _audio_error(f"The audio must not be larger than {settings.max_audio_mb} MB.")
    await db.commit()

    try:
        text, duration = await transcribe_audio(
            absolute_path(session.audio_path),
            filename=audio.filename or f"audio{suffix}",
            model=settings.groq_transcription_model,
            timeout_seconds=TRANSCRIPTION_TIMEOUT_SECONDS,
        )
    except AIError as exc:
        raise HTTPException(
            status_code=502, detail="Transcription failed. Please try again."
        ) from exc

    seconds = round(duration) if duration is not None else None
    session.duration_seconds = seconds
    transcript = await _save_transcript(
        db, session, text, TranscriptSource.AUDIO, response, duration_seconds=seconds
    )
    return TranscriptOut.model_validate(transcript)


@router.get("/transcript", response_model=TranscriptOut)
async def get_transcript(session_id: int, db: DB, user: CurrentUser) -> TranscriptOut:
    session = await get_owned_session(db, session_id, user)
    transcript = await db.scalar(select(Transcript).where(Transcript.session_id == session.id))
    if transcript is None:
        raise HTTPException(status_code=404, detail="No transcript found")
    return TranscriptOut.model_validate(transcript)
