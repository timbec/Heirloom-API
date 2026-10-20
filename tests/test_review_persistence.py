"""Review writes must actually be saved. The usual `client` fixture shares one rolled-back
transaction with each request, so an endpoint that flushes but never commits still passes there.
These tests go through the app's real database sessions (no override) and read back from a fresh
session, then delete what they created."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.models import InterviewSession, Subject, Transcript, TranscriptSource, Turn, User
from app.models.annotation import Annotation
from app.models.plan import SessionPlan
from app.security import hash_password
from tests.conftest import PASSWORD

EMAIL = "review-persist@example.com"
ANSWER = "We went to church every Sunday, St. Stanislaus, everybody did."


@pytest.fixture
async def seeded(migrated_db: None) -> AsyncIterator[dict[str, int]]:
    async with SessionLocal() as db:
        user = User(email=EMAIL, name="Linda", password_hash=hash_password(PASSWORD))
        subject = Subject(user=user, name="Frances")
        session = InterviewSession(subject=subject, title="Session 1")
        transcript = Transcript(
            session=session,
            transcript_text=f"Q: Church?\nA: {ANSWER}",
            source=TranscriptSource.MANUAL,
        )
        turn = Turn(transcript=transcript, turn_index=0, question="Church?", answer=ANSWER)
        db.add_all([user, turn])
        await db.flush()
        db.add(SessionPlan(transcript_id=transcript.id, content={}, user_selections={}))
        await db.commit()
        ids = {"transcript": transcript.id, "turn": turn.id}
    try:
        yield ids
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(User).where(User.email == EMAIL))
            await db.commit()


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        login = await c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        c.headers["Authorization"] = f"Bearer {login.json()['token']}"
        yield c


async def test_marks_and_selections_are_saved(seeded, api: AsyncClient):
    base = f"/api/heirloom/v1/transcripts/{seeded['transcript']}"
    start = ANSWER.index("St. Stanislaus")
    created = await api.post(
        f"{base}/annotations",
        json={
            "turn_id": seeded["turn"],
            "field": "answer",
            "start": start,
            "end": start + len("St. Stanislaus"),
            "quote": "St. Stanislaus",
            "kind": "keep",
        },
    )
    assert created.status_code == 201
    mark_id = created.json()["id"]

    assert (
        await api.patch(f"{base}/annotations/{mark_id}", json={"body": "her church"})
    ).is_success
    assert (
        await api.put(f"{base}/plan/selections", json={"free_notes": "bring photos"})
    ).is_success

    async with SessionLocal() as db:  # a fresh session sees only committed data
        mark = await db.get(Annotation, mark_id)
        plan = await db.scalar(
            select(SessionPlan).where(SessionPlan.transcript_id == seeded["transcript"])
        )
    assert mark is not None and mark.body == "her church"
    assert plan.user_selections["free_notes"] == "bring photos"

    assert (await api.delete(f"{base}/annotations/{mark_id}")).status_code == 204
    async with SessionLocal() as db:
        assert await db.get(Annotation, mark_id) is None
