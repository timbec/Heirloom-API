"""Tests for the review feature: owner scoping, annotation re-anchoring,
system annotation regeneration, export, and null handling."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.annotation import Annotation
from app.models.plan import SessionPlan
from app.models.session import InterviewSession, JobStatus, Transcript, Turn
from app.models.subject import Subject
from app.models.enums import TranscriptSource
from app.services.annotations import reanchor, regenerate_system_annotations
from tests.conftest import make_user, login_headers

# ─── Fixtures ────────────────────────────────────────────────────────────────


async def make_transcript(
    db: AsyncSession,
    user,
    *,
    turns: list[dict] | None = None,
    scored: bool = False,
) -> tuple[Subject, InterviewSession, Transcript]:
    subject = Subject(user_id=user.id, name="Frances")
    db.add(subject)
    await db.flush()

    session = InterviewSession(subject_id=subject.id, title="Session 1")
    db.add(session)
    await db.flush()

    transcript = Transcript(
        session_id=session.id,
        transcript_text="Q: Hello\nA: World",
        status=JobStatus.COMPLETED,
        source=TranscriptSource.MANUAL,
    )
    db.add(transcript)
    await db.flush()

    if turns is None:
        turns = [
            {
                "turn_index": 1,
                "question": "Where did you grow up?",
                "answer": "Fourth Street. He'd come home all black. There was a porch.",
                **({"gold_quote": "He'd come home all black."} if scored else {}),
            }
        ]

    for t in turns:
        turn = Turn(
            transcript_id=transcript.id,
            turn_index=t["turn_index"],
            question=t["question"],
            answer=t["answer"],
            gold_quote=t.get("gold_quote"),
            thread_anchor=t.get("thread_anchor"),
            retracted=t.get("retracted"),
            unable_to_recall=t.get("unable_to_recall"),
            repeat_of=t.get("repeat_of"),
        )
        db.add(turn)
    await db.flush()

    return subject, session, transcript


BASE = "/api/heirloom/v1/transcripts"


# ─── Owner scoping ────────────────────────────────────────────────────────────


async def test_get_review_forbidden_for_other_user(
    client: AsyncClient, db: AsyncSession, user
) -> None:
    _, _, transcript = await make_transcript(db, user)
    other = await make_user(db, email="other@example.com")
    headers = await login_headers(client, other)
    r = await client.get(f"{BASE}/{transcript.id}/review", headers=headers)
    assert r.status_code in (403, 404)


async def test_create_annotation_forbidden_for_other_user(
    client: AsyncClient, db: AsyncSession, user
) -> None:
    _, _, transcript = await make_transcript(db, user)
    other = await make_user(db, email="other2@example.com")
    headers = await login_headers(client, other)
    r = await client.post(
        f"{BASE}/{transcript.id}/annotations",
        json={
            "turn_id": 999,
            "field": "answer",
            "start": 0,
            "end": 5,
            "quote": "hello",
            "kind": "keep",
        },
        headers=headers,
    )
    assert r.status_code in (403, 404)


async def test_export_forbidden_for_other_user(
    client: AsyncClient, db: AsyncSession, user
) -> None:
    _, _, transcript = await make_transcript(db, user)
    other = await make_user(db, email="other3@example.com")
    headers = await login_headers(client, other)
    r = await client.get(f"{BASE}/{transcript.id}/export.md", headers=headers)
    assert r.status_code in (403, 404)


async def test_patch_annotation_forbidden_for_other_user(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    _, _, transcript = await make_transcript(db, user)

    # Create an annotation as the owner first.
    from sqlalchemy import select
    turns = (await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(Turn)
        .where(Turn.transcript_id == transcript.id)
    )).scalars().all()
    turn = turns[0]
    ann = Annotation(
        transcript_id=transcript.id,
        turn_id=turn.id,
        field="answer",
        start=0,
        end=5,
        quote=turn.answer[:5],
        author="user",
        kind="keep",
        dismissed=False,
    )
    db.add(ann)
    await db.flush()

    other = await make_user(db, email="other4@example.com")
    headers = await login_headers(client, other)
    r = await client.patch(
        f"{BASE}/{transcript.id}/annotations/{ann.id}",
        json={"kind": "chase"},
        headers=headers,
    )
    assert r.status_code in (403, 404)


# ─── Annotation re-anchoring ──────────────────────────────────────────────────


def test_reanchor_exact_match_returns_stored_offsets() -> None:
    ann = Annotation(
        transcript_id=1, turn_id=1, field="answer",
        start=5, end=10, quote="hello", author="user", kind="keep",
    )
    text = "say: hello world"
    ann.start, ann.end = 5, 10
    ann.quote = "hello"
    result = reanchor(ann, "say: hello world")
    assert result == (5, 10)


def test_reanchor_finds_shifted_quote() -> None:
    text_original = "Fourth Street. He'd come home all black."
    text_shifted = "He'd come home all black. Extra words added."
    ann = Annotation(
        transcript_id=1, turn_id=1, field="answer",
        start=15, end=39, quote="He'd come home all black.",
        author="system", kind="keep",
    )
    # Offsets no longer match (text changed), but quote is present.
    result = reanchor(ann, text_shifted)
    assert result is not None
    start, end = result
    assert text_shifted[start:end] == "He'd come home all black."


def test_reanchor_returns_none_when_not_found() -> None:
    ann = Annotation(
        transcript_id=1, turn_id=1, field="answer",
        start=0, end=5, quote="xyzzy",
        author="system", kind="keep",
    )
    result = reanchor(ann, "completely different text")
    assert result is None


def test_reanchor_normalises_whitespace() -> None:
    text = "She had — her hands  were always red."
    ann = Annotation(
        transcript_id=1, turn_id=1, field="answer",
        start=999, end=999, quote="her hands were always red.",
        author="system", kind="keep",
    )
    result = reanchor(ann, text)
    assert result is not None
    start, end = result
    assert "hands" in text[start:end]


# ─── System annotation regeneration ──────────────────────────────────────────


async def test_regenerate_creates_system_annotations(db: AsyncSession, user) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "Fourth Street. He'd come home all black. There was a porch.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    await regenerate_system_annotations(db, transcript)

    from sqlalchemy import select
    anns = (await db.execute(
        select(Annotation).where(Annotation.transcript_id == transcript.id)
    )).scalars().all()

    keep_anns = [a for a in anns if a.kind == "keep" and a.author == "system"]
    assert len(keep_anns) == 1
    ann = keep_anns[0]
    assert ann.quote == "He'd come home all black."


async def test_regenerate_updates_existing_annotation(db: AsyncSession, user) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "He'd come home all black. There was a porch.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    await regenerate_system_annotations(db, transcript)

    # Update gold_quote.
    from sqlalchemy import select
    turn = (await db.execute(
        select(Turn).where(Turn.transcript_id == transcript.id)
    )).scalar_one()
    turn.gold_quote = "There was a porch."
    await db.flush()

    await regenerate_system_annotations(db, transcript)

    anns = (await db.execute(
        select(Annotation).where(Annotation.transcript_id == transcript.id, Annotation.kind == "keep")
    )).scalars().all()
    assert len(anns) == 1
    assert anns[0].quote == "There was a porch."


async def test_regenerate_does_not_touch_user_annotations(db: AsyncSession, user) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "He'd come home all black. There was a porch.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    from sqlalchemy import select
    turn = (await db.execute(
        select(Turn).where(Turn.transcript_id == transcript.id)
    )).scalar_one()

    # Add a user annotation.
    user_ann = Annotation(
        transcript_id=transcript.id,
        turn_id=turn.id,
        field="answer",
        start=0,
        end=5,
        quote=turn.answer[:5],
        author="user",
        kind="chase",
    )
    db.add(user_ann)
    await db.flush()

    await regenerate_system_annotations(db, transcript)

    anns = (await db.execute(
        select(Annotation).where(Annotation.transcript_id == transcript.id)
    )).scalars().all()
    user_anns = [a for a in anns if a.author == "user"]
    assert len(user_anns) == 1
    assert user_anns[0].id == user_ann.id


async def test_regenerate_preserves_dismissed_state(db: AsyncSession, user) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "He'd come home all black.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    await regenerate_system_annotations(db, transcript)

    from sqlalchemy import select
    ann = (await db.execute(
        select(Annotation).where(
            Annotation.transcript_id == transcript.id, Annotation.kind == "keep"
        )
    )).scalar_one()
    ann.dismissed = True
    await db.flush()

    # Re-run — dismissed should be preserved.
    await regenerate_system_annotations(db, transcript)
    await db.refresh(ann)
    assert ann.dismissed is True


async def test_regenerate_removes_annotation_when_source_cleared(db: AsyncSession, user) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "He'd come home all black.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    await regenerate_system_annotations(db, transcript)

    from sqlalchemy import select
    turn = (await db.execute(
        select(Turn).where(Turn.transcript_id == transcript.id)
    )).scalar_one()
    turn.gold_quote = None
    await db.flush()

    await regenerate_system_annotations(db, transcript)

    anns = (await db.execute(
        select(Annotation).where(
            Annotation.transcript_id == transcript.id, Annotation.kind == "keep"
        )
    )).scalars().all()
    assert len(anns) == 0


# ─── Retracted excluded from export ──────────────────────────────────────────


async def test_retracted_turn_excluded_from_export(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    _, _, transcript = await make_transcript(
        db, user,
        turns=[
            {
                "turn_index": 1,
                "question": "Q1",
                "answer": "This answer is visible.",
            },
            {
                "turn_index": 2,
                "question": "Q2",
                "answer": "Don't put that in.",
                "retracted": True,
            },
        ],
    )
    r = await client.get(f"{BASE}/{transcript.id}/export.md", headers=auth_headers)
    assert r.status_code == 200
    body = r.text
    assert "This answer is visible." in body
    assert "Don't put that in." not in body


# ─── Null handling ────────────────────────────────────────────────────────────


async def test_get_review_no_plan_returns_null(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    _, _, transcript = await make_transcript(db, user)
    r = await client.get(f"{BASE}/{transcript.id}/review", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["plan"] is None


async def test_get_review_unscored_transcript_has_empty_annotations(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    _, _, transcript = await make_transcript(db, user)
    r = await client.get(f"{BASE}/{transcript.id}/review", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    for turn in data["turns"]:
        assert turn["annotations"] == []


# ─── Annotation span validation ───────────────────────────────────────────────


async def test_create_annotation_validates_quote_matches_offsets(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    _, _, transcript = await make_transcript(db, user)
    from sqlalchemy import select
    turn = (await db.execute(
        select(Turn).where(Turn.transcript_id == transcript.id)
    )).scalar_one()

    # Correct span.
    correct_quote = turn.answer[0:5]
    r = await client.post(
        f"{BASE}/{transcript.id}/annotations",
        json={
            "turn_id": turn.id,
            "field": "answer",
            "start": 0,
            "end": 5,
            "quote": correct_quote,
            "kind": "keep",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201

    # Wrong quote for same offsets.
    r = await client.post(
        f"{BASE}/{transcript.id}/annotations",
        json={
            "turn_id": turn.id,
            "field": "answer",
            "start": 0,
            "end": 5,
            "quote": "WRONG",
            "kind": "keep",
        },
        headers=auth_headers,
    )
    assert r.status_code == 422


async def test_returned_annotation_is_exact_substring(
    client: AsyncClient, db: AsyncSession, user, auth_headers
) -> None:
    """Every anchored span returned by GET /review must be an exact substring of turn text."""
    _, _, transcript = await make_transcript(
        db, user,
        turns=[{
            "turn_index": 1,
            "question": "Q",
            "answer": "Fourth Street. He'd come home all black. There was a porch.",
            "gold_quote": "He'd come home all black.",
        }],
    )
    await regenerate_system_annotations(db, transcript)

    r = await client.get(f"{BASE}/{transcript.id}/review", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    for turn in data["turns"]:
        for ann in turn["annotations"]:
            if ann["anchored"]:
                start, end = ann["start"], ann["end"]
                text = turn["answer"] if ann["field"] == "answer" else turn["question"]
                assert text[start:end] == ann["quote"]
