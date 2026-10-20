"""The admin's read-only Review page. The admin uses its own database sessions, so these tests
commit real rows and delete them afterwards (like tests/test_admin.py)."""

import re
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import InterviewSession, Subject, Transcript, TranscriptSource, Turn, User
from app.models.annotation import Annotation
from app.models.plan import SessionPlan
from app.security import hash_password
from app.services.review_render import PlacedAnnotation, build_pieces, note_text
from tests.conftest import PASSWORD

ADMIN = "review-admin@example.com"
OWNER = "review-owner@example.com"
ANSWER = "Pierogi. [pause] Her hands were always red. Lard! <b>not markup</b> I don't know why."


def ann(turn: Turn, quote: str, **kw) -> Annotation:
    start = turn.answer.find(quote) if quote else 0
    return Annotation(
        turn=turn,
        transcript=turn.transcript,
        field="answer",
        start=max(start, 0),
        end=max(start, 0) + len(quote),
        quote=quote,
        **{"author": "system", "dismissed": False, "body": None, **kw},
    )


@pytest.fixture
async def seeded(migrated_db: None) -> AsyncIterator[dict[str, int]]:
    async with SessionLocal() as db:
        admin = User(
            email=ADMIN, name="Admin", password_hash=hash_password(PASSWORD), is_admin=True
        )
        owner = User(email=OWNER, name="Linda", password_hash=hash_password(PASSWORD))
        subject = Subject(user=owner, name="Frances")
        session = InterviewSession(subject=subject, title="Session 1")
        transcript = Transcript(
            session=session, transcript_text="Q: Cook?\nA: ...", source=TranscriptSource.MANUAL
        )
        turn = Turn(transcript=transcript, turn_index=0, question="Did she cook?", answer=ANSWER)
        empty_transcript = Transcript(
            session=InterviewSession(subject=subject, title="Session 2"),
            transcript_text="Q: Hi\nA: Hello",
            source=TranscriptSource.MANUAL,
        )
        db.add_all([admin, owner, turn, empty_transcript])
        db.add_all(
            [
                ann(
                    turn,
                    "Her hands were always red.",
                    kind="keep",
                    body="Something only she remembers.",
                ),
                ann(turn, "Pierogi.", kind="leave", dismissed=True, body="Stock answer."),
                ann(turn, "Lard!", author="user", kind="chase"),
                ann(turn, "a phrase that was edited away", author="user", kind="keep"),
                ann(turn, "", author="user", kind="note", body="Ask about her rings."),
            ]
        )
        await db.flush()
        db.add(
            SessionPlan(
                transcript_id=transcript.id,
                content={
                    "intro": "Ask about objects.",
                    "threads": [
                        {
                            "title": "Her mother's hands",
                            "why": "Only she would remember.",
                            "turn_refs": [0],
                            "questions": ["What else did she do with them?", "Who taught you?"],
                            "directions": ["The kitchen as a room"],
                        }
                    ],
                    "leave_alone": [{"label": "Walt", "why": "Asked to leave out.", "out": True}],
                    "covered": [{"label": "The wedding year", "why": "Settled."}],
                    "how_to_ask": {"try_instead": "Ask for a scene.", "what_worked": "Patience."},
                    "bring": ["A nickel"],
                    "for_narrative": ["Leave out Walt"],
                },
                user_selections={
                    "picked_questions": {"0:1": True},
                    "picked_directions": {},
                    "own_questions": ["What was your first car?"],
                    "free_notes": "She was tired.",
                    "edited_questions": {"q:0:1": "Who taught you to make the dough?"},
                },
            )
        )
        await db.commit()
        ids = {"transcript": transcript.id, "empty": empty_transcript.id}
    try:
        yield ids
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(User).where(User.email.in_([ADMIN, OWNER])))
            await db.commit()


@pytest.fixture
async def admin_browser() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(c: AsyncClient) -> None:
    response = await c.post("/admin/login", data={"username": ADMIN, "password": PASSWORD})
    assert response.status_code in (302, 303)


