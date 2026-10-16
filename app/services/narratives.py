"""Narrative synthesis, ported from the Laravel NarrativeService (prompt unchanged)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.models import InterviewSession, JobStatus, Narrative, NarrativeFormat, Subject, Transcript
from app.services.groq import AIError, chat_completion

MAX_TOKENS = 2500
TIMEOUT_SECONDS = 120


class NoTranscriptsError(Exception):
    pass


FORMAT_INSTRUCTIONS = {
    NarrativeFormat.MEMOIR: (
        "Write this as the opening of a memoir — something a grandchild could read and feel "
        "they had sat in the room."
    ),
    NarrativeFormat.LETTER: (
        "Write this as a legacy letter — in the subject's voice, addressed to future generations."
    ),
    NarrativeFormat.TIMELINE: (
        "Write this as a timeline of key life moments, in the subject's voice."
    ),
}

PROMPT = """You are a narrative editor helping to preserve a person's life story.

You will be given a transcript of a recorded interview. Your task is to synthesise
it into a short, vivid first-person narrative — written in the subject's own voice,
as if they are telling their story directly to someone they love.

Guidelines:
- Write in the first person, in the subject's voice. Do not write about them — write as them.
- Preserve their speech patterns, idioms, and rhythms. If they are formal, be formal. If they are wry, be wry.
- Pay attention to pauses, laughter, and hesitations marked in the transcript — these carry emotional weight.
- Do not invent facts, memories, or emotions not present in the transcript.
- Prioritise moments of feeling over moments of fact.
- Write between {word_count} words unless instructed otherwise.
- End on something that resonates — a thought, an image, a question. Not a summary.

{format_instruction}

Here is the transcript:

{transcript_text}"""  # noqa: E501


def build_transcript_text(sessions: list[InterviewSession]) -> str:
    """Join sessions as "Session N — Title:\\n\\n<text>", separated by "---"."""
    parts = []
    for number, session in enumerate(sessions, start=1):
        label = f"Session {number} — {session.title}" if session.title else f"Session {number}"
        parts.append(f"{label}:\n\n{session.transcript.transcript_text}")
    return "\n\n---\n\n".join(parts)


def build_prompt(transcript_text: str, format: NarrativeFormat, session_count: int) -> str:
    return PROMPT.format(
        word_count="600 and 900" if session_count > 1 else "400 and 600",
        format_instruction=FORMAT_INSTRUCTIONS[format],
        transcript_text=transcript_text,
    )


async def sessions_with_transcripts(db: AsyncSession, subject: Subject) -> list[InterviewSession]:
    """The subject's sessions that have a completed transcript, oldest first."""
    result = await db.scalars(
        select(InterviewSession)
        .join(InterviewSession.transcript)
        .where(InterviewSession.subject_id == subject.id)
        .where(Transcript.status == JobStatus.COMPLETED)
        .options(joinedload(InterviewSession.transcript))
        .order_by(InterviewSession.id)
    )
    return list(result)


async def generate_narrative(
    db: AsyncSession, subject: Subject, format: NarrativeFormat
) -> Narrative:
    """Write a new narrative version from all of the subject's sessions so far.

    The attempt is saved whether or not it succeeds, so failures are visible in the admin panel.
    Raises NoTranscriptsError before saving anything, or AIError after saving a failed version.
    """
    sessions = await sessions_with_transcripts(db, subject)
    if not sessions:
        raise NoTranscriptsError("No completed transcripts found for this subject.")

    model = get_settings().groq_model
    narrative = Narrative(
        subject_id=subject.id,
        format=format,
        status=JobStatus.PROCESSING,
        session_ids=[s.id for s in sessions],
        model=model,
    )
    db.add(narrative)
    await db.commit()

    prompt = build_prompt(build_transcript_text(sessions), format, len(sessions))
    try:
        narrative.narrative_text = await chat_completion(
            prompt, model=model, max_tokens=MAX_TOKENS, timeout_seconds=TIMEOUT_SECONDS
        )
        narrative.status = JobStatus.COMPLETED
    except AIError as exc:
        narrative.status = JobStatus.FAILED
        narrative.error = str(exc)
        await db.commit()
        raise
    await db.commit()
    return narrative
