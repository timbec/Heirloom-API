"""Admin commands. Run with: uv run python -m app.cli <command> --help"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import delete, select

from app.db import SessionLocal, engine
from app.models import User
from app.security import hash_password

# ─── Frances seed data ──────────────────────────────────────────────────────

_FRANCES_TURNS = [
    {
        "turn_index": 1,
        "question": "Ma, can you tell me about the house on — what was it, Fourth Street?",
        "answer": (
            "Fourth Street. Yes. Well, we — it was my father’s house. No, my grandmother’s. "
            "It was my grandmother’s house and we all — there was a porch. Is that thing on? "
            "[laughs] Linda, is it on? Okay. So there was the porch and the, um, the... my father would "
            "sit there. After. He’d come home all black. Black from the — from the plant. And "
            "my mother wouldn’t let him in the kitchen until he washed at the... there was a sink, "
            "out back, by the coal. By the coal bin. Cold water. Even in winter, cold water."
        ),
        "gold_quote": "He’d come home all black. Black from the — from the plant.",
        "thread_anchor": "there was a porch",
    },
    {
        "turn_index": 2,
        "question": "What about your mother? What did she do?",
        "answer": (
            "Oh, she kept house. Everybody’s mother kept house then. She was a good woman. "
            "Very religious. We went to church every Sunday, St. Stanislaus, everybody did. She was a "
            "good mother. She worked hard. They all worked hard then, people don’t know."
        ),
    },
    {
        "turn_index": 3,
        "question": "Do you remember anything she used to cook?",
        "answer": (
            "Pierogi. Well. Everybody says pierogi. [pause] She had — her hands were always red. "
            "From the, uh, the lye soap. She’d make the dough and her knuckles would crack, right "
            "here, and she’d put lard on them. Lard! Can you imagine. Rub it in like hand cream. "
            "[pause] I don’t know why I remember that."
        ),
        "gold_quote": (
            "She had — her hands were always red. From the, uh, the lye soap. She’d make "
            "the dough and her knuckles would crack, right here, and she’d put lard on them. Lard!"
        ),
    },
    {
        "turn_index": 4,
        "question": "Tell me about meeting Dad.",
        "answer": (
            "Eddie. Eddie was — we met at the dance, at the, the Sokol hall. He had that car. "
            "A Ford. A green — no. No, it was his brother’s car, he didn’t have a car. "
            "[pause] Or was that Walt? Walt had the car. Walt had the green car. [pause] I went with "
            "Walt first, you know. Before your father. For a while. Don’t put that in."
        ),
        "thread_anchor": "we met at the dance, at the, the Sokol hall",
        "retracted": True,
    },
    {
        "turn_index": 5,
        "question": "Okay, Ma, we won’t. What year did you and Dad get married?",
        "answer": (
            "Fifty... fifty-six. No. Fifty-eight. Your brother was born in fifty-nine, so — "
            "[pause] Fifty-eight. June. It rained."
        ),
    },
    {
        "turn_index": 6,
        "question": "What do you remember about the wedding?",
        "answer": (
            "Well, my father, you know, he’d come home from the plant and he’d wash out back. "
            "My mother wouldn’t let him in. There was a sink down in the cellar, by the coal, and "
            "he’d wash there with the cold water, even in the winter. Black. All black from the "
            "plant. [pause] Did I tell you that?"
        ),
        "repeat_of": 1,
    },
    {
        "turn_index": 7,
        "question": "You did, Ma. We were talking about the wedding.",
        "answer": (
            "Were we? Oh. Well, it rained. Everybody said rain was lucky. [pause] Is your sister "
            "coming today? [Linda: Ma, Carol’s in Arizona.] Oh, that’s right. That’s "
            "right. She told me. She called. [pause] What were we saying?"
        ),
        "unable_to_recall": True,
    },
    {
        "turn_index": 8,
        "question": "Tell me about working at Woolworth’s.",
        "answer": (
            "Oh, I loved that. I loved it. The lunch counter. Grilled cheese was thirty-five cents. "
            "Or — no, a quarter. A quarter, I think. And the steel men would come in at the shift "
            "change, all at once, you had to have the coffee ready, forty cups lined up on the counter, "
            "because they’d only have — they had fifteen minutes. Fifteen minutes and then "
            "back. And there was one, he always left a nickel under the saucer. Every day. Never said "
            "a word. Every single day, a nickel under the saucer. I never knew his name."
        ),
        "gold_quote": "Every day. Never said a word. Every single day, a nickel under the saucer.",
    },
    {
        "turn_index": 9,
        "question": "Why did you stop working there?",
        "answer": (
            "Well, when you get married, you — [long pause] I don’t remember. I don’t. "
            "Isn’t that terrible? [pause] I don’t know why I stopped. I liked it there."
        ),
        "unable_to_recall": True,
    },
    {
        "turn_index": 10,
        "question": "That’s okay, Ma. It doesn’t matter.",
        "answer": (
            "My father. When he washed out back, by the coal — he’d sing. Did I tell you "
            "that? He sang in Polish. Every night, washing. I don’t know the words. I never "
            "learned. My mother didn’t want us talking Polish, she wanted us to be American. "
            "[pause] I wish I knew the words."
        ),
        "gold_quote": (
            "He sang in Polish. Every night, washing. I don’t know the words. I never learned."
        ),
        "thread_anchor": "I wish I knew the words.",
    },
]

# Margin-note text from the mockup, keyed by (turn_index, kind). System annotations derived from
# turn fields carry no explanation of their own; the planning pass will write these later.
_FRANCES_NOTES = {
    (1, "keep"): "Concrete and physical. “All black from the plant” tells you more about her "
    "father than any description would.",
    (1, "chase"): "She mentions it twice and moves on. Who else sat there, and what was the "
    "evening like?",
    (3, "keep"): "She pushes past the stock answer (“everybody says pierogi”) to something only "
    "she would remember. This is the voice you want in the final story.",
    (4, "out"): "She said “don’t put that in”, and you agreed. Excluded from the story and from "
    "anything you share. Don’t follow up on Walt or the green car.",
    (4, "chase"): "The story of how she met Eddie never got told. The answer drifted to cars. "
    "Ask about the hall instead.",
    (6, "told"): "The same story as exchange 1, with small differences (here the sink is in the "
    "cellar). Keep one version in the narrative. It also means the wedding question didn’t land.",
    (7, "leave"): "She lost the thread (“What were we saying?”). That’s a reason to change "
    "subject, not a reason to worry. Bring the wedding photograph next time. One usable line: "
    "“Everybody said rain was lucky.” Linda’s aside isn’t Frances’s words, so it stays out of the "
    "narrative.",
    (8, "keep"): "A whole small story in four sentences, in her rhythm.",
    (9, "leave"): "She couldn’t remember and it bothered her (“Isn’t that terrible?”). Don’t ask "
    "again, and don’t let the narrative invent a reason. “I liked it there” is the part to keep.",
    (10, "keep"): "The emotional centre of the session, and she says it plainly.",
    (10, "chase"): "The strongest thread of the day, and she opened it herself. “I wish I knew "
    "the words” is an invitation.",
}
# Whole-turn notes with no highlight ("skip"); no turn field produces these yet.
_FRANCES_SKIP_NOTES = {
    2: "Generic answer. “A good woman”, “worked hard”, “everybody’s mother”. This is what anyone "
    "would say. The one specific detail is St. Stanislaus on Sundays. Next time, ask about a "
    "scene, not about who she was.",
    5: "Settled. June 1958. She corrected herself and checked it against her son’s birth. No "
    "need to ask again.",
}

_FRANCES_PLAN_CONTENT = {
    "intro": (
        "Frances was at her best with things she could see in her mind: the saucer, the lard, "
        "the sink by the coal bin, her father singing. She was weakest on dates, names and ‘what "
        "was she like’ questions. Next time, ask about objects and moments rather than years and "
        "people. Keep it short, and stop when she says ‘What were we saying?’"
    ),
    "threads": [
        {
            "title": "Her father’s singing",
            "why": "The strongest thread of the session, and she opened it herself.",
            "turn_refs": [10],
            "questions": [
                "What did your father’s singing sound like? Was it the same song every night?",
                "Can you hum any of it, even without the words?",
                "Is there anyone who might still know the words: an aunt, a cousin, someone from St. Stanislaus?",
            ],
            "directions": [
                "Why her mother wanted them to be American, and what Polish meant at home",
                "Music in the house and at church",
            ],
        },
        {
            "title": "The nickel under the saucer",
            "why": "A complete little story. She never knew his name, so skip asking who he was.",
            "turn_refs": [8],
            "questions": [
                "What did you do with the nickels?",
                "Did you ever wonder why he did it?",
                "Picture the counter at shift change. What could you hear and smell, and where did you stand?",
            ],
            "directions": [
                "The other women at the counter, and what the job meant to her at that age",
                "What she did with her first pay",
            ],
        },
        {
            "title": "Her mother’s hands",
            "why": "She went past the stock answer to something only she would remember.",
            "turn_refs": [3],
            "questions": [
                "Tell me more about your mother’s hands. What else did she do with them?",
                "Who taught you to make the dough?",
                "Where in the kitchen did she work? Standing, or sitting at a table?",
            ],
            "directions": [
                "The kitchen as a room: who sat where, and what Sunday meals were like",
            ],
        },
        {
            "title": "The dance at the Sokol hall",
            "why": "How she met Eddie never got told. Ask about the hall, not about who else she danced with.",
            "turn_refs": [4],
            "questions": [
                "What do you remember about the Sokol hall: the music, the floor, what you wore?",
                "Who asked whom to dance?",
            ],
            "directions": [
                "Eddie as a young man: what she noticed first about him",
            ],
        },
        {
            "title": "The porch and Fourth Street",
            "why": "Her father sat there after the plant. There is a whole street behind that sentence.",
            "turn_refs": [1],
            "questions": [
                "Who sat on the porch in the evening, and what did you talk about?",
                "What did you do while your father was washing up?",
            ],
            "directions": [
                "The neighbours on Fourth Street",
            ],
        },
    ],
    "leave_alone": [
        {
            "label": "Walt",
            "why": "She asked for this to be left out. If she brings it up again, that’s her call, and yours.",
            "out": True,
        },
        {
            "label": "Why she left Woolworth’s",
            "why": "She couldn’t remember and it upset her. If the answer comes up on its own, good.",
            "out": False,
        },
        {
            "label": "The wedding day",
            "why": "She lost the thread. Try again with the photograph in front of her.",
            "out": False,
        },
    ],
    "covered": [
        {"label": "Washing at the coal bin", "why": "Told twice. One version is enough."},
        {"label": "When they married", "why": "June 1958, settled."},
    ],
    "how_to_ask": {
        "try_instead": (
            "Try instead of “What was your mother like?”: "
            "“Tell me about a Sunday at your house.” A scene gives her something to see. "
            "A person or a year asks her to summarise."
        ),
        "what_worked": (
            "When you said “That’s okay, Ma. It doesn’t matter,” the pressure "
            "lifted and the best answer of the session came next."
        ),
    },
    "bring": [
        "The wedding photograph",
        "A nickel",
        "A recording of Polish hymns or folk songs, if you can find one",
        "Her dough board or rolling pin, if the family still has it",
    ],
    "for_narrative": [
        "Leave out the Walt exchange entirely",
        "Use “my grandmother’s house”: she corrected herself",
        "Tell the coal-bin story once",
        "Don’t supply a reason she left Woolworth’s",
    ],
}

MIN_PASSWORD_LENGTH = 8


async def seed_review() -> None:
    """Seed the Frances transcript and session plan for UI development."""
    from app.models.annotation import Annotation
    from app.models.enums import JobStatus, TranscriptSource
    from app.models.plan import SessionPlan
    from app.models.session import InterviewSession, Transcript, Turn
    from app.models.subject import Subject
    from app.services.annotations import regenerate_system_annotations

    async with SessionLocal() as db:
        # 1. Demo user.
        demo_email = "demo@heirloom.app"
        user = await db.scalar(select(User).where(User.email == demo_email))
        if user is None:
            user = User(
                email=demo_email,
                name="Demo User",
                password_hash=hash_password("demo"),
                is_admin=False,
            )
            db.add(user)
            await db.flush()

        # 2. Subject (replacing any earlier seeded Frances, so the command can be re-run).
        await db.execute(
            delete(Subject).where(Subject.user_id == user.id, Subject.name == "Frances")
        )
        subject = Subject(user_id=user.id, name="Frances")
        db.add(subject)
        await db.flush()

        # 3. Session.
        session = InterviewSession(subject_id=subject.id, title="Session 1")
        db.add(session)
        await db.flush()

        # 4. Transcript.
        full_text = "\n\n".join(f"Q: {t['question']}\nA: {t['answer']}" for t in _FRANCES_TURNS)
        transcript = Transcript(
            session_id=session.id,
            transcript_text=full_text,
            status=JobStatus.COMPLETED,
            source=TranscriptSource.MANUAL,
        )
        db.add(transcript)
        await db.flush()

        # 5. Turns with scores.
        for t in _FRANCES_TURNS:
            turn = Turn(
                transcript_id=transcript.id,
                turn_index=t["turn_index"],
                question=t["question"],
                answer=t["answer"],
                gold_quote=t.get("gold_quote"),
                thread_anchor=t.get("thread_anchor"),
                retracted=t.get("retracted"),
                unable_to_recall=t.get("unable_to_recall"),
                repeat_of=t.get("repeat_of"),
            )
            db.add(turn)
        await db.flush()

        # 6. System annotations, with the mockup's note text, plus the whole-turn notes.
        await regenerate_system_annotations(db, transcript)
        turns_by_index = {
            t.turn_index: t
            for t in await db.scalars(select(Turn).where(Turn.transcript_id == transcript.id))
        }
        for ann in await db.scalars(
            select(Annotation).where(Annotation.transcript_id == transcript.id)
        ):
            index = next(i for i, t in turns_by_index.items() if t.id == ann.turn_id)
            ann.body = _FRANCES_NOTES.get((index, ann.kind))
        for index, body in _FRANCES_SKIP_NOTES.items():
            db.add(
                Annotation(
                    transcript_id=transcript.id,
                    turn_id=turns_by_index[index].id,
                    field="answer",
                    start=0,
                    end=0,
                    quote="",
                    author="system",
                    kind="skip",
                    body=body,
                    dismissed=False,
                )
            )

        # 7. Session plan.
        plan = SessionPlan(
            transcript_id=transcript.id,
            content=_FRANCES_PLAN_CONTENT,
            user_selections={
                "picked_questions": {},
                "picked_directions": {},
                "own_questions": [],
                "free_notes": "",
                "edited_questions": {},
            },
        )
        db.add(plan)
        await db.commit()

        print(
            f"Seeded Frances review:\n"
            f"  user:       {demo_email} / demo\n"
            f"  subject id: {subject.id}\n"
            f"  session id: {session.id}\n"
            f"  transcript id: {transcript.id}"
        )


async def create_user(email: str, name: str, password: str, admin: bool) -> User:
    async with SessionLocal() as db:
        email = email.strip().lower()
        if await db.scalar(select(User).where(User.email == email)):
            raise SystemExit(f"A user with email {email} already exists.")
        user = User(email=email, name=name, password_hash=hash_password(password), is_admin=admin)
        db.add(user)
        await db.commit()
        return user


async def set_password(email: str, password: str) -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise SystemExit(f"No user with email {email}.")
        user.password_hash = hash_password(password)
        await db.commit()


def _read_password(given: str | None) -> str:
    password = given or getpass.getpass("Password: ")
    if given is None and password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords don't match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "create-user":
            password = _read_password(args.password)
            user = await create_user(args.email, args.name, password, args.admin)
            role = "admin" if user.is_admin else "user"
            print(f"Created {role} {user.email} (id {user.id}).")
        elif args.command == "set-password":
            await set_password(args.email, _read_password(args.password))
            print(f"Password updated for {args.email}.")
        elif args.command == "seed-review":
            await seed_review()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="Create a user (no public sign-up yet)")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--admin", action="store_true", help="Can use the admin panel")
    create.add_argument("--password", help="Omit to be prompted (keeps it out of shell history)")

    reset = commands.add_parser("set-password", help="Set a user's password")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password", help="Omit to be prompted")

    commands.add_parser("seed-review", help="Seed Frances transcript + plan for UI development")

    asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