def review_url(pk: int) -> str:
    return f"/admin/transcript/action/view-review?pks={pk}"


async def test_requires_admin_login(admin_browser: AsyncClient, seeded):
    response = await admin_browser.get(review_url(seeded["transcript"]))
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/admin/login")


async def test_review_shows_marks_notes_and_memo(admin_browser: AsyncClient, seeded):
    await login(admin_browser)
    page = (await admin_browser.get(review_url(seeded["transcript"]))).text

    # Marks: system highlight, user follow-up (green), stage direction; dismissed mark not drawn.
    assert '<span class="k-keep">Her hands were always red.</span>' in page
    assert '<span class="mine m-chase">Lard!</span>' in page
    assert '<span class="stage">[pause]</span>' in page
    assert "k-leave" not in re.sub(r"<style>.*?</style>", "", page, flags=re.S)

    # Notes, distinguished by author; dismissal and unanchored states shown.
    assert "Something only she remembers." in page
    assert "(user disagreed)" in page
    assert page.count('<span class="tag user">User</span>') >= 3  # mark, lost mark, note
    assert "Ask about her rings." in page
    assert "No longer found in the text" in page
    assert OWNER in page

    # Memo with the user's ticks, edits, own questions and notes.
    assert "Who taught you to make the dough?" in page and "edited" in page
    assert "☑" in page and "☐" in page
    assert "What was your first car?" in page and "She was tired." in page
    assert 'href="#t-0">Exchange 1</a>' in page


async def test_review_is_read_only_and_escaped(admin_browser: AsyncClient, seeded):
    await login(admin_browser)
    page = (await admin_browser.get(review_url(seeded["transcript"]))).text
    assert "<b>not markup</b>" not in page
    assert "&lt;b&gt;not markup&lt;/b&gt;" in page
    content = page.split('class="hr"', 1)[1]
    assert "<textarea" not in content and "contenteditable" not in content
    assert "<input" not in content and "<form" not in content


async def test_review_empty_states(admin_browser: AsyncClient, seeded):
    await login(admin_browser)
    page = (await admin_browser.get(review_url(seeded["empty"]))).text
    assert "hasn't been scored yet" in page
    assert "No plan for this session yet." in page


async def test_review_is_linked_from_transcript_and_turns_pages(admin_browser: AsyncClient, seeded):
    await login(admin_browser)
    detail = (await admin_browser.get(f"/admin/transcript/details/{seeded['transcript']}")).text
    assert "action/view-review" in detail
    turns = (
        await admin_browser.get(f"/admin/transcript/action/view-turns?pks={seeded['transcript']}")
    ).text
    assert "action/view-review" in turns


def placed(text: str, quote: str, author: str = "system", kind: str = "keep") -> PlacedAnnotation:
    start = text.index(quote)
    a = SimpleNamespace(author=author, kind=kind, dismissed=False, field="answer", quote=quote)
    return PlacedAnnotation(a, start, start + len(quote))  # type: ignore[arg-type]


def test_pieces_rejoin_exactly_and_combine_overlaps():
    text = "Every day. Never said a word. [pause] A nickel under the saucer."
    marks = [
        placed(text, "Never said a word. [pause] A nickel"),
        placed(text, "A nickel", "user", "chase"),
    ]
    pieces = build_pieces(text, marks)
    assert "".join(p.text for p in pieces) == text
    by_text = {p.text: p.classes for p in pieces}
    assert by_text["[pause]"] == ["k-keep", "stage"]
    assert by_text["A nickel"] == ["k-keep", "mine", "m-chase"]
    for p in pieces:  # every highlighted piece is an exact substring
        assert p.text in text


def test_skip_note_label_comes_from_first_sentence():
    note = SimpleNamespace(kind="skip", quote="", body="Settled. June 1958, no need to ask again.")
    assert note_text(note) == ("Settled", "June 1958, no need to ask again.")  # type: ignore[arg-type]
