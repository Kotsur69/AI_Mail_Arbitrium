"""The one contract the LLM is allowed to produce, plus the grounding check.

The model classifies a single message and nothing else. Every count, rollup and
status precedence is computed in Python from these verdicts.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["zgoda", "brak_zgody", "inne", "nie_dotyczy"]
"""zgoda / brak_zgody are decisive. `inne` is an on-topic reply that is not
decisive -- conditional, evasive, a counter-question. `nie_dotyczy` is mail that
is not a reply to the request at all. Splitting the last two matters: measured
against a real inbox, collapsing them put 100% of messages in the review queue."""


class MessageVerdict(BaseModel):
    """One supplier message, classified."""

    status: Status
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(description="Doslowny cytat z wiadomosci uzasadniajacy status")
    rationale: str = Field(description="Jedno zdanie po polsku")


def normalize(text: str) -> str:
    """Collapse whitespace and strip accents so quote matching survives cosmetic drift."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip()


def is_grounded(evidence: str, source: str) -> bool:
    """True when the evidence quote really appears in the source message."""
    if not evidence.strip():
        return False
    return normalize(evidence) in normalize(source)
