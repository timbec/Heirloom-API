"""Split a transcript into question/answer turns.

Handles `Q:`/`A:` transcripts (the old format, including inline `Q: … A: …`) and naturalistic
ones with named speakers (`MARCUS:` / `FRANK:`). A new turn starts only at a real question from
the interviewer; short interjections ("No?", "Twenty-six.", "You okay?") stay inside the answer,
so a story told across several back-and-forths isn't chopped into fragments.
"""

import re
from collections import Counter
from dataclasses import dataclass

# "NAME: text" at the start of a line. Up to four words, starting with a capital letter.
_LABEL = re.compile(r"^([A-Z][\w.'’-]*(?: [\w.'’-]+){0,3})\s*:\s*(.*)$")
_INLINE_QA = re.compile(r"\s+(?=(?:Q|A):\s)")
_STAGE_DIRECTION = re.compile(r"\[[^\]]*\]")

# An interviewer line opens a new turn if it's a question of at least this many words…
QUESTION_MIN_WORDS = 3
# …or a statement-style prompt ("Tell me about the shop on Blackstone.") at least this long.
PROMPT_MIN_WORDS = 12


class TurnParseError(ValueError):
    pass


@dataclass
class Utterance:
    speaker: str
    text: str


@dataclass
class ParsedTurn:
    question: str
    answer: str


def _utterances(text: str) -> list[Utterance]:
    """Lines grouped by speaker. A label only counts if it recurs (or is Q/A), so one-off
    lines such as "Subject: …" or "Note: …" aren't mistaken for speakers. Text before the first
    speaker is dropped; unlabelled lines continue the previous speaker."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labels = Counter(m.group(1) for line in lines if (m := _LABEL.match(line)))
    speakers = {label for label, count in labels.items() if count >= 2 or label in ("Q", "A")}

    utterances: list[Utterance] = []
    for line in lines:
        match = _LABEL.match(line)
        if match and match.group(1) in speakers:
            utterances.append(Utterance(match.group(1), match.group(2).strip()))
        elif utterances:
            utterances[-1].text = f"{utterances[-1].text}\n{line}".strip()
    return [u for u in utterances if u.text]


def _interviewer(utterances: list[Utterance]) -> str:
    speakers = list(dict.fromkeys(u.speaker for u in utterances))  # first-appearance order
    if "Q" in speakers:
        return "Q"

    def question_rate(speaker: str) -> float:
        own = [u for u in utterances if u.speaker == speaker]
        return sum("?" in u.text for u in own) / len(own)

    # Most questions asked; ties go to whoever spoke first.
    return max(speakers, key=lambda s: (question_rate(s), -speakers.index(s)))


def _word_count(text: str) -> int:
    return len(_STAGE_DIRECTION.sub("", text).split())


def _opens_turn(text: str) -> bool:
    words = _word_count(text)
    return ("?" in text and words >= QUESTION_MIN_WORDS) or words >= PROMPT_MIN_WORDS


def parse_turns(text: str) -> list[ParsedTurn]:
    utterances = _utterances(_INLINE_QA.sub("\n", text))
    if len({u.speaker for u in utterances}) < 2:
        raise TurnParseError(
            "Couldn't find questions and answers in this transcript. Start each line with who "
            "is speaking, for example 'Q:' and 'A:', or names like 'MARCUS:' and 'FRANK:'."
        )

    interviewer = _interviewer(utterances)
    # Q/A transcripts need no names in the answer; named ones keep who said what.
    show_names = not {u.speaker for u in utterances} <= {"Q", "A"}

    turns: list[tuple[list[str], list[str]]] = []  # (question parts, answer lines)
    for u in utterances:
        if u.speaker == interviewer:
            if turns and not turns[-1][1]:
                turns[-1][0].append(u.text)  # consecutive questions before any answer
                continue
            # Every "Q:" is a deliberate question; named interviewers also interject.
            if not turns or interviewer == "Q" or _opens_turn(u.text):
                turns.append(([u.text], []))
                continue
        elif not turns:
            turns.append(([], []))  # the subject spoke before any question
        turns[-1][1].append(f"{u.speaker}: {u.text}" if show_names else u.text)

    parsed = [ParsedTurn(" ".join(q).strip(), "\n".join(a).strip()) for q, a in turns]
    parsed = [t for t in parsed if t.answer]
    if not parsed:
        raise TurnParseError("Found questions but no answers in this transcript.")
    return parsed
