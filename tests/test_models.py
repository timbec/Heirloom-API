import subprocess

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InterviewSession,
    JobStatus,
    Narrative,
    NarrativeFormat,
    SessionStatus,
    Subject,
    Transcript,
    TranscriptSource,
    Turn,
    User,
)


async def make_story(db: AsyncSession, email: str = "Ada@Example.com") -> User:
    """A user with one subject, one session, its transcript, two turns and a narrative."""
    user = User(email=email, name="Ada", password_hash="x")
    subject = Subject(user=user, name="Grandma Rose", birth_year=1938)
    session = InterviewSession(subject=subject, title="Childhood")
    transcript = Transcript(
        session=session,
        transcript_text="Q: Where were you born? A: Leeds.",
        source=TranscriptSource.MANUAL,
    )
    transcript.turns = [
        Turn(turn_index=0, question="Where were you born?", answer="Leeds."),
        Turn(turn_index=1, question="And then?", answer="We moved."),
    ]
    subject.narratives = [Narrative(format=NarrativeFormat.MEMOIR)]
    db.add(user)
    await db.flush()
    return user


async def count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def test_migrations_match_models(migrated_db: None) -> None:
    """Fails if a model changed without a migration (alembic check runs autogenerate)."""
    result = subprocess.run(["alembic", "check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


async def test_defaults(db: AsyncSession) -> None:
    user = await make_story(db)
    subject = user.subjects[0]
    session = subject.sessions[0]
    narrative = subject.narratives[0]

    assert user.email == "ada@example.com"
    assert user.is_admin is False
    assert user.created_at is not None
    assert user.updated_at is not None
    assert session.status == SessionStatus.PENDING
    assert session.transcript.status == JobStatus.PENDING
    assert session.transcript.language == "en"
    assert narrative.status == JobStatus.PENDING
    assert len(narrative.share_token) == 32


async def test_enums_stored_as_plain_strings(db: AsyncSession) -> None:
    await make_story(db)
    raw = await db.scalar(select(func.cast(InterviewSession.status, Subject.name.type)))
    assert raw == "pending"


async def test_deleting_subject_cascades_to_everything_below(db: AsyncSession) -> None:
    user = await make_story(db)
    await db.delete(user.subjects[0])
    await db.flush()

    for model in (Subject, InterviewSession, Transcript, Turn, Narrative):
        assert await count(db, model) == 0, model.__name__
    assert await count(db, User) == 1


async def test_deleting_user_cascades(db: AsyncSession) -> None:
    user = await make_story(db)
    await db.delete(user)
    await db.flush()
    assert await count(db, Subject) == 0
    assert await count(db, Turn) == 0


async def test_email_unique_case_insensitively(db: AsyncSession) -> None:
    await make_story(db, email="ada@example.com")
    db.add(User(email="ADA@example.com ", name="Imposter", password_hash="x"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_one_transcript_per_session(db: AsyncSession) -> None:
    user = await make_story(db)
    session = user.subjects[0].sessions[0]
    db.add(Transcript(session_id=session.id, transcript_text="again", source="manual"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_turn_index_unique_per_transcript(db: AsyncSession) -> None:
    user = await make_story(db)
    transcript = user.subjects[0].sessions[0].transcript
    db.add(Turn(transcript_id=transcript.id, turn_index=0, question="Q", answer="A"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_one_narrative_per_subject_and_format(db: AsyncSession) -> None:
    user = await make_story(db)
    subject = user.subjects[0]
    db.add(Narrative(subject_id=subject.id, format=NarrativeFormat.LETTER))
    await db.flush()  # a different format is fine
    db.add(Narrative(subject_id=subject.id, format=NarrativeFormat.MEMOIR))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_scores_must_be_0_to_10(db: AsyncSession) -> None:
    user = await make_story(db)
    turn = user.subjects[0].sessions[0].transcript.turns[0]
    turn.specificity = 11
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_invalid_enum_value_rejected(db: AsyncSession) -> None:
    user = await make_story(db)
    user.subjects[0].sessions[0].status = "archived"
    with pytest.raises(StatementError):
        await db.flush()
