from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_subject
from app.models import JobStatus, Narrative
from app.schemas.common import ListResponse
from app.schemas.narrative import NarrativeCreate, NarrativeOut, SharedNarrativeOut
from app.services.groq import AIError
from app.services.narratives import NoTranscriptsError, generate_narrative

router = APIRouter(tags=["narratives"])
# Public, no auth: mounted at /api/heirloom/share/{token}.
share_router = APIRouter(tags=["narratives"])


@router.post("/subjects/{subject_id}/narratives", response_model=NarrativeOut, status_code=201)
async def create_narrative(
    subject_id: int, payload: NarrativeCreate, db: DB, user: CurrentUser
) -> NarrativeOut:
    """Generate a new narrative version from all of the subject's transcribed sessions.
    Synchronous for now (can take up to two minutes); moves to a background job later."""
    subject = await get_owned_subject(db, subject_id, user)
    try:
        narrative = await generate_narrative(db, subject, payload.format)
    except NoTranscriptsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AIError as exc:
        raise HTTPException(
            status_code=502, detail="Narrative generation failed. Please try again."
        ) from exc
    return NarrativeOut.model_validate(narrative)


@router.get("/subjects/{subject_id}/narratives", response_model=ListResponse[NarrativeOut])
async def list_narratives(subject_id: int, db: DB, user: CurrentUser) -> ListResponse[NarrativeOut]:
    """Every version for the subject, newest first, failed attempts included."""
    subject = await get_owned_subject(db, subject_id, user)
    narratives = await db.scalars(
        select(Narrative).where(Narrative.subject_id == subject.id).order_by(Narrative.id.desc())
    )
    return ListResponse(data=[NarrativeOut.model_validate(n) for n in narratives])


@router.get("/narratives/{narrative_id}", response_model=NarrativeOut)
async def get_narrative(narrative_id: int, db: DB, user: CurrentUser) -> NarrativeOut:
    narrative = await db.scalar(
        select(Narrative).where(Narrative.id == narrative_id).options(joinedload(Narrative.subject))
    )
    if narrative is None:
        raise HTTPException(status_code=404, detail="Narrative not found.")
    if narrative.subject.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return NarrativeOut.model_validate(narrative)


@share_router.get("/share/{token}", response_model=SharedNarrativeOut)
async def get_shared_narrative(token: str, db: DB) -> SharedNarrativeOut:
    narrative = await db.scalar(
        select(Narrative).where(
            Narrative.share_token == token, Narrative.status == JobStatus.COMPLETED
        )
    )
    if narrative is None:
        raise HTTPException(status_code=404, detail="Narrative not found.")
    return SharedNarrativeOut.model_validate(narrative)
