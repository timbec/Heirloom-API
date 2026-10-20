"""Server-side rendering helpers for the admin's read-only Review page.

A port of heirloom-web's lib/review/marks.ts (same rules), so the admin shows the transcript marked
up exactly as the user sees it. Keep the two in step.
"""

import re
from dataclasses import dataclass, field

from app.models.annotation import Annotation
from app.models.session import Turn
from app.services.annotations import reanchor

SYSTEM_MARK_KINDS = {"keep", "chase", "leave", "out", "told"}
USER_MARK_KINDS = {"keep", "chase", "leave"}
NOTE_ORDER = ["out", "keep", "chase", "leave", "told", "skip"]
LABELS = {
    "keep": "Keep word for word",
    "chase": "Follow up",
    "leave": "Leave alone",
    "out": "Left out on request",
    "told": "Told before",
    "skip": "Nothing to chase",
}
_BRACKETED = re.compile(r"\[[^\]]*\]")
_SPEAKER_ASIDE = re.compile(r"^\[[A-Z][\w .'’-]{0,30}:")  # "[Linda: ...]": someone else speaking


@dataclass
class Piece:
    text: str
    classes: list[str] = field(default_factory=list)


@dataclass
class PlacedAnnotation:
    """An annotation with its position re-found in the current text (None if it can't be)."""

    annotation: Annotation
    start: int | None
    end: int | None

    @property
    def anchored(self) -> bool:
        return self.start is not None


def place(turn: Turn) -> list[PlacedAnnotation]:
    placed = []
    for ann in turn.annotations:
        text = turn.answer if ann.field == "answer" else turn.question
        pos = reanchor(ann, text)
        placed.append(PlacedAnnotation(ann, *(pos or (None, None))))
    return placed


def _is_span(p: PlacedAnnotation) -> bool:
    kinds = SYSTEM_MARK_KINDS if p.annotation.author == "system" else USER_MARK_KINDS
    return p.anchored and p.end > p.start and p.annotation.kind in kinds


def _classes(p: PlacedAnnotation) -> list[str]:
    a = p.annotation
    if a.author == "user":
        return ["mine", f"m-{a.kind}"]
    return [] if a.dismissed else [f"k-{a.kind}"]  # "I disagree" removes the mark


def build_pieces(text: str, placed: list[PlacedAnnotation]) -> list[Piece]:
    """Split text at every mark and stage-direction boundary; each piece carries the classes of
    all marks covering it. The pieces' text, joined, is exactly the input text."""
    marks = [p for p in placed if _is_span(p)]
    brackets = [
        (m.start(), m.end(), "aside" if _SPEAKER_ASIDE.match(m.group()) else "stage")
        for m in _BRACKETED.finditer(text)
    ]
    cuts = {0, len(text)}
    for p in marks:
        cuts.update((max(0, min(p.start, len(text))), max(0, min(p.end, len(text)))))
    for start, end, _ in brackets:
        cuts.update((start, end))
    points = sorted(cuts)

    pieces = []
    for start, end in zip(points, points[1:], strict=False):
        if end <= start:
            continue
        classes: list[str] = []
        for p in marks:
            if p.start <= start and p.end >= end:
                classes += [c for c in _classes(p) if c not in classes]
        for b_start, b_end, cls in brackets:
            if b_start <= start and b_end >= end and cls not in classes:
                classes.append(cls)
        pieces.append(Piece(text[start:end], classes))
    return pieces


def _shorten(text: str, length: int = 48) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"


def note_text(ann: Annotation) -> tuple[str, str]:
    """(label, body) for a margin note. "skip" notes keep their heading in the body's first
    sentence ("Generic answer. ..."), since annotations have no separate label field."""
    body = ann.body or ""
    if ann.kind == "chase" and ann.quote:
        return f"Follow up: “{_shorten(ann.quote)}”", body
    if ann.kind == "skip":
        match = re.match(r"^([^.]{1,40})\.\s+(.*)$", body, re.S)
        if match:
            return match.group(1), match.group(2)
    return LABELS.get(ann.kind, "Note"), body


def turn_context(turn: Turn, position: int) -> dict:
    """Everything the template needs to show one exchange."""
    placed = place(turn)
    system = sorted(
        (p for p in placed if p.annotation.author == "system" and p.annotation.kind != "note"),
        key=lambda p: (
            NOTE_ORDER.index(p.annotation.kind) if p.annotation.kind in NOTE_ORDER else 99
        ),
    )
    notes = []
    for p in system:
        label, body = note_text(p.annotation)
        notes.append(
            {
                "kind": p.annotation.kind,
                "label": label,
                "body": body,
                "dismissed": p.annotation.dismissed,
                "anchored": p.anchored or not p.annotation.quote,
            }
        )
    user_marks = [
        {
            "kind": p.annotation.kind,
            "label": LABELS.get(p.annotation.kind, p.annotation.kind),
            "quote": p.annotation.quote,
            "anchored": p.anchored,
        }
        for p in placed
        if p.annotation.author == "user" and p.annotation.kind in USER_MARK_KINDS
    ]
    user_note = next(
        (
            p.annotation.body
            for p in placed
            if p.annotation.author == "user" and p.annotation.kind == "note"
        ),
        None,
    )
    return {
        "position": position,
        "turn": turn,
        "question": build_pieces(
            turn.question, [p for p in placed if p.annotation.field == "question"]
        ),
        "answer": build_pieces(turn.answer, [p for p in placed if p.annotation.field == "answer"]),
        "notes": notes,
        "user_marks": user_marks,
        "user_note": (user_note or "").strip() or None,
    }


def plan_context(content: dict | None, selections: dict | None) -> dict | None:
    """The memo with the user's ticks, edits, own questions and notes applied (read-only)."""
    if not content:
        return None
    s = selections or {}
    picked_q, picked_d = s.get("picked_questions") or {}, s.get("picked_directions") or {}
    edited = s.get("edited_questions") or {}
    threads = []
    for t, thread in enumerate(content.get("threads") or []):

        def items(kind: str, texts: list[str], picks: dict, t: int = t) -> list[dict]:
            return [
                {
                    "text": edited.get(f"{kind}:{t}:{i}", text),
                    "edited": f"{kind}:{t}:{i}" in edited,
                    "picked": bool(picks.get(f"{t}:{i}")),
                }
                for i, text in enumerate(texts)
            ]

        threads.append(
            {
                **thread,
                "question_items": items("q", thread.get("questions") or [], picked_q),
                "direction_items": items("d", thread.get("directions") or [], picked_d),
            }
        )
    how = content.get("how_to_ask")
    return {
        "intro": content.get("intro"),
        "threads": threads,
        "leave_alone": content.get("leave_alone") or [],
        "covered": content.get("covered") or [],
        "how_to_ask": how if isinstance(how, dict) else {},
        "how_to_ask_text": how if isinstance(how, str) else None,
        "bring": content.get("bring") or [],
        "for_narrative": content.get("for_narrative") or [],
        "picked_questions": [
            i["text"] for th in threads for i in th["question_items"] if i["picked"]
        ],
        "picked_directions": [
            i["text"] for th in threads for i in th["direction_items"] if i["picked"]
        ],
        "own_questions": s.get("own_questions") or [],
        "free_notes": (s.get("free_notes") or "").strip(),
    }
