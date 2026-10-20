import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.annotation import Annotation
from app.models.session import Transcript, Turn


def reanchor(annotation: Annotation, text: str) -> tuple[int, int] | None:
    """Return the (start, end) offsets of the annotation's quote in text.

    Tries the stored offsets first; if those no longer match, searches the text
    with whitespace-normalised matching. Returns None if the quote cannot be found.
    """
    if text[annotation.start : annotation.end] == annotation.quote:
        return annotation.start, annotation.end

    # Whitespace-normalised search: split on whitespace, allow any \s+ between tokens.
    stripped = annotation.quote.strip()
    if not stripped:
        return None

    tokens = re.split(r"\s+", stripped)
    pattern = r"\s+".join(re.escape(t) for t in tokens if t)
    match = re.search(pattern, text)
    if match:
        return match.start(), match.end()

    return None


# ─── kind → source field mapping ───────────────────────────────────────────

_KIND_TO_FIELD = {
    "keep": "gold_quote",
    "chase": "thread_anchor",
    "out": "retracted",
    "leave": "unable_to_recall",
    "told": "repeat_of",
}


def _system_annotation_body(kind: str, turn: Turn) -> tuple[int, int, str] | None:
    """Return (start, end, quote) for a system annotation, or None if the source is absent."""
    answer = turn.answer
    if kind == "keep":
        quote = turn.gold_quote
        if not quote:
            return None
        start = answer.find(quote)
        if start == -1:
            start, end = 0, len(quote)
        else:
            end = start + len(quote)
        return start, end, quote

    if kind == "chase":
        quote = turn.thread_anchor
        if not quote:
            return None
        start = answer.find(quote)
        if start == -1:
            start, end = 0, len(quote)
        else:
            end = start + len(quote)
        return start, end, quote

    if kind == "out":
        if not turn.retracted:
            return None
        return 0, len(answer), answer

    if kind == "leave":
        if not turn.unable_to_recall:
            return None
        return 0, len(answer), answer

    if kind == "told":
        if turn.repeat_of is None:
            return None
        return 0, len(answer), answer

    return None


def _source_is_present(kind: str, turn: Turn) -> bool:
    if kind == "keep":
        return bool(turn.gold_quote)
    if kind == "chase":
        return bool(turn.thread_anchor)
    if kind == "out":
        return bool(turn.retracted)
    if kind == "leave":
        return bool(turn.unable_to_recall)
    if kind == "told":
        return turn.repeat_of is not None
    return False


async def regenerate_system_annotations(db: AsyncSession, transcript: Transcript) -> None:
    """Derive system annotations from turn fields. Does not touch user annotations or
    dismissed state. Safe to call repeatedly — it upserts, never duplicates."""
    result = await db.execute(
        select(Turn)
        .where(Turn.transcript_id == transcript.id)
        .options(selectinload(Turn.annotations))
        .order_by(Turn.turn_index)
    )
    turns = result.scalars().all()

    for turn in turns:
        # Index existing system annotations for this turn by kind.
        existing: dict[str, Annotation] = {
            a.kind: a for a in turn.annotations if a.author == "system"
        }

        for kind in _KIND_TO_FIELD:
            pos = _system_annotation_body(kind, turn)
            if pos is None:
                # Source field absent — delete stale system annotation if any.
                if kind in existing:
                    await db.delete(existing[kind])
                continue

            start, end, quote = pos
            if kind in existing:
                ann = existing[kind]
                ann.quote = quote
                ann.start = start
                ann.end = end
                # dismissed is intentionally preserved
            else:
                ann = Annotation(
                    transcript_id=transcript.id,
                    turn_id=turn.id,
                    field="answer",
                    start=start,
                    end=end,
                    quote=quote,
                    author="system",
                    kind=kind,
                    body=None,
                    dismissed=False,
                )
                db.add(ann)

    await db.flush()
