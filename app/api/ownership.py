"""Load a resource by id and check it belongs to the current user.

404 if it doesn't exist, 403 {"message": "Forbidden"} if it's someone else's (as Laravel did).
Ownership always comes from the subject: sessions and everything below inherit it.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import InterviewSession, Subject, User


def _check_owner(owner_id: int, user: User) -> None:
    if owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


async def get_owned_subject(db: AsyncSession, subject_id: int, user: User) -> Subject:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found.")
    _check_owner(subject.user_id, user)
    return subject


async def get_owned_session(db: AsyncSession, session_id: int, user: User) -> InterviewSession:
    session = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(joinedload(InterviewSession.subject))
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _check_owner(session.subject.user_id, user)
    return session
