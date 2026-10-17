import json
from types import SimpleNamespace

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.services.scoring import build_context, build_profile, is_verbatim

V1 = "/api/heirloom/v1"
GROQ_CHAT = "https://groq.test/openai/v1/chat/completions"
TRANSCRIPT = (
    "Q: Where were you born?\nA: Leeds, in the back bedroom of my grandmother's house.\n"
    "Q: What was the house like?\nA: Cold. Always cold. Gran kept the coal for Sundays.\n"
    "Q: Who else lived there?\nA: My uncle Albert, who sang in the bath.\n"
    "Q: And school?\nA: It was fine. Normal, really."
)
GOOD = {
    "specificity": 8,
    "emotional_charge": 6,
    "thread_type": "new",
    "is_gold": True,
    "gold_quote": "Gran kept the coal for Sundays",
    "open_thread": "Uncle Albert",
}


def reply(score: dict | str, status: int = 200, **headers) -> httpx.Response:
    content = score if isinstance(score, str) else json.dumps(score)
    return httpx.Response(
        status, json={"choices": [{"message": {"content": content}}]}, headers=headers
    )


@pytest.fixture
def groq():
    with respx.mock(assert_all_called=False) as mock:
        yield mock.post(GROQ_CHAT)


async def make_transcript(client: AsyncClient, headers: dict, text: str = TRANSCRIPT) -> dict:
    subject = (
        await client.post(
            f"{V1}/subjects", json={"name": "Rose", "birth_year": 1938}, headers=headers
        )
    ).json()
    session = (
        await client.post(f"{V1}/sessions", json={"subject_id": subject["id"]}, headers=headers)
    ).json()
    response = await client.post(
        f"{V1}/sessions/{session['id']}/transcript", json={"transcript_text": text}, headers=headers
    )
    return response.json()


def score_url(transcript: dict) -> str:
    return f"{V1}/transcripts/{transcript['id']}/turns/score"


async def test_score_transcript(client: AsyncClient, auth_headers: dict, groq):
    groq.return_value = reply(GOOD)
    transcript = await make_transcript(client, auth_headers)

    response = await client.post(score_url(transcript), headers=auth_headers)
    assert response.status_code == 201, response.text
    turns = response.json()
    assert [t["turn_index"] for t in turns] == [0, 1, 2, 3]
    assert turns[1]["question"] == "What was the house like?"
    assert turns[1]["specificity"] == 8
    assert turns[1]["thread_type"] == "new"
    assert turns[1]["gold_quote"] == "Gran kept the coal for Sundays"
    assert all(t["scored_at"] for t in turns)
    assert groq.call_count == 4

    # Request shape: system prompt, JSON mode, temperature 0, model and effort from settings.
    calls = [json.loads(c.request.content) for c in groq.calls]
    sent = next(c for c in calls if "And school?" in c["messages"][1]["content"])
    assert sent["model"] == "test-scoring-model"
    assert sent["temperature"] == 0
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["reasoning_effort"] == "low"
    assert sent["messages"][0]["content"].startswith("You are scoring a single answer")
    user = sent["messages"][1]["content"]
    assert user.startswith("SUBJECT PROFILE: Name: Rose | Born: 1938")
    # The three turns before it, as context.
    context = user.split("RECENT CONTEXT")[1].split("CURRENT TURN")[0]
    assert context.count("Q: ") == 3
    assert "Q: Where were you born?" in context and "Q: Who else lived there?" in context
    assert user.endswith("CURRENT TURN:\nQ: And school?\nA: It was fine. Normal, really.")

    listed = await client.get(f"{V1}/transcripts/{transcript['id']}/turns", headers=auth_headers)
    assert listed.json() == turns


