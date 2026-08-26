"""Phase 0 follow-up: can sample agreement replace the model's flat self-confidence?

phase0_smoke.py found that `confidence` comes back ~0.95 on every case, including
a deliberately ambiguous one. That field cannot gate a review queue.

The proposed replacement: sample the same message K times at a non-zero
temperature and use how often the samples agree as the confidence signal.

This script only tells us something if agreement DISCRIMINATES -- unanimous on
the clear cases, split on the genuinely hard ones. So it runs both:
  * the five clear cases from phase0_smoke (expected: unanimous)
  * five hard cases with no obvious right answer (expected: split)

If everything comes back unanimous, the fix does not work either and the review
trigger has to come from somewhere else.

Run:  .venv/Scripts/python.exe scripts/phase0_confidence.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collections import Counter

from openai import OpenAI

from mail_analyzer.verdict import MessageVerdict, is_grounded
from phase0_smoke import BASE_URL, CASES, MODEL, SYSTEM_PROMPT

SAMPLES = 3
TEMPERATURE = 0.7
SEEDS = (11, 29, 47)

# Deliberately hard: real supplier-reply shapes where reasonable readers disagree.
# No expected status -- the question is whether the samples split, not who is right.
HARD_CASES: list[tuple[str, str]] = [
    (
        "podpisany zalacznik + pytanie",
        "Dzien dobry,\n\nW zalaczeniu odsylam podpisany dokument. Prosze o potwierdzenie,\n"
        "czy to wszystko czego Panstwo potrzebuja.\n\nPozdrawiam",
    ),
    (
        "przekazanie do dzialu prawnego",
        "Szanowni Panstwo,\n\nPrzekazuje sprawe do naszego dzialu prawnego. Beda sie Panstwo\n"
        "kontaktowac bezposrednio z mecenasem Nowakiem.\n\nZ powazaniem",
    ),
    (
        "miekka odmowa",
        "Dzien dobry,\n\nObecnie nie widzimy mozliwosci przystapienia do tej zmiany\n"
        "w proponowanym ksztalcie.\n\nPozdrawiam",
    ),
    (
        "zgoda czesciowa",
        "Dzien dobry,\n\nZgadzamy sie na punkty 1 i 2, natomiast punkt 3 wymaga dyskusji.\n\n"
        "Pozdrawiam",
    ),
    (
        "brak uwag",
        "Dzien dobry,\n\nNie mamy uwag.\n\nPozdrawiam",
    ),
]

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "message_verdict",
        "strict": True,
        "schema": MessageVerdict.model_json_schema(),
    },
}


def sample_verdicts(client: OpenAI, body: str) -> tuple[list[MessageVerdict], float]:
    """Classify one message SAMPLES times at TEMPERATURE, one distinct seed each."""
    verdicts: list[MessageVerdict] = []
    started = time.perf_counter()
    for seed in SEEDS[:SAMPLES]:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
            response_format=SCHEMA,
            temperature=TEMPERATURE,
            seed=seed,
            max_tokens=400,
        )
        verdicts.append(MessageVerdict.model_validate_json(response.choices[0].message.content or ""))
    return verdicts, time.perf_counter() - started


def report(name: str, body: str, verdicts: list[MessageVerdict], elapsed: float, expected: str | None) -> float:
    """Print one case and return its agreement fraction."""
    votes = Counter(v.status for v in verdicts)
    winner, winner_votes = votes.most_common(1)[0]
    agreement = winner_votes / len(verdicts)
    self_conf = statistics.mean(v.confidence for v in verdicts)
    grounded = sum(is_grounded(v.evidence, body) for v in verdicts)

    verdict_line = f"{winner}  ({'/'.join(f'{s}:{n}' for s, n in votes.most_common())})"
    marker = ""
    if expected is not None:
        marker = "  PASS" if winner == expected else f"  FAIL expected={expected}"

    print(f"{name}{marker}")
    print(f"      majority   : {verdict_line}")
    print(f"      agreement  : {agreement:.2f}   self-reported: {self_conf:.2f}")
    print(f"      grounded   : {grounded}/{len(verdicts)}   {elapsed:.1f}s")
    return agreement


def main() -> int:
    client = OpenAI(base_url=BASE_URL, api_key="lm-studio")

    print(f"model       : {MODEL}")
    print(f"sampling    : {SAMPLES} samples @ temperature {TEMPERATURE}, seeds {SEEDS[:SAMPLES]}")
    print("=" * 78)

    print("\nCLEAR CASES  (agreement should be 1.00)\n")
    clear_agreements: list[float] = []
    for name, expected, body in CASES:
        verdicts, elapsed = sample_verdicts(client, body)
        clear_agreements.append(report(name, body, verdicts, elapsed, expected))
        print()

    print("\nHARD CASES  (agreement should drop below 1.00 if the signal works)\n")
    hard_agreements: list[float] = []
    for name, body in HARD_CASES:
        verdicts, elapsed = sample_verdicts(client, body)
        hard_agreements.append(report(name, body, verdicts, elapsed, None))
        print()

    print("=" * 78)
    print(f"clear cases : mean agreement {statistics.mean(clear_agreements):.2f}  "
          f"(unanimous {clear_agreements.count(1.0)}/{len(clear_agreements)})")
    print(f"hard cases  : mean agreement {statistics.mean(hard_agreements):.2f}  "
          f"(unanimous {hard_agreements.count(1.0)}/{len(hard_agreements)})")

    discriminates = statistics.mean(hard_agreements) < statistics.mean(clear_agreements)
    print()
    if discriminates:
        print("VERDICT: agreement separates hard from clear -- usable as a review trigger.")
    else:
        print("VERDICT: agreement does NOT separate hard from clear -- needs another trigger.")
    return 0 if discriminates else 1


if __name__ == "__main__":
    sys.exit(main())
