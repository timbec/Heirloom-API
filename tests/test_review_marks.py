"""Scoring creates the Review's system marks, and re-scoring keeps the user's own work."""

import json

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Transcript
from app.services.annotations import HANDLE_WITH_CARE_NOTE

V1 = "/api/heirloom/v1"
GROQ_CHAT = "https://groq.test/openai/v1/chat/completions"
TRANSCRIPT = (
    "Q: What did she cook?\n"
    "A: Pierogi. Her hands were always red from the lye soap. I don't know why I remember that.\n"
    "Q: And Woolworth's?\n"
    "A: Forty cups on the counter. Every day, a nickel under the saucer. I never knew his name."
)
GOLD = {
    "What did she cook?": "Her hands were always red from the lye soap.",
    "And Woolworth's?": "Every day, a nickel under the saucer.",
}


def scorer(**extra):
    """A fake Groq scorer: gold quote and open thread for each turn, plus any extra fields."""

    def respond(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        question = user.split("CURRENT TURN:\nQ: ")[1].split("\n")[0]
        score = {
            "specificity": 8,
            "emotional_charge": 7,
            "thread_type": "new",
            "is_gold": True,
            "gold_quote": GOLD[question],
            "open_thread": f"more about {question.rstrip('?').lower()}",
            **extra.get(question, {}),
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(score)}}]})

    return respond


@pytest.fixture
def groq():
    with respx.mock(assert_all_called=False) as mock:
        yield mock.post(GROQ_CHAT)


async def make_transcript(client: AsyncClient, headers: dict) -> int:
    subject = (
        await client.post(f"{V1}/subjects", json={"name": "Frances"}, headers=headers)
    ).json()
    session = (
        await client.post(f"{V1}/sessions", json={"subject_id": subject["id"]}, headers=headers)
    ).json()
    transcript = await client.post(
        f"{V1}/sessions/{session['id']}/transcript",
        json={"transcript_text": TRANSCRIPT},
        headers=headers,
    )
    return transcript.json()["id"]


async def score(client: AsyncClient, headers: dict, tid: int) -> None:
    response = await client.post(f"{V1}/transcripts/{tid}/turns/score", headers=headers)
    assert response.status_code == 201, response.text


async def review(client: AsyncClient, headers: dict, tid: int) -> list[dict]:
    return (await client.get(f"{V1}/transcripts/{tid}/review", headers=headers)).json()["turns"]


def by(turn: dict, author: str, kind: str) -> dict | None:
    return next(
        (a for a in turn["annotations"] if a["author"] == author and a["kind"] == kind), None
    )


async def test_scoring_creates_system_marks(client: AsyncClient, auth_headers: dict, groq):
    groq.side_effect = scorer()
    tid = await make_transcript(client, auth_headers)
    await score(client, auth_headers, tid)

    first = (await review(client, auth_headers, tid))[0]
    keep = by(first, "system", "keep")
    assert keep["anchored"] and keep["quote"] == GOLD["What did she cook?"]
    assert first["answer"][keep["start"] : keep["end"]] == keep["quote"]  # exact substring

    # The scorer's open thread becomes a follow-up note with no highlight.
    chase = by(first, "system", "chase")
    assert chase["body"] == "more about what did she cook"
    assert chase["quote"] == "" and chase["start"] == chase["end"]


async def test_prompt_v2_sensitivity_becomes_marks(
    client: AsyncClient, auth_headers: dict, groq, monkeypatch
):
    monkeypatch.setattr(get_settings(), "scoring_prompt", "v2")
    groq.side_effect = scorer(
        **{
            "What did she cook?": {"sensitivity": "handle_with_care"},
            "And Woolworth's?": {"sensitivity": "off_record"},
        }
    )
    tid = await make_transcript(client, auth_headers)
    await score(client, auth_headers, tid)

    first, second = await review(client, auth_headers, tid)
    assert by(first, "system", "leave")["body"] == HANDLE_WITH_CARE_NOTE
    out = by(second, "system", "out")
    assert out["quote"] == second["answer"]  # the whole answer is struck through
    assert by(second, "system", "keep") is None  # off the record is never gold

    # ...and it never appears in the text download.
    export = (await client.get(f"{V1}/transcripts/{tid}/export.md", headers=auth_headers)).text
    assert "nickel under the saucer" not in export
    assert "Her hands were always red" in export