async def test_a_bad_reply_leaves_only_that_turn_unscored(
    client: AsyncClient, auth_headers: dict, groq
):
    def respond(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        if user.endswith("A: Cold. Always cold. Gran kept the coal for Sundays."):
            return reply({**GOOD, "specificity": 11})  # out of range
        if user.endswith("A: My uncle Albert, who sang in the bath."):
            return reply("not json at all")
        return reply({**GOOD, "is_gold": False})

    groq.side_effect = respond
    transcript = await make_transcript(client, auth_headers)
    turns = (await client.post(score_url(transcript), headers=auth_headers)).json()

    assert [t["scored_at"] is not None for t in turns] == [True, False, False, True]
    assert turns[1]["specificity"] is None
    assert turns[0]["gold_quote"] is None  # dropped because is_gold is false


async def test_rate_limit_is_retried(client: AsyncClient, auth_headers: dict, groq):
    groq.side_effect = [reply({}, status=429, **{"retry-after": "0"})] + [reply(GOOD)] * 4
    transcript = await make_transcript(client, auth_headers)
    turns = (await client.post(score_url(transcript), headers=auth_headers)).json()
    assert all(t["scored_at"] for t in turns)
    assert groq.call_count == 5


async def test_all_failing_is_502_with_turns_kept(client: AsyncClient, auth_headers: dict, groq):
    groq.return_value = httpx.Response(500, text="down")
    transcript = await make_transcript(client, auth_headers)

    response = await client.post(score_url(transcript), headers=auth_headers)
    assert response.status_code == 502
    assert response.json() == {"message": "Scoring failed. Please try again."}
    listed = (
        await client.get(f"{V1}/transcripts/{transcript['id']}/turns", headers=auth_headers)
    ).json()
    assert len(listed) == 4 and not any(t["scored_at"] for t in listed)


async def test_rescoring_replaces_turns(client: AsyncClient, auth_headers: dict, groq):
    groq.return_value = reply(GOOD)
    transcript = await make_transcript(client, auth_headers)
    first = (await client.post(score_url(transcript), headers=auth_headers)).json()
    second = (await client.post(score_url(transcript), headers=auth_headers)).json()
    assert len(second) == 4
    assert {t["id"] for t in first}.isdisjoint(t["id"] for t in second)


async def test_unparseable_transcript_is_422(client: AsyncClient, auth_headers: dict, groq):
    transcript = await make_transcript(client, auth_headers, "Just one long paragraph. " * 5)
    response = await client.post(score_url(transcript), headers=auth_headers)
    assert response.status_code == 422
    assert "Start each line with who is speaking" in response.json()["message"]
    assert not groq.called


async def test_ownership(client: AsyncClient, auth_headers: dict, other_headers: dict, groq):
    transcript = await make_transcript(client, auth_headers)
    assert (await client.post(score_url(transcript), headers=other_headers)).status_code == 403
    listed = await client.get(f"{V1}/transcripts/{transcript['id']}/turns", headers=other_headers)
    assert listed.status_code == 403
    assert (
        await client.get(f"{V1}/transcripts/999999/turns", headers=auth_headers)
    ).status_code == 404
    assert not groq.called


def test_profile_and_context_wording():
    blank = SimpleNamespace(
        name="",
        birth_year=None,
        places_lived=None,
        education_profession=None,
        family_structure=None,
        life_chapters=None,
        interests=None,
    )
    assert build_profile(None) == "Unknown."
    assert build_profile(blank) == "No profile details recorded."
    rose = SimpleNamespace(**{**vars(blank), "name": "Rose", "family_structure": "Two sons"})
    assert build_profile(rose) == "Name: Rose | Family: Two sons"

    assert build_context([]) == "(none — this is the first turn)"
    turns = [
        SimpleNamespace(question="Q1", answer="A1"),
        SimpleNamespace(question="Q2", answer="A2"),
    ]
    assert build_context(turns) == "Q: Q1\nA: A1\n\nQ: Q2\nA: A2"


def test_is_verbatim():
    answer = "Carol used to say “you still smell like Blackstone Avenue” — years after."
    assert is_verbatim('"you still smell like Blackstone Avenue"', answer)
    assert is_verbatim("You still  smell like Blackstone Avenue.", answer)
    assert not is_verbatim("you smelled like the shop", answer)
    assert is_verbatim("say 'you still smell like Blackstone Avenue'", answer)


async def test_quotes_not_in_the_answer_are_dropped(client: AsyncClient, auth_headers: dict, groq):
    groq.return_value = reply({**GOOD, "gold_quote": "My uncle Albert, who sang in the bath."})
    transcript = await make_transcript(client, auth_headers)
    turns = (await client.post(score_url(transcript), headers=auth_headers)).json()

    by_question = {t["question"]: t for t in turns}
    assert (
        by_question["Who else lived there?"]["gold_quote"]
        == "My uncle Albert, who sang in the bath."
    )
    # The same quote offered for another turn (it's only in the context there) is dropped.
    assert by_question["And school?"]["gold_quote"] is None
    assert by_question["And school?"]["is_gold"] is True
