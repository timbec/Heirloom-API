"""Split a transcript into turns and score them, saving the results. Shared by the API and the
admin panel's "Score turns" button."""

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Transcript, Turn
from app.services.scoring import PROMPTS, TurnScore, build_profile, score_turns
from app.services.turns import parse_turns


async def rescore_transcript(db: AsyncSession, transcript: Transcript) -> tuple[list[Turn], int]:
    """Replace the transcript's turns with freshly parsed and scored ones. Returns the turns and
    how many scored successfully (failures stay unscored). `transcript.session.subject` must be
    loaded. Raises TurnParseError if the transcript can't be split into turns."""
    parsed = parse_turns(transcript.transcript_text)
    settings = get_settings()

    await db.execute(delete(Turn).where(Turn.transcript_id == transcript.id))
    turns = [
        Turn(transcript_id=transcript.id, turn_index=i, question=p.question, answer=p.answer)
        for i, p in enumerate(parsed)
    ]
    db.add_all(turns)
    await db.commit()

    results = await score_turns(
        build_profile(transcript.session.subject), parsed, PROMPTS[settings.scoring_prompt]
    )
    now = datetime.now(UTC)
    scored_with = f"{settings.groq_scoring_model}, prompt {settings.scoring_prompt}"
    scored = 0
    for turn, result in zip(turns, results, strict=True):
        if isinstance(result, TurnScore):
            for field, value in result.model_dump().items():
                setattr(turn, field, value)
            turn.scored_at = now
            turn.scored_with = scored_with
            scored += 1
    await db.commit()
    return turns, scored
