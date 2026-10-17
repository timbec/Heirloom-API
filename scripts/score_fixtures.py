"""Score the sample interviews and write a report for checking the scoring by hand.

    uv run python -m scripts.score_fixtures [--models openai/gpt-oss-120b]
                                             [--prompts v1 v2] [--only frances-kowalski ...]
                                             [--interviews DIR] [--out reports/]

Uses the real AI API (key from .env). Doesn't touch the database. Each interview is a .txt file;
profiles come from subjects.json and expected verdicts from expected.json in the same folder
(both optional; neither is ever sent to the model).
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
from app.services.scoring import PROMPTS, TurnScore, build_profile, is_verbatim, score_turns
from app.services.turns import ParsedTurn, parse_turns

DEFAULT_INTERVIEWS = Path(__file__).parent.parent / "tests" / "fixtures" / "interviews"
EMPTY_PROFILE = dict.fromkeys(
    ["birth_year", "places_lived", "education_profession", "family_structure", "life_chapters",
     "interests"]
)  # fmt: skip
SENSITIVITY_MARK = {"handle_with_care": " ⚠care", "off_record": " ⛔off-record"}


def short(text: str, length: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1] + "…"


def cell(result: TurnScore | AIError) -> str:
    if isinstance(result, AIError):
        return "failed"
    gold = " ★" if result.is_gold else ""
    flag = SENSITIVITY_MARK.get(result.sensitivity or "", "")
    return f"{result.specificity} / {result.emotional_charge} / {result.thread_type}{gold}{flag}"


async def run(turns: list[ParsedTurn], profile: str, configs: list[tuple[str, str]]) -> dict:
    settings = get_settings()
    results = {}
    for model, prompt in configs:
        settings.groq_scoring_model = model
        start = time.monotonic()
        scores = await score_turns(profile, turns, PROMPTS[prompt])
        results[f"{model.split('/')[-1]} {prompt}"] = (scores, time.monotonic() - start)
    return results


def report_section(
    name: str, turns: list[ParsedTurn], results: dict, expected: list[str] | None
) -> list[str]:
    configs = list(results)
    lines = [f"## {name}", ""]
    for config, (scores, seconds) in results.items():
        failed = sum(isinstance(s, AIError) for s in scores)
        gold = sum(isinstance(s, TurnScore) and s.is_gold for s in scores)
        lines.append(
            f"- **{config}**: {len(turns)} turns in {seconds:.0f}s, {gold} gold, {failed} failed"
        )
    lines += [
        "",
        "Scores are specificity / emotional charge / thread type; ★ gold, ⚠ handle with care, "
        "⛔ off the record.",
        "",
    ]
    header = "| # | Question | " + ("Expected | " if expected else "") + " | ".join(configs) + " |"
    lines += [header, "|---|---|" + ("---|" if expected else "") + "---|" * len(configs)]
    for i, turn in enumerate(turns):
        exp = f"{expected[i]} | " if expected else ""
        cells = " | ".join(cell(results[c][0][i]) for c in configs)
        lines.append(f"| {i} | {short(turn.question, 50) or '(no question)'} | {exp}{cells} |")

    for config in configs:
        lines += ["", f"### {config}: gold quotes and open threads", ""]
        for i, (turn, score) in enumerate(zip(turns, results[config][0], strict=True)):
            if isinstance(score, AIError):
                lines.append(f"- Turn {i}: **failed**: {short(str(score), 160)}")
                continue
            if score.gold_quote:
                ok = is_verbatim(score.gold_quote, turn.answer)
                check = "verbatim" if ok else "**NOT verbatim**"
                lines.append(f"- Turn {i} ★ ({check}): > {score.gold_quote}")
            if score.rejected_quote:
                lines.append(f"- Turn {i} ★ quote **rejected**: > {score.rejected_quote}")
            if score.open_thread:
                lines.append(f"- Turn {i} open thread: *{score.open_thread}*")
    lines += ["", "<details><summary>Turns as parsed</summary>", ""]
    for i, turn in enumerate(turns):
        lines += [f"**{i}. Q:** {turn.question or '(none)'}", "", "```", turn.answer, "```", ""]
    lines += ["</details>", ""]
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=[get_settings().groq_scoring_model])
    parser.add_argument("--prompts", nargs="+", default=["v1"], choices=sorted(PROMPTS))
    parser.add_argument("--only", nargs="+", help="interview file names (without .txt)")
    parser.add_argument("--interviews", type=Path, default=DEFAULT_INTERVIEWS)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    args = parser.parse_args()

    def load(name: str) -> dict:
        path = args.interviews / name
        return json.loads(path.read_text()) if path.exists() else {}

    profiles, expectations = load("subjects.json"), load("expected.json")
    configs = [(m, p) for m in args.models for p in args.prompts]
    paths = sorted(args.interviews.glob("*.txt"))
    if args.only:
        paths = [p for p in paths if p.stem in args.only]

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    described = ", ".join(f"{m} with prompt {p}" for m, p in configs)
    effort = get_settings().groq_scoring_reasoning_effort or "not sent"
    lines = [f"# Turn scoring check, {stamp}", "", f"{described}. Reasoning effort: {effort}.", ""]
    for path in paths:
        turns = parse_turns(path.read_text())
        data = profiles.get(path.stem)
        profile = build_profile(SimpleNamespace(**{**EMPTY_PROFILE, **data}) if data else None)
        print(f"Scoring {path.stem} ({len(turns)} turns)…", flush=True)
        results = await run(turns, profile, configs)
        title = data["name"] if data else path.stem
        lines += report_section(title, turns, results, expectations.get(path.stem))

    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"turn-scoring-{stamp}.md"
    out.write_text("\n".join(lines))
    print(f"Report: {out.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
