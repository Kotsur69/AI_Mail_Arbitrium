"""Decides which verdicts a human has to check.

Phase 0 tested three ways to get a confidence number out of the model and all
three failed on this stack:

  * self-reported `confidence` came back ~0.95 on every message, including a
    deliberately ambiguous one;
  * majority vote over 3 samples at temperature 0.7 was unanimous on all ten
    test messages, clear and hard alike, at three times the cost;
  * LM Studio's OpenAI-compatible endpoint returns `logprobs: null`.

So nothing here is probabilistic. The queue is filled by rules over the verdict
itself, which are cheap, auditable, and explain themselves to the reviewer.
"""

from __future__ import annotations

from enum import Enum

from arbitrium.verdict import MessageVerdict, Status, is_grounded

# A decisive verdict resting on a shorter quote than this is not justified.
MIN_EVIDENCE_CHARS = 12

DECISIVE: frozenset[Status] = frozenset({"zgoda", "brak_zgody"})


class ReviewReason(str, Enum):
    """Why a message was queued. Shown to the reviewer as-is."""

    AMBIGUOUS_STATUS = "ambiguous_status"
    OFF_TOPIC = "off_topic"
    NO_EVIDENCE = "no_evidence"
    EVIDENCE_NOT_GROUNDED = "evidence_not_grounded"
    EVIDENCE_TOO_SHORT = "evidence_too_short"
    BODY_ATTACHMENT_CONFLICT = "body_attachment_conflict"
    VISION_TRANSCRIPT = "vision_transcript"


def review_reasons(
    verdict: MessageVerdict,
    source_text: str,
    attachment_status: Status | None = None,
    from_vision: bool = False,
) -> list[ReviewReason]:
    """Every reason this verdict needs a human, in the order a reviewer should read them."""
    reasons: list[ReviewReason] = []

    # Neither non-decisive status is trusted, but they are queued separately:
    # off-topic mail is bulk-dismissable, an ambiguous reply must be read.
    # The evidence rules below would only add noise on top of either.
    if verdict.status == "nie_dotyczy":
        reasons.append(ReviewReason.OFF_TOPIC)
    elif verdict.status not in DECISIVE:
        reasons.append(ReviewReason.AMBIGUOUS_STATUS)
    elif not verdict.evidence.strip():
        reasons.append(ReviewReason.NO_EVIDENCE)
    elif not is_grounded(verdict.evidence, source_text):
        reasons.append(ReviewReason.EVIDENCE_NOT_GROUNDED)
    elif len(verdict.evidence.strip()) < MIN_EVIDENCE_CHARS:
        reasons.append(ReviewReason.EVIDENCE_TOO_SHORT)

    # Evidence read off a scan is the one case the grounding rule above cannot
    # police. The quote is checked against the transcription, and the
    # transcription is what the vision model believed it saw -- so a misread
    # word matches itself perfectly. Nothing here can catch that; a person
    # glancing at the page can, in seconds, which is the whole trade.
    if from_vision:
        reasons.append(ReviewReason.VISION_TRANSCRIPT)

    # A signed attachment carries consent, so a body that says otherwise is a
    # conflict no rollup rule should silently resolve.
    if attachment_status is not None and attachment_status != verdict.status:
        reasons.append(ReviewReason.BODY_ATTACHMENT_CONFLICT)

    return reasons


def supporting_status(verdict: MessageVerdict | None, source_text: str) -> Status | None:
    """The status an attachment contributes to a message, or None for nothing.

    Only a decisive, grounded verdict counts, and both exclusions are load-bearing.
    An attachment the model called ambiguous is usually not a position at all --
    a price list, a footer, a quoted policy -- and letting those disagree with
    the body would queue nearly every message with a file on it. A quote that is
    not verbatim in the attachment is not evidence the attachment said anything.
    """
    if verdict is None or verdict.status not in DECISIVE:
        return None
    if not is_grounded(verdict.evidence, source_text):
        return None
    return verdict.status


def needs_review(
    verdict: MessageVerdict,
    source_text: str,
    attachment_status: Status | None = None,
    from_vision: bool = False,
) -> bool:
    return bool(review_reasons(verdict, source_text, attachment_status, from_vision))
