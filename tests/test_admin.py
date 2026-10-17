"""The admin panel reads through its own database sessions, so these tests commit real rows
(and always delete them afterwards) instead of using the rolled-back `db` fixture."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import InterviewSession, Narrative, Subject, Transcript, TranscriptSource, User
from app.security import hash_password
from tests.conftest import PASSWORD

ADMIN_EMAIL = "admin-test@example.com"
USER_EMAIL = "member-test@example.com"


@pytest.fixture
async def people(migrated_db: None) -> AsyncIterator[dict[str, int]]:
    """An admin, and an ordinary user who owns a subject with a session, transcript and
    narrative. Committed, then removed (the cascade takes the rest)."""
    async with SessionLocal() as db:
        admin = User(
            email=ADMIN_EMAIL, name="Admin", password_hash=hash_password(PASSWORD), is_admin=True
        )
        member = User(email=USER_EMAIL, name="Member", password_hash=hash_password(PASSWORD))
        subject = Subject(user=member, name="Grandma Rose")
        session = InterviewSession(subject=subject, title="Childhood in Leeds")
        session.transcript = Transcript(
            transcript_text="Q: Where?\nA: Leeds, in the back bedroom.",
            source=TranscriptSource.MANUAL,
        )
        subject.narratives = [Narrative(narrative_text="I was born in Leeds.", session_ids=[1])]
        db.add_all([admin, member])
        await db.commit()
        ids = {
            "admin": admin.id,
            "member": member.id,
            "subject": subject.id,
            "transcript": session.transcript.id,
        }
    try:
        yield ids
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(User).where(User.email.in_([ADMIN_EMAIL, USER_EMAIL])))
            await db.commit()


@pytest.fixture
async def browser() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def admin_login(browser: AsyncClient, email: str, password: str = PASSWORD):
    return await browser.post("/admin/login", data={"username": email, "password": password})


async def test_requires_login(browser: AsyncClient, people):
    response = await browser.get("/admin/subject/list")
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/admin/login")


async def test_admin_can_log_in_and_see_everyones_data(browser: AsyncClient, people):
    response = await admin_login(browser, ADMIN_EMAIL.upper())
    assert response.status_code in (302, 303)
    assert not response.headers["location"].endswith("/login")

    for page, expected in [
        ("user", USER_EMAIL),
        ("subject", "Grandma Rose"),
        ("interview-session", "Childhood in Leeds"),
        ("transcript", "Leeds, in the back bedroom"),
        ("narrative", "I was born in Leeds."),
        ("turn", "Turns"),
    ]:
        response = await browser.get(f"/admin/{page}/list")
        assert response.status_code == 200, page
        assert expected in response.text, page


async def test_detail_pages(browser: AsyncClient, people):
    await admin_login(browser, ADMIN_EMAIL)

    response = await browser.get(f"/admin/subject/details/{people['subject']}")
    assert response.status_code == 200
    assert "Childhood in Leeds" in response.text  # its sessions are listed

    response = await browser.get(f"/admin/user/details/{people['member']}")
    assert response.status_code == 200
    assert "argon2" not in response.text  # no password hash on show


@pytest.mark.parametrize(
    ("email", "password"),
    [(USER_EMAIL, PASSWORD), (ADMIN_EMAIL, "wrong password"), ("nobody@example.com", PASSWORD)],
)
async def test_non_admins_and_bad_passwords_are_refused(
    browser: AsyncClient, people, email: str, password: str
):
    response = await admin_login(browser, email, password)
    assert response.status_code == 400  # SQLAdmin re-shows the form with an error
    assert (await browser.get("/admin/subject/list")).status_code in (302, 303)


async def test_removing_admin_flag_locks_out_immediately(browser: AsyncClient, people):
    await admin_login(browser, ADMIN_EMAIL)
    assert (await browser.get("/admin/subject/list")).status_code == 200

    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == people["admin"]).values(is_admin=False))
        await db.commit()
    assert (await browser.get("/admin/subject/list")).status_code in (302, 303)


async def test_login_is_rate_limited(browser: AsyncClient, people):
    for _ in range(5):
        await admin_login(browser, ADMIN_EMAIL, "wrong password")
    response = await admin_login(browser, ADMIN_EMAIL)  # right password, still blocked
    assert response.status_code == 400


GROQ_CHAT = "https://groq.test/openai/v1/chat/completions"


def scoring_reply(**overrides) -> httpx.Response:
    score = {
        "specificity": 8,
        "emotional_charge": 6,
        "thread_type": "new",
        "is_gold": True,
        "gold_quote": "in the back bedroom",
        "open_thread": "the house in Leeds",
        **overrides,
    }
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(score)}}]})


async def test_score_and_view_turns(browser: AsyncClient, people):
    await admin_login(browser, ADMIN_EMAIL)
    view = f"/admin/transcript/action/view-turns?pks={people['transcript']}"
    score = f"/admin/transcript/action/score-turns?pks={people['transcript']}"

    page = await browser.get(view)
    assert page.status_code == 200
    assert "hasn't been split into turns yet" in page.text

    with respx.mock(assert_all_called=False) as mock:
        mock.post(GROQ_CHAT).return_value = scoring_reply()
        response = await browser.get(score)
    assert response.status_code == 303
    assert "view-turns" in response.headers["location"]

    page = await browser.get(response.headers["location"])
    assert page.status_code == 200
    assert "Grandma Rose" in page.text
    assert "★ gold" in page.text
    assert "“in the back bedroom”" in page.text
    assert "the house in Leeds" in page.text
    assert "test-scoring-model, prompt v1" in page.text

    # The detail page offers both buttons.
    detail = await browser.get(f"/admin/transcript/details/{people['transcript']}")
    assert "Score turns" in detail.text and "View turns" in detail.text


async def test_prompt_v2_saves_sensitivity(browser: AsyncClient, people, monkeypatch):
    monkeypatch.setattr(get_settings(), "scoring_prompt", "v2")
    await admin_login(browser, ADMIN_EMAIL)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(GROQ_CHAT)
        route.return_value = scoring_reply(sensitivity="off_record")
        response = await browser.get(
            f"/admin/transcript/action/score-turns?pks={people['transcript']}"
        )
        sent = json.loads(route.calls.last.request.content)
    assert "sensitivity" in sent["messages"][0]["content"]  # the v2 prompt was used

    page = await browser.get(response.headers["location"])
    assert "⛔ off the record" in page.text
    assert "★ gold" not in page.text  # off the record is never gold
    assert "prompt v2" in page.text


async def test_failed_scoring_shows_a_message(browser: AsyncClient, people):
    await admin_login(browser, ADMIN_EMAIL)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(GROQ_CHAT).return_value = httpx.Response(500, text="down")
        response = await browser.get(
            f"/admin/transcript/action/score-turns?pks={people['transcript']}"
        )
    page = await browser.get(response.headers["location"])
    assert "couldn&#39;t be scored" in page.text or "couldn't be scored" in page.text
    assert "not scored" in page.text
