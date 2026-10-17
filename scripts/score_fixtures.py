"""Score the sample interviews and write a report for checking the scoring by hand.

    uv run python -m scripts.score_fixtures [--models openai/gpt-oss-20b openai/gpt-oss-120b]
                                             [--interviews DIR] [--out reports/]

Uses the real Groq API (key from .env). Doesn't touch the database. Each interview is a .txt
file; profiles come from subjects.json in the same folder (optional).
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.services.groq import AIError
from app.services.scoring import TurnScore, build_profile, is_verbatim, score_turns
from app.services.turns import ParsedTurn, parse_turns

DEFAULT_INTERVIEWS = Path(__file__).parent.parent / "tests" / "fixtures" / "interviews"
EMPTY_PROFILE = dict.fromkeys(
    ["birth_year", "places_lived", "education_profession", "family_structure", "life_chapters",
     "interests"]
)  # fmt: skip


def short(text: str, length: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1] + "…"


def cell(result: TurnScore | AIError) -> str:
    if isinstance(result, AIError):
        return "failed"
    gold = " ★" if result.is_gold else ""
    return f"{result.specificity} / {result.emotional_charge} / {result.thread_type}{gold}"


async def score_interview(
    turns: list[ParsedTurn], profile: str, models: list[str]
) -> dict[str, tuple[list[TurnScore | AIError], float]]:
    settings = get_settings()
    results = {}
    for model in models:
        settings.groq_scoring_model = model
        start = time.monotonic()
        results[model] = (await score_turns(profile, turns), time.monotonic() - start)
    return results


def report_section(name: str, turns: list[ParsedTurn], results: dict) -> list[str]:
    models = list(results)
    lines = [f"## {name}", ""]
    for model, (scores, seconds) in results.items():
        failed = sum(isinstance(s, AIError) for s in scores)
        gold = sum(isinstance(s, TurnScore) and s.is_gold for s in scores)
        lines.append(
            f"- **{model}**: {len(turns)} turns in {seconds:.1f}s, {gold} gold, {failed} failed"
        )
    lines += ["", "Scores are specificity / emotional charge / thread type; ★ = gold.", ""]
    lines.append("| # | Question | " + " | ".join(models) + " |")
    lines.append("|---|---|" + "---|" * len(models))
    for i, turn in enumerate(turns):
        cells = " | ".join(cell(results[m][0][i]) for m in models)
        lines.append(f"| {i} | {short(turn.question, 60) or '(no question)'} | {cells} |")

    for model in models:
        lines += ["", f"### {model}: gold quotes and open threads", ""]
        for i, (turn, score) in enumerate(zip(turns, results[model][0], strict=True)):
            if isinstance(score, AIError):
                lines.append(f"- Turn {i}: **failed**: {short(str(score), 160)}")
                continue
            if score.gold_quote:
                check = (
                    "verbatim" if is_verbatim(score.gold_quote, turn.answer) else "**NOT verbatim**"
                )
                lines.append(f"- Turn {i} ★ ({check}): > {score.gold_quote}")
            if score.rejected_quote:
                lines.append(
                    f"- Turn {i} ★ quote **rejected** (not in answer): > {score.rejected_quote}"
                )
            if score.open_thread:
                lines.append(f"- Turn {i} open thread: *{score.open_thread}*")
    lines += ["", "<details><summary>Turns as parsed</summary>", ""]
    for i, turn in enumerate(turns):
        lines += [f"**{i}. Q:** {turn.question or '(none)'}", "", "```", turn.answer, "```", ""]
    lines += ["</details>", ""]
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models", nargs="+", default=["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    )
    parser.add_argument("--interviews", type=Path, default=DEFAULT_INTERVIEWS)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    args = parser.parse_args()

    profiles_file = args.interviews / "subjects.json"
    profiles = json.loads(profiles_file.read_text()) if profiles_file.exists() else {}

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    lines = [
        f"# Turn scoring check, {stamp}",
        "",
        f"Models: {', '.join(args.models)}. "
        f"Reasoning effort: {get_settings().groq_scoring_reasoning_effort or 'not sent'}.",
        "",
    ]
    for path in sorted(args.interviews.glob("*.txt")):
        turns = parse_turns(path.read_text())
        profile_data = profiles.get(path.stem)
        profile = build_profile(
            SimpleNamespace(**{**EMPTY_PROFILE, **profile_data}) if profile_data else None
        )
        print(f"Scoring {path.stem} ({len(turns)} turns)…", flush=True)
        results = await score_interview(turns, profile, args.models)
        lines += report_section(profile_data["name"] if profile_data else path.stem, turns, results)

    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"turn-scoring-{stamp}.md"
    out.write_text("\n".join(lines))
    print(f"Report: {out.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
