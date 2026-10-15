from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_session
from app.models import InterviewSession, SessionStatus, Subject
from app.schemas.common import ListResponse
from app.schemas.session import SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=ListResponse[SessionOut])
async def list_sessions(
    db: DB, user: CurrentUser, subject_id: int | None = None
) -> ListResponse[SessionOut]:
    """The user's sessions, newest first, optionally for one subject."""
    query = (
        select(InterviewSession)
        .join(InterviewSession.subject)
        .where(Subject.user_id == user.id)
        .options(joinedload(InterviewSession.subject))
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
    )
    if subject_id is not None:
        query = query.where(InterviewSession.subject_id == subject_id)
    sessions = await db.scalars(query)
    return ListResponse(data=[SessionOut.model_validate(s) for s in sessions])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    payload: SessionCreate, db: DB, user: CurrentUser
) -> SessionOut | JSONResponse:
    subject = await db.get(Subject, payload.subject_id)
    if subject is None or subject.user_id != user.id:
        # Someone else's subject looks the same as a missing one, so ids can't be probed.
        message = "The selected subject id is invalid."
        return JSONResponse(
            {"message": message, "errors": {"subject_id": [message]}}, status_code=422
        )

    session = InterviewSession(
        **payload.model_dump(exclude={"subject_id"}),
        subject=subject,
        status=SessionStatus.PENDING,
    )
    db.add(session)
    await db.commit()
    return SessionOut.model_validate(session)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, db: DB, user: CurrentUser) -> SessionOut:
    return SessionOut.model_validate(await get_owned_session(db, session_id, user))
