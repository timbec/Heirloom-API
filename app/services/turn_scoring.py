"""Split a transcript into turns and score them, saving the results. Shared by the API and the
admin panel's "Score turns" button."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Transcript, Turn
from app.models.annotation import Annotation
from app.services.annotations import reanchor, regenerate_system_annotations
from app.services.scoring import PROMPTS, TurnScore, build_profile, score_turns
from app.services.turns import parse_turns


@dataclass
class _SavedMark:
    """A user's mark or note, detached from the turn it was on."""

    turn_index: int
    field: str
    start: int
    end: int
    quote: str
    kind: str
    body: str | None
    dismissed: bool


async def _save_user_work(
    db: AsyncSession, transcript_id: int
) -> tuple[list[_SavedMark], set[tuple[int, str]]]:
    """The user's marks and notes, and which system marks they disagreed with, keyed by turn
    index. Taken before the turns (and, by cascade, their annotations) are replaced."""
    rows = await db.execute(
        select(Annotation, Turn.turn_index)
        .join(Turn, Annotation.turn_id == Turn.id)
        .where(Annotation.transcript_id == transcript_id)
    )
    marks, dismissed = [], set()
    for ann, turn_index in rows:
        if ann.author == "user":
            marks.append(
                _SavedMark(
                    turn_index, ann.field, ann.start, ann.end, ann.quote, ann.kind, ann.body,
                    ann.dismissed,
                )
            )  # fmt: skip
        elif ann.dismissed:
            dismissed.add((turn_index, ann.kind))
    return marks, dismissed


def _found_at(mark: _SavedMark, turn: Turn) -> tuple[int, int] | None:
    text = turn.answer if mark.field == "answer" else turn.question
    probe = Annotation(start=mark.start, end=mark.end, quote=mark.quote)
    return reanchor(probe, text)


def _restore(mark: _SavedMark, turns: list[Turn], transcript_id: int) -> Annotation:
    """Put a mark back on the turn that still has its words: the same exchange if possible, else
    any exchange that contains them. If the words are gone, keep it on the nearest exchange
    with its old offsets, where it reads back as unanchored (shown in the margin) rather than
    being lost. Notes (no quote) stay with their exchange."""
    same = next((t for t in turns if t.turn_index == mark.turn_index), None)
    candidates = ([same] if same else []) + [t for t in turns if t is not same]
    for turn in candidates if mark.quote else []:
        if (position := _found_at(mark, turn)) is not None:
            target, (start, end) = turn, position
            break
    else:
        target = same or min(turns, key=lambda t: abs(t.turn_index - mark.turn_index))
        start, end = mark.start, mark.end
    return Annotation(
        transcript_id=transcript_id,
        turn_id=target.id,
        field=mark.field,
        start=start,
        end=end,
        quote=mark.quote,
        author="user",
        kind=mark.kind,
        body=mark.body,
        dismissed=mark.dismissed,
    )


async def rescore_transcript(db: AsyncSession, transcript: Transcript) -> tuple[list[Turn], int]:
    """Replace the transcript's turns with freshly parsed and scored ones, keeping the user's own
    marks, notes and "I disagree" choices, and derive the system marks from the new scores.
    Returns the turns and how many scored successfully (failures stay unscored).
    `transcript.session.subject` must be loaded. Raises TurnParseError if the transcript can't
    be split into turns."""
    parsed = parse_turns(transcript.transcript_text)
    settings = get_settings()
    user_marks, dismissed = await _save_user_work(db, transcript.id)

    await db.execute(delete(Turn).where(Turn.transcript_id == transcript.id))
    turns = [
        Turn(transcript_id=transcript.id, turn_index=i, question=p.question, answer=p.answer)
        for i, p in enumerate(parsed)
    ]
    db.add_all(turns)
    await db.flush()  # assigns the new turns' ids
    # The user's work goes back with the new turns, before the (slow) scoring, so an interrupted
    # or failed scoring can't lose it. Linked by turn_id (not the relationship), like the system
    # annotations, so no turn caches a partial list of its annotations.
    db.add_all(_restore(mark, turns, transcript.id) for mark in user_marks)
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
    await db.flush()

    await regenerate_system_annotations(db, transcript)
    if dismissed:
        index_of = {t.id: t.turn_index for t in turns}
        system = await db.scalars(
            select(Annotation).where(
                Annotation.transcript_id == transcript.id, Annotation.author == "system"
            )
        )
        for ann in system:
            if (index_of.get(ann.turn_id), ann.kind) in dismissed:
                ann.dismissed = True
    await db.commit()
    return turns, scored
