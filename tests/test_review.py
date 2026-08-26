"""Rules that decide which verdicts a human has to look at.

Phase 0 measured three candidate confidence signals and all three failed:
self-reported confidence is flat, sample agreement is unanimous even on
ambiguous mail, and LM Studio does not expose logprobs. So the review queue is
filled by deterministic rules over the verdict, not by a probability.
"""

from mail_analyzer.review import ReviewReason, needs_review, review_reasons
from mail_analyzer.verdict import MessageVerdict

BODY = "Dzien dobry,\n\nPotwierdzamy i akceptujemy proponowane warunki wspolpracy.\n\nPozdrawiam"


def verdict(**overrides: object) -> MessageVerdict:
    base = {
        "status": "zgoda",
        "confidence": 0.95,
        "evidence": "Potwierdzamy i akceptujemy proponowane warunki",
        "rationale": "Dostawca jednoznacznie akceptuje.",
    }
    return MessageVerdict.model_validate({**base, **overrides})


def test_clean_decisive_verdict_is_auto_accepted() -> None:
    # Arrange
    v = verdict()

    # Act
    reasons = review_reasons(v, BODY)

    # Assert
    assert reasons == []
    assert needs_review(v, BODY) is False


def test_invented_evidence_forces_review() -> None:
    # Arrange -- a quote that reads plausibly but is not in the message
    v = verdict(evidence="Wyrazamy pelna zgode na wszystkie punkty")

    # Act
    reasons = review_reasons(v, BODY)

    # Assert
    assert ReviewReason.EVIDENCE_NOT_GROUNDED in reasons


def test_accent_and_whitespace_drift_still_counts_as_grounded() -> None:
    # Arrange -- same span, restored diacritics and collapsed newlines
    v = verdict(evidence="Potwierdzamy   i akceptujemy  proponowane warunki")

    # Act / Assert
    assert review_reasons(v, BODY) == []


def test_empty_evidence_on_decisive_verdict_forces_review() -> None:
    assert ReviewReason.NO_EVIDENCE in review_reasons(verdict(evidence=""), BODY)


def test_one_word_quote_is_too_thin_to_carry_a_decisive_verdict() -> None:
    # Arrange -- grounded, but far too short to justify a supplier's status
    v = verdict(status="brak_zgody", evidence="Dzien")

    # Act / Assert
    assert ReviewReason.EVIDENCE_TOO_SHORT in review_reasons(v, BODY)


def test_inne_always_goes_to_review() -> None:
    # `inne` is the residual bucket by construction -- a person decides.
    v = verdict(status="inne", evidence="Potwierdzamy i akceptujemy proponowane warunki")

    assert review_reasons(v, BODY) == [ReviewReason.AMBIGUOUS_STATUS]


def test_thin_evidence_is_not_held_against_inne() -> None:
    # `inne` is already queued; length and emptiness rules would only add noise.
    reasons = review_reasons(verdict(status="inne", evidence=""), BODY)

    assert reasons == [ReviewReason.AMBIGUOUS_STATUS]


def test_signed_attachment_contradicting_the_body_forces_review() -> None:
    # A signed document means consent, so a refusing body is a real conflict.
    v = verdict(status="brak_zgody", evidence="Potwierdzamy i akceptujemy proponowane warunki")

    reasons = review_reasons(v, BODY, attachment_status="zgoda")

    assert ReviewReason.BODY_ATTACHMENT_CONFLICT in reasons


def test_attachment_agreeing_with_the_body_adds_no_reason() -> None:
    assert review_reasons(verdict(), BODY, attachment_status="zgoda") == []


def test_high_self_reported_confidence_never_suppresses_a_reason() -> None:
    # The measured defect: confidence is ~0.95 on everything, so it must not vote.
    v = verdict(confidence=1.0, evidence="Cytat ktorego nie ma w wiadomosci")

    assert needs_review(v, BODY) is True


def test_off_topic_mail_is_queued_under_its_own_reason() -> None:
    # Bulk-dismissable, so it must not be confused with an ambiguous reply.
    v = verdict(status="nie_dotyczy", evidence="")

    assert review_reasons(v, BODY) == [ReviewReason.OFF_TOPIC]


def test_ambiguous_reply_and_off_topic_never_share_a_bucket() -> None:
    ambiguous = review_reasons(verdict(status="inne", evidence=""), BODY)
    off_topic = review_reasons(verdict(status="nie_dotyczy", evidence=""), BODY)

    assert ambiguous != off_topic
    assert ReviewReason.AMBIGUOUS_STATUS in ambiguous
    assert ReviewReason.OFF_TOPIC in off_topic
