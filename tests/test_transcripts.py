import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Turn
from app.services.storage import absolute_path

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


# --- Audio --------------------------------------------------------------------------------

GROQ_TRANSCRIBE = "https://groq.test/openai/v1/audio/transcriptions"
AUDIO = b"ID3" + b"\x00" * 2048  # stands in for an mp3; the fake Whisper doesn't decode it


@pytest.fixture
def whisper():
    with respx.mock(assert_all_called=False) as mock:
        yield mock.post(GROQ_TRANSCRIBE)


def audio_url(session: dict) -> str:
    return f"{SESSIONS}/{session['id']}/transcribe"


async def upload(
    client: AsyncClient, session: dict, headers: dict, name="interview.mp3", data=AUDIO
):
    return await client.post(audio_url(session), files={"audio": (name, data)}, headers=headers)


async def test_transcribe_audio(client: AsyncClient, db: AsyncSession, auth_headers: dict, whisper):
    whisper.return_value = httpx.Response(
        200, json={"text": "  Q: Where were you born? A: Leeds.  ", "duration": 12.6}
    )
    session = await make_session(client, auth_headers)

    response = await upload(client, session, auth_headers, name="Mum Interview.MP3")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["transcript_text"] == "Q: Where were you born? A: Leeds."
    assert body["source"] == "audio"
    assert body["status"] == "completed"
    assert body["duration_seconds"] == 13

    # What was sent to Whisper.
    sent = whisper.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"
    assert b'name="model"\r\n\r\ntest-transcription-model' in sent.content
    assert b'name="response_format"\r\n\r\nverbose_json' in sent.content
    assert AUDIO in sent.content

    # The original recording is kept, and the session points at it.
    saved = (await client.get(f"{SESSIONS}/{session['id']}", headers=auth_headers)).json()
    assert saved["status"] == "transcribed"
    assert saved["duration_seconds"] == 13
    assert saved["audio_path"].startswith(f"audio/session-{session['id']}/")
    assert saved["audio_path"].endswith(".mp3")
    assert absolute_path(saved["audio_path"]).read_bytes() == AUDIO


async def test_audio_validation(client: AsyncClient, auth_headers: dict, whisper, monkeypatch):
    session = await make_session(client, auth_headers)

    response = await client.post(audio_url(session), headers=auth_headers)  # no file
    assert response.status_code == 422
    assert "audio" in response.json()["errors"]

    response = await upload(client, session, auth_headers, name="notes.pdf")
    assert response.status_code == 422
    assert "must be a file of type" in response.json()["errors"]["audio"][0]

    monkeypatch.setattr(get_settings(), "max_audio_mb", 1)
    response = await upload(client, session, auth_headers, data=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 422
    assert "larger than 1 MB" in response.json()["message"]
    assert not list(absolute_path(f"audio/session-{session['id']}").glob("*"))  # nothing left
    assert not whisper.called


async def test_failed_transcription_keeps_the_recording(
    client: AsyncClient, auth_headers: dict, whisper
):
    whisper.return_value = httpx.Response(500, text="upstream error")
    session = await make_session(client, auth_headers)

    response = await upload(client, session, auth_headers)
    assert response.status_code == 502
    assert response.json() == {"message": "Transcription failed. Please try again."}

    saved = (await client.get(f"{SESSIONS}/{session['id']}", headers=auth_headers)).json()
    assert saved["status"] == "pending"
    assert absolute_path(saved["audio_path"]).read_bytes() == AUDIO
    assert (await client.get(transcript_url(session), headers=auth_headers)).status_code == 404


async def test_other_users_cannot_upload(
    client: AsyncClient, auth_headers: dict, other_headers: dict, whisper
):
    session = await make_session(client, auth_headers)
    assert (await upload(client, session, other_headers)).status_code == 403
    assert not whisper.called
