"""Phase 0 smoke test: verify LM Studio serves constrained JSON for Polish supplier replies.

Checks, in order:
  1. LM Studio server reachable and model loadable
  2. JSON-Schema constrained decoding returns schema-valid output
  3. Polish business prose is classified correctly on hand-written cases
  4. The grounding check catches evidence quotes the model invented
  5. Throughput is good enough for an overnight backfill

Run:  .venv/Scripts/python.exe scripts/phase0_smoke.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI

from arbitrium.verdict import MessageVerdict, is_grounded

BASE_URL = "http://localhost:1234/v1"
MODEL = "qwen/qwen3-30b-a3b-2507"



SYSTEM_PROMPT = """Jestes analitykiem odpowiedzi od dostawcow. Otrzymujesz tresc jednej wiadomosci e-mail.

Twoje zadanie: okresl stanowisko dostawcy wobec prosby, ktora do niego wyslano.

Statusy:
- "zgoda" - dostawca jednoznacznie akceptuje / potwierdza / wyraza zgode
- "brak_zgody" - dostawca jednoznacznie odmawia / nie akceptuje
- "inne" - odpowiedz warunkowa, wymijajaca, prosba o dodatkowe informacje,
  autoresponder, nieobecnosc, lub tresc niezwiazana z prosba

ZASADY:
1. Pole "evidence" musi byc DOSLOWNYM fragmentem wiadomosci, skopiowanym znak w znak.
   Nie parafrazuj. Nie tlumacz. Jesli nie ma takiego fragmentu, zwroc pusty string.
2. Zgoda warunkowa ("zgodzimy sie, jesli...") to "inne", nie "zgoda".
3. Uprzejmosc nie jest zgoda. "Dziekujemy za wiadomosc" nie oznacza akceptacji.
4. "confidence" ma odzwierciedlac Twoja faktyczna pewnosc, nie byc zawsze wysokie."""


CASES: list[tuple[str, str, str]] = [
    (
        "jednoznaczna zgoda",
        "zgoda",
        """Dzien dobry,

W nawiazaniu do Panstwa pisma z dnia 4 sierpnia potwierdzam, ze wyrazamy zgode
na proponowane warunki wspolpracy w brzmieniu przeslanym w zalaczniku.

Z powazaniem,
Anna Kowalska
Dzial Zakupow""",
    ),
    (
        "jednoznaczna odmowa",
        "brak_zgody",
        """Szanowni Panstwo,

Po analizie przedstawionej propozycji informujemy, ze nie wyrazamy zgody na
zaproponowane zmiany. Obecne warunki umowy pozostaja dla nas jedyna akceptowalna forma wspolpracy.

Pozdrawiam,
Marek Nowak""",
    ),
    (
        "zgoda warunkowa - pulapka",
        "inne",
        """Dzien dobry,

Jestesmy wstepnie zainteresowani i mozemy wyrazic zgode, pod warunkiem wydluzenia
terminu platnosci do 60 dni oraz potwierdzenia wolumenu na caly rok.
Prosze o informacje, czy jest to mozliwe.

Z powazaniem,
Katarzyna Wisniewska""",
    ),
    (
        "autoresponder - nie odpowiedz",
        "inne",
        """Uprzejmie informuje, ze przebywam na urlopie do dnia 15 wrzesnia.
W sprawach pilnych prosze o kontakt z sekretariatem.

Wiadomosc wygenerowana automatycznie.""",
    ),
    (
        "zgoda pod cytowana historia",
        "zgoda",
        """Potwierdzam, akceptujemy.

W dniu 4 sierpnia napisano:
> Szanowni Panstwo, zwracamy sie z prosba o wyrazenie zgody na aktualizacje
> warunkow wspolpracy. Prosimy o odpowiedz do 20 sierpnia.
> Czy wyrazaja Panstwo zgode na powyzsze?""",
    ),
]


def main() -> int:
    client = OpenAI(base_url=BASE_URL, api_key="lm-studio")

    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "message_verdict",
            "strict": True,
            "schema": MessageVerdict.model_json_schema(),
        },
    }

    print(f"model      : {MODEL}")
    print(f"endpoint   : {BASE_URL}")
    print("-" * 78)

    passed = 0
    grounded_ok = 0
    total_tokens = 0
    total_seconds = 0.0

    for name, expected, body in CASES:
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
            response_format=schema,
            temperature=0.0,
            seed=7,
            max_tokens=400,
        )
        elapsed = time.perf_counter() - started

        raw = response.choices[0].message.content or ""
        verdict = MessageVerdict.model_validate_json(raw)

        out_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens += out_tokens
        total_seconds += elapsed

        status_ok = verdict.status == expected
        ground_ok = is_grounded(verdict.evidence, body)
        passed += status_ok
        grounded_ok += ground_ok

        print(f"{'PASS' if status_ok else 'FAIL'}  {name}")
        print(f"      expected={expected}  got={verdict.status}  conf={verdict.confidence:.2f}")
        print(f"      grounded={'yes' if ground_ok else 'NO  <-- evidence not in source'}")
        print(f"      evidence: {verdict.evidence[:96]!r}")
        print(f"      {out_tokens} tok in {elapsed:.1f}s = {out_tokens / elapsed:.1f} tok/s")
        print()

    print("-" * 78)
    print(f"classification : {passed}/{len(CASES)}")
    print(f"grounding      : {grounded_ok}/{len(CASES)}")
    print(f"throughput     : {total_tokens / total_seconds:.1f} tok/s avg")
    print(f"per message    : {total_seconds / len(CASES):.1f}s avg")
    print(f"300-msg backfill estimate: {total_seconds / len(CASES) * 300 / 60:.0f} min")

    return 0 if passed == len(CASES) and grounded_ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
