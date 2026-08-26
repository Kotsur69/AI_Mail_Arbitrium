"""Reduce a raw mail body to the text the sender actually wrote.

Measured, so the rationale stays honest: on three replies carrying ~630
characters of quoted history deliberately stuffed with consent wording
("Akceptujemy", "zostaly zaakceptowane"), stripping changed **no** verdicts.
qwen3-30b-a3b reads the reply, not the quote, at that scale.

So this is not the correctness fix it was assumed to be. It is kept for context
economy -- real threads run far longer than the tested 630 characters, and every
quoted line is prompt the model pays for -- and as cheap insurance at thread
lengths nobody has measured yet. Treat any stronger claim as unproven.

Everything here is pure text handling: no I/O, no model, no Outlook.
"""

from __future__ import annotations

import re

# Where quoted history begins. First match wins, so order does not matter --
# only that every pattern is anchored at the start of its own line.
HISTORY_MARKERS: tuple[re.Pattern[str], ...] = (
    # Outlook's horizontal rule above a forwarded/replied header block.
    re.compile(r"^_{10,}\s*$", re.M),
    # "-----Original Message-----" / "-----Oryginalna wiadomosc-----"
    re.compile(r"^\s*-{3,}\s*(original message|oryginalna wiadomo|forwarded message|wiadomo)\S*.*$", re.M | re.I),
    # "W dniu 4 sierpnia 2026 napisano:" / "W dniu ... <x@y> napisal(a):"
    re.compile(r"^\s*W dniu .{0,120}?napisa\w*\s*:\s*$", re.M | re.I),
    # "On Tue, 4 Aug 2026 at 10:00, Anna wrote:"
    re.compile(r"^\s*On .{0,120}?\bwrote\s*:\s*$", re.M | re.I),
    # A bare header block: "Od:" / "From:" starting a line, followed by more headers.
    re.compile(r"^\s*(Od|From)\s*:\s*.+$", re.M),
    # The first line of an unattributed quote block.
    re.compile(r"^\s*>", re.M),
)

# Corporate confidentiality footers. Anchored at a line start; everything after
# the match is dropped, because these always sit at the very bottom.
DISCLAIMER_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*Ta wiadomo\S*\s+i\s+wszelkie\b", re.M | re.I),
    re.compile(r"^\s*Niniejsza wiadomo\S*\b", re.M | re.I),
    re.compile(r"^\s*This (e-?mail|message)\b.{0,80}\bconfidential\b", re.M | re.I),
    re.compile(r"^\s*The information contained in this\b", re.M | re.I),
)


def clean_whitespace(text: str) -> str:
    """Normalise line endings and exotic spaces, and collapse blank-line runs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _first_marker(text: str, markers: tuple[re.Pattern[str], ...]) -> int | None:
    """Offset of the earliest marker match, or None if none matched."""
    hits = [m.start() for m in (p.search(text) for p in markers) if m is not None]
    return min(hits) if hits else None


def strip_disclaimer(text: str) -> str:
    """Drop a trailing corporate confidentiality footer."""
    cut = _first_marker(text, DISCLAIMER_MARKERS)
    return text if cut is None else text[:cut].rstrip()


def reply_text(body: str) -> str:
    """The sender's own words, with quoted history and disclaimers removed.

    Never returns empty: a body that is nothing but quoted history is still a
    message someone has to classify, so it is handed back whole.
    """
    text = clean_whitespace(body)
    text = strip_disclaimer(text)

    cut = _first_marker(text, HISTORY_MARKERS)
    if cut is None:
        return text

    head = text[:cut].strip()
    return head if head else text
