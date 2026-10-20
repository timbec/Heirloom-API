from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser
from app.api.ownership import get_owned_annotation, get_owned_transcript
from app.models.annotation import Annotation
from app.models.plan import SessionPlan
from app.models.session import Turn
from app.services.annotations import reanchor

router = APIRouter(prefix="/heirloom/v1/transcripts/{transcript_id}", tags=["review"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class AnnotationOut(BaseModel):
    id: int
    turn_id: int
    field: str
    start: int | None
    end: int | None
    quote: str
    author: str
    kind: str
    body: str | None
    dismissed: bool
    anchored: bool

    model_config = {"from_attributes": True}


class TurnOut(BaseModel):
    id: int
    turn_index: int
    question: str
    answer: str
    retracted: bool | None
    unable_to_recall: bool | None
    repeat_of: int | None
    thread_anchor: str | None
    annotations: list[AnnotationOut]

    model_config = {"from_attributes": True}


class ReviewOut(BaseModel):
    transcript_id: int
    session_title: str | None
    subject_name: str
    turns: list[TurnOut]
    plan: dict | None


class AnnotationCreate(BaseModel):
    turn_id: int
    field: str
    start: int
    end: int
    quote: str
    kind: str
    body: str | None = None


class AnnotationUpdate(BaseModel):
    kind: str | None = None
    body: str | None = None
    dismissed: bool | None = None


class DismissUpdate(BaseModel):
    dismissed: bool


class SelectionsUpdate(BaseModel):
    picked_questions: dict = {}
    picked_directions: dict = {}
    own_questions: list = []
    free_notes: str = ""
    edited_questions: dict = {}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _annotation_out(ann: Annotation, text: str) -> AnnotationOut:
    pos = reanchor(ann, text)
    return AnnotationOut(
        id=ann.id,
        turn_id=ann.turn_id,
        field=ann.field,
        start=pos[0] if pos else None,
        end=pos[1] if pos else None,
        quote=ann.quote,
        author=ann.author,
        kind=ann.kind,
        body=ann.body,
        dismissed=ann.dismissed,
        anchored=pos is not None,
    )


def _turn_text(turn: Turn, field: str) -> str:
    return turn.answer if field == "answer" else turn.question


def visible_turns(turns: list[Turn]) -> list[Turn]:
    return [t for t in turns if not t.retracted]


def _inline_mark(text: str, annotations: list[Annotation]) -> str:
    """Apply system and user annotation marks inline as markdown syntax."""
    # Sort user keep/chase/leave annotations by start offset for inline insertion.
    # We build the marked string by iterating through spans.
    # For simplicity, apply system-level marks first (whole-answer marks), then
    # handle span annotations via character-level replacement.

    # Check for whole-answer system marks (out/leave/told) — these wrap the whole text.
    system_by_kind = {a.kind: a for a in annotations if a.author == "system"}

    # Span annotations from both system and user, sorted by start.
    span_anns = [
        a for a in annotations
        if a.kind in ("keep", "chase") and not a.dismissed
    ]
    user_leave = [a for a in annotations if a.author == "user" and a.kind == "leave" and not a.dismissed]

    if not span_anns and not user_leave:
        # Apply whole-text wrapping.
        if "leave" in system_by_kind and not system_by_kind["leave"].dismissed:
            return "{leave alone: " + text + "}"
        if "told" in system_by_kind and not system_by_kind["told"].dismissed:
            return "(told before: " + text + ")"
        return text

    # Build marked text with inline spans.
    result = []
    pos = 0

    # Collect all non-overlapping span annotations, sorted by start.
    all_spans: list[tuple[int, int, str, str]] = []  # (start, end, prefix, suffix)
    for a in span_anns:
        if a.start is None:
            continue
        if a.author == "system" and a.kind == "keep":
            all_spans.append((a.start, a.end, "==", "=="))
        elif a.author == "system" and a.kind == "chase":
            all_spans.append((a.start, a.end, "[follow up: ", "]"))
        elif a.author == "user" and a.kind == "keep":
            all_spans.append((a.start, a.end, "==", "==(you)"))
        elif a.author == "user" and a.kind == "chase":
            all_spans.append((a.start, a.end, "[follow up (you): ", "]"))
    for a in user_leave:
        if a.start is None:
            continue
        all_spans.append((a.start, a.end, "{leave alone (you): ", "}"))

    all_spans.sort(key=lambda x: x[0])

    for start, end, prefix, suffix in all_spans:
        if start < pos:
            continue
        result.append(text[pos:start])
        result.append(prefix + text[start:end] + suffix)
        pos = end

    result.append(text[pos:])
    return "".join(result)


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/review", response_model=ReviewOut)
async def get_review(transcript_id: int, db: DB, user: CurrentUser) -> ReviewOut:
    transcript = await get_owned_transcript(db, transcript_id, user)

    result = await db.execute(
        select(Turn)
        .where(Turn.transcript_id == transcript_id)
        .options(selectinload(Turn.annotations))
        .order_by(Turn.turn_index)
    )
    turns = result.scalars().all()

    plan_row = await db.scalar(
        select(SessionPlan).where(SessionPlan.transcript_id == transcript_id)
    )

    turn_outs = []
    for turn in turns:
        anns = [_annotation_out(a, _turn_text(turn, a.field)) for a in turn.annotations]
        turn_outs.append(
            TurnOut(
                id=turn.id,
                turn_index=turn.turn_index,
                question=turn.question,
                answer=turn.answer,
                retracted=turn.retracted,
                unable_to_recall=turn.unable_to_recall,
                repeat_of=turn.repeat_of,
                thread_anchor=turn.thread_anchor,
                annotations=anns,
            )
        )

    plan_data: dict | None = None
    if plan_row is not None:
        plan_data = {
            "content": plan_row.content,
            "user_selections": plan_row.user_selections,
        }

    return ReviewOut(
        transcript_id=transcript_id,
        session_title=transcript.session.title,
        subject_name=transcript.session.subject.name,
        turns=turn_outs,
        plan=plan_data,
    )


@router.post("/annotations", response_model=AnnotationOut, status_code=201)
async def create_annotation(
    transcript_id: int, payload: AnnotationCreate, db: DB, user: CurrentUser
) -> AnnotationOut:
    transcript = await get_owned_transcript(db, transcript_id, user)

    turn = await db.get(Turn, payload.turn_id)
    if turn is None or turn.transcript_id != transcript.id:
        raise HTTPException(status_code=404, detail="Turn not found.")

    text = _turn_text(turn, payload.field)
    if text[payload.start : payload.end] != payload.quote:
        raise HTTPException(
            status_code=422,
            detail="quote does not match turn text at the given offsets.",
        )

    ann = Annotation(
        transcript_id=transcript_id,
        turn_id=payload.turn_id,
        field=payload.field,
        start=payload.start,
        end=payload.end,
        quote=payload.quote,
        author="user",
        kind=payload.kind,
        body=payload.body,
        dismissed=False,
    )
    db.add(ann)
    await db.flush()
    await db.refresh(ann)
    return _annotation_out(ann, text)


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
async def update_annotation(
    transcript_id: int, annotation_id: int, payload: AnnotationUpdate, db: DB, user: CurrentUser
) -> AnnotationOut:
    ann = await get_owned_annotation(db, annotation_id, user)
    if ann.transcript_id != transcript_id:
        raise HTTPException(status_code=404, detail="Annotation not found.")

    if ann.author == "system" and (payload.kind is not None or payload.body is not None):
        raise HTTPException(status_code=403, detail="Cannot change kind or body of system annotations.")

    if payload.kind is not None:
        ann.kind = payload.kind
    if payload.body is not None:
        ann.body = payload.body
    if payload.dismissed is not None:
        ann.dismissed = payload.dismissed

    await db.flush()

    turn = await db.get(Turn, ann.turn_id)
    text = _turn_text(turn, ann.field)
    return _annotation_out(ann, text)


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(
    transcript_id: int, annotation_id: int, db: DB, user: CurrentUser
) -> Response:
    ann = await get_owned_annotation(db, annotation_id, user)
    if ann.transcript_id != transcript_id:
        raise HTTPException(status_code=404, detail="Annotation not found.")
    if ann.author == "system":
        raise HTTPException(status_code=403, detail="Cannot delete system annotations.")
    await db.delete(ann)
    await db.flush()
    return Response(status_code=204)


@router.patch("/annotations/{annotation_id}/dismiss", response_model=AnnotationOut)
async def dismiss_annotation(
    transcript_id: int, annotation_id: int, payload: DismissUpdate, db: DB, user: CurrentUser
) -> AnnotationOut:
    ann = await get_owned_annotation(db, annotation_id, user)
    if ann.transcript_id != transcript_id:
        raise HTTPException(status_code=404, detail="Annotation not found.")
    ann.dismissed = payload.dismissed
    await db.flush()
    turn = await db.get(Turn, ann.turn_id)
    text = _turn_text(turn, ann.field)
    return _annotation_out(ann, text)


@router.put("/plan/selections", response_model=dict)
async def update_plan_selections(
    transcript_id: int, payload: SelectionsUpdate, db: DB, user: CurrentUser
) -> dict:
    await get_owned_transcript(db, transcript_id, user)
    plan = await db.scalar(select(SessionPlan).where(SessionPlan.transcript_id == transcript_id))
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan found for this transcript.")
    plan.user_selections = payload.model_dump()
    await db.flush()
    return plan.user_selections


@router.get("/export.md", response_class=PlainTextResponse)
async def export_markdown(transcript_id: int, db: DB, user: CurrentUser) -> str:
    transcript = await get_owned_transcript(db, transcript_id, user)

    result = await db.execute(
        select(Turn)
        .where(Turn.transcript_id == transcript_id)
        .options(selectinload(Turn.annotations))
        .order_by(Turn.turn_index)
    )
    all_turns = result.scalars().all()

    session_title = transcript.session.title or f"Session {transcript.session_id}"
    subject_name = transcript.session.subject.name
    interviewer = "Linda"  # default interviewer label

    lines = [
        f"# {subject_name}, {session_title}: marked-up transcript",
        "",
        "Marks: ==keep word for word==  [follow up: ...]  {leave alone: ...}  "
        "~~left out on request~~  (told before: ...)",
        "Marks tagged (you) are yours.",
        "",
    ]

    for turn in visible_turns(all_turns):
        lines.append(f"**{interviewer}:** {turn.question}")
        lines.append("")

        answer_anns = [a for a in turn.annotations if a.field == "answer"]
        marked_answer = _inline_mark(turn.answer, answer_anns)
        lines.append(f"**{subject_name}:** {marked_answer}")
        lines.append("")

        for ann in turn.annotations:
            if ann.body:
                dismissed_tag = " (you disagreed)" if ann.dismissed else ""
                lines.append(f"> {ann.kind}{dismissed_tag}: {ann.body}")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)
