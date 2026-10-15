from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_subject
from app.models import InterviewSession, Subject
from app.schemas.common import ListResponse, MessageResponse
from app.schemas.subject import SubjectCreate, SubjectFields, SubjectOut, SubjectUpdate

router = APIRouter(prefix="/subjects", tags=["subjects"])

_sessions_count = (
    select(func.count(InterviewSession.id))
    .where(InterviewSession.subject_id == Subject.id)
    .correlate(Subject)
    .scalar_subquery()
)


def _out(subject: Subject, sessions_count: int) -> SubjectOut:
    fields = SubjectFields.model_validate(subject).model_dump()
    return SubjectOut(**fields, sessions_count=sessions_count)


async def _count_sessions(db: DB, subject: Subject) -> int:
    return await db.scalar(select(_sessions_count).where(Subject.id == subject.id))


@router.get("", response_model=ListResponse[SubjectOut])
async def list_subjects(db: DB, user: CurrentUser) -> ListResponse[SubjectOut]:
    """Every subject the user owns, unpaginated: the frontend resolves slugs from this list."""
    rows = await db.execute(
        select(Subject, _sessions_count).where(Subject.user_id == user.id).order_by(Subject.id)
    )
    return ListResponse(data=[_out(subject, count) for subject, count in rows])


@router.post("", response_model=SubjectOut, status_code=201)
async def create_subject(payload: SubjectCreate, db: DB, user: CurrentUser) -> SubjectOut:
    subject = Subject(**payload.model_dump(), user_id=user.id)
    db.add(subject)
    await db.commit()
    return _out(subject, 0)


@router.get("/{subject_id}", response_model=SubjectOut)
async def get_subject(subject_id: int, db: DB, user: CurrentUser) -> SubjectOut:
    subject = await get_owned_subject(db, subject_id, user)
    return _out(subject, await _count_sessions(db, subject))


@router.put("/{subject_id}", response_model=SubjectOut)
@router.patch("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: int, payload: SubjectUpdate, db: DB, user: CurrentUser
) -> SubjectOut:
    subject = await get_owned_subject(db, subject_id, user)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name", "") is None:
        changes.pop("name")  # name can't be cleared
    for field, value in changes.items():
        setattr(subject, field, value)
    await db.commit()
    return _out(subject, await _count_sessions(db, subject))


@router.delete("/{subject_id}", response_model=MessageResponse)
async def delete_subject(subject_id: int, db: DB, user: CurrentUser) -> MessageResponse:
    """Deletes the subject and, via the database cascade, everything recorded about them."""
    subject = await get_owned_subject(db, subject_id, user)
    await db.delete(subject)
    await db.commit()
    return MessageResponse(message="Deleted")
