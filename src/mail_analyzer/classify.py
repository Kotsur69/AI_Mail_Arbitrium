"""Send one message to the local model and get back one verdict.

The model is asked to do exactly one thing: judge a single message. Counts,
rollups and precedence are Python's job, not the model's.

Constrained decoding is not optional here -- JSON Schema is what makes the
output a contract rather than a suggestion.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from mail_analyzer.verdict import MessageVerdict

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "qwen/qwen3-30b-a3b-2507"

# Rule 4 asks for calibrated confidence. Phase 0 measured it coming back at 0.95
# regardless of difficulty, so nothing downstream reads the field -- review.py
# decides on grounded evidence instead. The instruction stays only because
# removing it changed nothing and re-testing it costs a run.
SYSTEM_PROMPT = """Jestes analitykiem odpowiedzi od dostawcow. Otrzymujesz tresc jednej wiadomosci e-mail.

Twoje zadanie: okresl stanowisko dostawcy wobec prosby, ktora do niego wyslano.

Statusy:
- "zgoda" - dostawca jednoznacznie akceptuje / potwierdza / wyraza zgode
- "brak_zgody" - dostawca jednoznacznie odmawia / nie akceptuje
- "inne" - dostawca ODPOWIADA na prosbe, ale niejednoznacznie: zgoda warunkowa,
  odpowiedz wymijajaca, prosba o doprecyzowanie, zgoda czesciowa
- "nie_dotyczy" - wiadomosc NIE JEST odpowiedzia na te prosbe: newsletter,
  autoresponder, powiadomienie systemowe, korespondencja w innej sprawie

ZASADY:
1. Pole "evidence" musi byc DOSLOWNYM fragmentem wiadomosci, skopiowanym znak w znak.
   Nie parafrazuj. Nie tlumacz. Jesli nie ma takiego fragmentu, zwroc pusty string.
2. Zgoda warunkowa ("zgodzimy sie, jesli...") to "inne", nie "zgoda".
3. Uprzejmosc nie jest zgoda. "Dziekujemy za wiadomosc" nie oznacza akceptacji.
5. Rozroznij "inne" od "nie_dotyczy". "inne" oznacza, ze dostawca odniosl sie do
   prosby, ale niejednoznacznie. "nie_dotyczy" oznacza, ze wiadomosc w ogole nie
   dotyczy tej prosby. To rozroznienie decyduje, co trafi do recznej weryfikacji.
4. "confidence" ma odzwierciedlac Twoja faktyczna pewnosc, nie byc zawsze wysokie."""

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "message_verdict",
        "strict": True,
        "schema": MessageVerdict.model_json_schema(),
    },
}


class Classifier:
    """A thin, deterministic wrapper over the local OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        max_body_chars: int = 12000,
    ) -> None:
        self.model = model
        self.max_body_chars = max_body_chars
        self._client = OpenAI(base_url=base_url, api_key="lm-studio")

    def classify(self, text: str) -> MessageVerdict:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[: self.max_body_chars]},
            ],
            response_format=RESPONSE_FORMAT,
            temperature=0.0,
            seed=7,
            max_tokens=400,
        )
        return MessageVerdict.model_validate_json(response.choices[0].message.content or "")
