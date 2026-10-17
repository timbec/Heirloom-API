# Answer key — Transcripts 06 (Frances) & 07 (Dougie)

Written by Claude.ai alongside the two transcripts, as an answer key for checking the scorer. Keep this out of anything fed to the scorer (the report script only reads `*.txt`; `expected.json` holds the short verdicts for the report). Turns are 0-indexed.

## 06 — Frances (memory loss, looping)

| Turn | Expected | What it tests |
|---|---|---|
| 0 | Borderline gold | Specific detail (father washing out back, cold water) buried in false starts and a "is it on?" aside |
| 1 | Flat | Generic "kept house / good woman" boilerplate |
| 2 | **Gold** | Red knuckles, lard as hand cream. Self-aware close ("I don't know why I remember that") |
| 3 | Gold-ish, **sensitive** | Confuses Eddie/Walt and the car; then discloses Walt and says **"Don't put that in."** Synthesis must exclude it. Ideally flagged, not passed through as a gold quote |
| 4 | Flat | Self-corrected date. Factual, not narrative |
| 5 | **Repeat / contradiction** | Loops back to turn 0 instead of answering. Sink moves from "out back" to "in the cellar." Should not double-count as new gold; synthesis must not pick one location as fact |
| 6 | Flat | Present-day drift, confuses who's visiting. Bracketed interviewer interjection inside an answer |
| 7 | **Gold** | Forty cups, fifteen minutes, the nickel under the saucer. Self-corrected price (35¢ → a quarter) — fine to keep the hedge |
| 8 | Low specificity, high charge | Can't remember why she stopped working. Should produce an **open_thread**, not gold |
| 9 | **Gold** (despite repeat) | Third return to the washing story, but adds new material: he sang in Polish, she never learned. The loop is where the best line is. Tests whether the scorer penalises repetition too hard |

**Expected:** ~3–4 gold of 10. Key failures to watch: gold-plating turn 3 without respecting the off-record request; marking turn 9 "rehearsed" because it repeats turn 0.

## 07 — Dougie (terse, word-finding, third speaker)

| Turn | Expected | What it tests |
|---|---|---|
| 0 | Flat | Resistant non-answer |
| 1 | Flat | Can't retrieve the boat name; wife's suggestion rejected. No fact established — synthesis must not name the boat |
| 2 | Flat / rehearsed | Three-word routine answer |
| 3 | **Gold** | Concrete prompt unlocks sensory detail (diesel, wet wool, Erchie's black twist). Proves the "ask concrete, not evaluative" rule |
| 4 | Flat | "Everybody asks that" — classic deflection |
| 5 | **Gold — the hardest case** | Very few words, low surface specificity, boat name inaudible. The charge is all in the 8-second pause, the broken-off "Erchie was —", turning off the TV, "That's all there is." A text-only scorer may underrate this. Should also suggest a **handle-with-care** tier |
| 6 | Gold or high charge | "Now you do." Three words, heavy weight. Tests whether short = flat |
| 7 | Gold (red coat), **conflicting facts** | Ball vs. bus is disputed by a second speaker. Synthesis must not resolve it; the red coat is the safe, agreed detail |
| 8 | Borderline | Present-day loss, word-finding struggle ("the wind — the boats"). Moderate charge |
| 9 | Flat | Boilerplate advice plus fatigue. Session-end signal |

**Expected:** ~3–4 gold of 10. Key failures to watch: underscoring turn 5 because it's short and vague on the page; attributing Moira's lines to Dougie; synthesis naming a boat or picking "bus" or "Ball."

## Format note

Both keep `Q:` / `A:` so the parser can split them. Interjections from third parties are bracketed inside the `A:` block (`[Moira: ...]`, `[Linda: ...]`). Real Whisper output would have no labels and would mostly drop the `[pause]` tags — worth an unlabelled variant later for the condenser/diarization problem.
