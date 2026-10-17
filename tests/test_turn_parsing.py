from pathlib import Path

import pytest

from app.services.turns import TurnParseError, parse_turns

FIXTURES = Path(__file__).parent / "fixtures" / "interviews"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("brigid-connolly", 7), ("ron-ashworth", 5), ("dot-ferreira", 5)],
)
def test_qa_fixtures_give_one_turn_per_question(name: str, expected: int):
    turns = parse_turns(fixture(name))
    assert len(turns) == expected
    assert all(t.question and t.answer for t in turns)
    assert not any(t.answer.startswith("A:") for t in turns)


def test_qa_answer_text_and_stage_directions_are_kept():
    first = parse_turns(fixture("dot-ferreira"))[1]
    assert first.question == "Why did you come to England?"
    assert first.answer.startswith("My aunt had come the year before")
    assert "[shakes head]" in first.answer


def test_inline_qa_still_works():
    turns = parse_turns("Q: Where were you born? A: Leeds. Q: And then? A: We moved to Hull.")
    assert [(t.question, t.answer) for t in turns] == [
        ("Where were you born?", "Leeds."),
        ("And then?", "We moved to Hull."),
    ]


def test_naturalistic_transcript_keeps_stories_whole():
    turns = parse_turns(fixture("frank-delgado"))
    questions = [t.question for t in turns]

    # MARCUS is identified as the interviewer; only real questions open turns.
    assert questions[0].endswith("When did you actually open that?")
    assert "Did you like it? The shop." in questions
    assert (
        "No?" not in questions and "You okay?" not in questions and "Twenty-six." not in questions
    )
    assert 5 <= len(turns) <= 8

    # Interjections stay inside the answer, labelled; FRANK's lines are labelled too.
    lease = turns[0].answer
    assert "FRANK: Huh. Well anyway. Sixty-eight" in lease
    assert "MARCUS: Twenty-six." in lease
    assert "Salvador" in lease

    # The Carol moment stays together with its [pause].
    smell = next(t for t in turns if t.question == "Did you like it? The shop.")
    assert "you still smell like Blackstone Avenue" in smell.answer
    assert "[pause]" in smell.answer
    assert "I'd rather you bring it up than not" in smell.answer


def test_one_off_labels_are_not_speakers():
    text = "Subject: Rose, born 1938.\nQ: Where were you born?\nA: Leeds.\nNote: she smiled."
    [turn] = parse_turns(text)
    assert turn.answer == "Leeds.\nNote: she smiled."


def test_consecutive_questions_merge():
    [turn] = parse_turns("Q: Where were you born?\nQ: Sorry, I mean which town?\nA: Leeds.")
    assert turn.question == "Where were you born? Sorry, I mean which town?"


def test_interviewer_found_by_questions_not_order():
    text = (
        "MUM: I've been thinking about the farm.\n"
        "ANNA: What do you remember about it?\n"
        "MUM: The geese, mostly. They chased me.\n"
        "ANNA: Were you scared of them?\n"
        "MUM: Terrified."
    )
    turns = parse_turns(text)
    assert turns[0].question == ""  # Mum spoke before any question
    assert turns[0].answer == "MUM: I've been thinking about the farm."
    assert [t.question for t in turns[1:]] == [
        "What do you remember about it?",
        "Were you scared of them?",
    ]


@pytest.mark.parametrize(
    "text",
    ["Just a block of text with no speakers at all.", "Q: Only questions?\nQ: Anyone?"],
)
def test_unparseable_transcripts(text: str):
    with pytest.raises(TurnParseError):
        parse_turns(text)
