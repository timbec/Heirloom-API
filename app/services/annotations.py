import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.annotation import Annotation
from app.models.enums import Sensitivity
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


# ─── deriving system annotations from turn fields ──────────────────────────

# The kinds derived from turn fields, one system annotation of each per turn at most.
_DERIVED_KINDS = ("keep", "chase", "out", "leave", "told")

HANDLE_WITH_CARE_NOTE = (
    "Handle with care. This was painful or hard to talk about. Let them lead if it comes up again."
)


def _span(answer: str, quote: str) -> tuple[int, int, str]:
    start = answer.find(quote)
    return (start, start + len(quote), quote) if start != -1 else (0, len(quote), quote)


def _derive(kind: str, turn: Turn) -> tuple[int, int, str, str | None] | None:
    """(start, end, quote, body) for a system annotation of this kind, or None if the turn gives
    no reason for one. An empty quote means a margin note with no highlight. A body of None
    leaves any existing note text alone (the seed's mockup text, for instance)."""
    answer = turn.answer
    whole = (0, len(answer), answer, None)

    if kind == "keep" and turn.gold_quote:
        return (*_span(answer, turn.gold_quote), None)
    if kind == "chase":
        if turn.thread_anchor:
            return (*_span(answer, turn.thread_anchor), None)
        if turn.open_thread:  # what the scorer produces: a note, no highlight
            return 0, 0, "", turn.open_thread
    if kind == "out" and (turn.retracted or turn.sensitivity == Sensitivity.OFF_RECORD):
        return whole
    if kind == "leave":
        if turn.unable_to_recall:
            return whole
        if turn.sensitivity == Sensitivity.HANDLE_WITH_CARE:  # scoring prompt v2
            return 0, 0, "", HANDLE_WITH_CARE_NOTE
    if kind == "told" and turn.repeat_of is not None:
        return whole
    return None


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

        for kind in _DERIVED_KINDS:
            derived = _derive(kind, turn)
            if derived is None:
                # Source field absent — delete stale system annotation if any.
                if kind in existing:
                    await db.delete(existing[kind])
                continue

            start, end, quote, body = derived
            if kind in existing:
                ann = existing[kind]
                ann.quote = quote
                ann.start = start
                ann.end = end
                if body is not None:
                    ann.body = body
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
                    body=body,
                    dismissed=False,
                )
                db.add(ann)

    await db.flush()