async def test_rescoring_keeps_the_users_marks_notes_and_dismissals(
    client: AsyncClient, auth_headers: dict, groq
):
    groq.side_effect = scorer()
    tid = await make_transcript(client, auth_headers)
    await score(client, auth_headers, tid)
    turns = await review(client, auth_headers, tid)
    base = f"{V1}/transcripts/{tid}"

    answer = turns[1]["answer"]
    start = answer.index("Forty cups")
    await client.post(
        f"{base}/annotations",
        json={"turn_id": turns[1]["id"], "field": "answer", "start": start,
              "end": start + len("Forty cups"), "quote": "Forty cups", "kind": "chase"},
        headers=auth_headers,
    )  # fmt: skip
    await client.post(
        f"{base}/annotations",
        json={"turn_id": turns[0]["id"], "field": "answer", "start": 0, "end": 0, "quote": "",
              "kind": "note", "body": "Ask about the soap"},
        headers=auth_headers,
    )  # fmt: skip
    keep = by(turns[0], "system", "keep")
    await client.patch(
        f"{base}/annotations/{keep['id']}/dismiss", json={"dismissed": True}, headers=auth_headers
    )

    await score(client, auth_headers, tid)  # re-score: every turn is replaced
    first, second = await review(client, auth_headers, tid)

    mark = by(second, "user", "chase")
    assert mark["quote"] == "Forty cups" and mark["anchored"]
    assert second["answer"][mark["start"] : mark["end"]] == "Forty cups"
    assert by(first, "user", "note")["body"] == "Ask about the soap"
    assert by(first, "system", "keep")["dismissed"] is True
    assert by(second, "system", "keep")["dismissed"] is False


async def test_marks_whose_words_are_gone_are_kept_unanchored(
    client: AsyncClient, db: AsyncSession, auth_headers: dict, groq
):
    groq.side_effect = scorer()
    tid = await make_transcript(client, auth_headers)
    await score(client, auth_headers, tid)
    turns = await review(client, auth_headers, tid)
    answer = turns[0]["answer"]
    start = answer.index("Pierogi")
    await client.post(
        f"{V1}/transcripts/{tid}/annotations",
        json={"turn_id": turns[0]["id"], "field": "answer", "start": start,
              "end": start + len("Pierogi"), "quote": "Pierogi", "kind": "keep"},
        headers=auth_headers,
    )  # fmt: skip

    # The transcript changes underneath (e.g. corrected by hand), then it's re-scored.
    await db.execute(
        update(Transcript)
        .where(Transcript.id == tid)
        .values(transcript_text=TRANSCRIPT.replace("Pierogi. ", ""))
    )
    await score(client, auth_headers, tid)

    mark = by((await review(client, auth_headers, tid))[0], "user", "keep")
    assert mark is not None and mark["quote"] == "Pierogi"
    assert mark["anchored"] is False  # shown in the margin, not lost


# --- Admin: the Reviews list ---------------------------------------------------------------
# The admin reads through its own sessions, so these reuse the committed-data fixtures.
from tests.test_admin_review import OWNER, admin_browser, login, seeded  # noqa: E402, F401


async def test_reviews_list_links_every_transcript(admin_browser: AsyncClient, seeded):  # noqa: F811
    await login(admin_browser)
    page = await admin_browser.get("/admin/reviews")
    assert page.status_code == 200
    text = page.text
    assert OWNER in text and "Frances" in text
    assert f"view-review?pks={seeded['transcript']}" in text
    assert f"view-review?pks={seeded['empty']}" in text
    assert "not scored" in text  # the empty transcript
    assert ">Reviews<" in text or "Reviews</" in text  # in the sidebar


async def test_reviews_list_requires_admin(admin_browser: AsyncClient, seeded):  # noqa: F811
    response = await admin_browser.get("/admin/reviews")
    assert response.status_code in (302, 303)


async def test_score_confirmation_says_user_marks_are_kept(admin_browser: AsyncClient, seeded):  # noqa: F811
    await login(admin_browser)
    detail = (await admin_browser.get(f"/admin/transcript/details/{seeded['transcript']}")).text
    assert "own marks, notes" in detail
