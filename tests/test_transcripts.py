from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Turn

SUBJECTS = "/api/heirloom/v1/subjects"
SESSIONS = "/api/heirloom/v1/sessions"
TEXT = "Q: Where were you born? A: In Leeds, in the back bedroom of my grandmother's house."


async def make_session(client: AsyncClient, headers: dict) -> dict:
    subject = (await client.post(SUBJECTS, json={"name": "Rose"}, headers=headers)).json()
    response = await client.post(SESSIONS, json={"subject_id": subject["id"]}, headers=headers)
    return response.json()


def transcript_url(session: dict) -> str:
    return f"{SESSIONS}/{session['id']}/transcript"


async def test_save_manual_transcript(client: AsyncClient, auth_headers: dict):
    session = await make_session(client, auth_headers)

    response = await client.post(
        transcript_url(session), json={"transcript_text": f"  {TEXT}  "}, headers=auth_headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["transcript_text"] == TEXT
    assert body["source"] == "manual"
    assert body["status"] == "completed"
    assert body["language"] == "en"

    # The session page only fetches the transcript once the session is "transcribed".
    session_now = (await client.get(f"{SESSIONS}/{session['id']}", headers=auth_headers)).json()
    assert session_now["status"] == "transcribed"

    response = await client.get(transcript_url(session), headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == body


async def test_transcript_must_be_at_least_50_characters(client: AsyncClient, auth_headers: dict):
    session = await make_session(client, auth_headers)
    padded = "Too short" + " " * 60  # trimmed before the length check
    for payload in ({}, {"transcript_text": padded}):
        response = await client.post(transcript_url(session), json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert "transcript_text" in response.json()["errors"]


async def test_posting_again_replaces_transcript_and_clears_turns(
    client: AsyncClient, db: AsyncSession, auth_headers: dict
):
    session = await make_session(client, auth_headers)
    first = (
        await client.post(
            transcript_url(session), json={"transcript_text": TEXT}, headers=auth_headers
        )
    ).json()
    db.add(Turn(transcript_id=first["id"], turn_index=0, question="Q", answer="A"))
    await db.flush()

    revised = TEXT + " We moved to Toronto in 1962."
    response = await client.post(
        transcript_url(session), json={"transcript_text": revised}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert response.json()["transcript_text"] == revised
    assert await db.scalar(select(func.count()).select_from(Turn)) == 0


async def test_missing_transcript_is_404(client: AsyncClient, auth_headers: dict):
    session = await make_session(client, auth_headers)
    response = await client.get(transcript_url(session), headers=auth_headers)
    assert response.status_code == 404
    assert response.json() == {"message": "No transcript found"}


async def test_other_users_cannot_read_or_write(
    client: AsyncClient, auth_headers: dict, other_headers: dict
):
    session = await make_session(client, auth_headers)
    url = transcript_url(session)
    await client.post(url, json={"transcript_text": TEXT}, headers=auth_headers)

    assert (await client.get(url, headers=other_headers)).status_code == 403
    response = await client.post(url, json={"transcript_text": TEXT}, headers=other_headers)
    assert response.status_code == 403
    assert (
        await client.get(f"{SESSIONS}/999999/transcript", headers=auth_headers)
    ).status_code == 404
