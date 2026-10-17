"""Turn scoring, ported from the Laravel ScoringService (prompts unchanged).

Each turn is scored with the three turns before it as context. Turns only need earlier turns'
*text*, not their scores, so they're scored concurrently.
"""

import asyncio
import json
import re
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.config import get_settings
from app.models import ThreadType
from app.services.groq import AIError, chat_completion

# Room for a reasoning model (at low effort) to think before the JSON. Groq counts the requested
# maximum against the per-minute token limit, so don't ask for more than needed.
MAX_TOKENS = 800
TIMEOUT_SECONDS = 60
CONTEXT_TURNS = 3
CONCURRENCY = 2  # parallel calls; with per-minute token limits, more just means more 429s

SYSTEM_PROMPT = """You are scoring a single answer from an oral-history interview between an adult
child and their elderly parent. You are not the interviewer — you only evaluate
what was already said. Never invent details not present in the answer.

Score the answer on three dimensions:

1. specificity (0-10): Does the answer contain a concrete, sensory, or
   idiosyncratic detail (a place, a physical sensation, an exact phrase they
   used, a named person) — or is it a generic statement anyone could give?

2. emotional_charge (0-10): Does the answer carry visible emotional weight —
   hesitation, pride, grief, humor, contradiction — versus flat recitation of
   fact?

3. thread_type: one of "new" | "continuation" | "rehearsed"
   - "new": introduces a topic, name, or detail not previously mentioned
   - "continuation": deepens something already raised in this session
   - "rehearsed": a well-worn anecdote likely told the same way many times
     before (polished, generic phrasing, no new detail even if emotionally
     positive)

Then decide:
- is_gold (boolean): true if this answer contains a line worth preserving
  nearly verbatim in the final narrative (usually specificity >= 7 OR
  emotional_charge >= 7)
- gold_quote (string or null): if is_gold, extract the exact verbatim span
  worth preserving — do not paraphrase it
- open_thread (string or null): if this answer gestures at something left
  unexplored, name it in a few words for the between-session planning pass

Respond with ONLY valid JSON, no preamble, matching this schema:
{"specificity": int, "emotional_charge": int, "thread_type": "new"|"continuation"|"rehearsed", "is_gold": bool, "gold_quote": string|null, "open_thread": string|null}"""  # noqa: E501

USER_PROMPT = """SUBJECT PROFILE: {profile}

RECENT CONTEXT (preceding turns in this session):
{context}

CURRENT TURN:
Q: {question}
A: {answer}"""


class QA(Protocol):
    question: str
    answer: str


class Profile(Protocol):
    name: str
    birth_year: int | None
    places_lived: str | None
    education_profession: str | None
    family_structure: str | None
    life_chapters: str | None
    interests: str | None


class TurnScore(BaseModel):
    """The model's verdict on one turn, validated rather than trusted."""

    specificity: int = Field(ge=0, le=10)
    emotional_charge: int = Field(ge=0, le=10)
    thread_type: ThreadType
    is_gold: bool
    gold_quote: str | None = None
    open_thread: str | None = None
    # A gold quote the model offered that isn't actually in the answer (e.g. lifted from the
    # context turns). Kept for reports, never saved.
    rejected_quote: str | None = Field(default=None, exclude=True)

    @field_validator("gold_quote", "open_thread", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def quote_only_when_gold(self) -> "TurnScore":
        if not self.is_gold:
            self.gold_quote = None
        return self


def build_profile(subject: Profile | None) -> str:
    if subject is None:
        return "Unknown."
    fields = [
        ("Name", subject.name),
        ("Born", subject.birth_year),
        ("Places lived", subject.places_lived),
        ("Education/profession", subject.education_profession),
        ("Family", subject.family_structure),
        ("Life chapters", subject.life_chapters),
        ("Interests", subject.interests),
    ]
    parts = [f"{label}: {value}" for label, value in fields if value not in (None, "")]
    return " | ".join(parts) if parts else "No profile details recorded."


def build_context(previous: Sequence[QA]) -> str:
    if not previous:
        return "(none — this is the first turn)"
    return "\n\n".join(f"Q: {t.question}\nA: {t.answer}" for t in previous)


async def score_turn(profile: str, previous: Sequence[QA], turn: QA) -> TurnScore:
    settings = get_settings()
    options: dict = {"temperature": 0, "response_format": {"type": "json_object"}}
    if settings.groq_scoring_reasoning_effort:
        options["reasoning_effort"] = settings.groq_scoring_reasoning_effort

    reply = await chat_completion(
        USER_PROMPT.format(
            profile=profile,
            context=build_context(previous),
            question=turn.question,
            answer=turn.answer,
        ),
        system=SYSTEM_PROMPT,
        model=settings.groq_scoring_model,
        max_tokens=MAX_TOKENS,
        timeout_seconds=TIMEOUT_SECONDS,
        **options,
    )
    try:
        score = TurnScore.model_validate(json.loads(reply))
    except (ValueError, ValidationError) as exc:
        raise AIError(f"Scoring reply wasn't valid: {reply[:300]}") from exc

    # "Exact verbatim span" is the prompt's instruction; enforce it. The turn stays gold.
    if score.gold_quote and not is_verbatim(score.gold_quote, turn.answer):
        score.rejected_quote, score.gold_quote = score.gold_quote, None
    return score


async def score_turns(profile: str, turns: Sequence[QA]) -> list[TurnScore | AIError]:
    """Score every turn concurrently. A failed turn comes back as its AIError, so one bad reply
    doesn't lose the rest."""
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(index: int) -> TurnScore | AIError:
        async with limit:
            try:
                return await score_turn(
                    profile, turns[max(0, index - CONTEXT_TURNS) : index], turns[index]
                )
            except AIError as exc:
                return exc

    return list(await asyncio.gather(*(one(i) for i in range(len(turns)))))


def _normalise(text: str) -> str:
    text = re.sub(r"[‘’“”\"]", "'", text)  # any quote mark counts as any other
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.replace(" — ", " ").replace("—", " ").replace(" -- ", " ")


def is_verbatim(quote: str, answer: str) -> bool:
    """Whether a gold quote really appears in the answer (ignoring quote style and spacing)."""
    return _normalise(quote).strip("\"' .") in _normalise(answer)
