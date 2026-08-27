"""Verdicts kept on disk, so an hours-long backfill can be resumed.

The whole mailbox back to late July has to be classified at 6-12 s per message.
Before this, a crash, a closed laptop or an LM Studio hiccup lost the lot. The
store is keyed on dedupe_key, which already survives Outlook moving an item
between folders, and it holds verdicts -- never message bodies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from arbitrium.export import MessageRecord
from arbitrium.store import SCHEMA_VERSION, VerdictStore

MODEL = "qwen/qwen3-30b-a3b-2507"
CLASSIFIED_AT = datetime(2026, 8, 27, 10, 0)


def record(**overrides: object) -> MessageRecord:
    base = {
        "mailbox": "dostawcy",
        "supplier": "huta.pl",
        "sender": "biuro@huta.pl",
        "subject": "Re: zgoda na przetwarzanie",
        "received_at": datetime(2026, 8, 20, 9, 14, tzinfo=timezone.utc),
        "status": "zgoda",
        "review_reasons": (),
        "evidence": "Potwierdzamy i akceptujemy",
        "rationale": "Dostawca jednoznacznie akceptuje.",
        "attachments_total": 2,
        "attachments_read": 1,
        "attachment_status": "zgoda",
    }
    return MessageRecord(**{**base, **overrides})  # type: ignore[arg-type]


def test_a_saved_verdict_comes_back_unchanged(tmp_path: Path) -> None:
    # Arrange
    original = record()

    # Act
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<abc@huta.pl>", original, model=MODEL, classified_at=CLASSIFIED_AT)
        [restored] = store.records()

    # Assert
    assert restored == original


def test_what_outlook_could_not_answer_stays_absent(tmp_path: Path) -> None:
    # Arrange -- None must not come back as an empty string
    original = record(received_at=None, supplier=None, attachment_status=None)

    # Act
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<no-date@huta.pl>", original, model=MODEL)
        [restored] = store.records()

    # Assert
    assert restored.received_at is None
    assert restored.supplier is None
    assert restored.attachment_status is None


def test_review_reasons_round_trip(tmp_path: Path) -> None:
    # Arrange
    queued = record(status="inne", review_reasons=("ambiguous_status", "no_evidence"))

    # Act
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<queued@huta.pl>", queued, model=MODEL)
        store.save("<clean@huta.pl>", record(), model=MODEL)
        by_key = {r.subject: r for r in store.records()}
        restored = [r for r in store.records() if r.status == "inne"][0]

    # Assert
    assert restored.review_reasons == ("ambiguous_status", "no_evidence")
    assert by_key["Re: zgoda na przetwarzanie"].review_reasons == ()


def test_reclassifying_a_message_replaces_it_rather_than_duplicating(tmp_path: Path) -> None:
    # Arrange -- the same message seen twice is one row, not two
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<abc@huta.pl>", record(status="inne"), model=MODEL)

        # Act
        store.save("<abc@huta.pl>", record(status="zgoda"), model=MODEL)
        rows = store.records()

    # Assert
    assert len(rows) == 1
    assert rows[0].status == "zgoda"


def test_classified_keys_is_what_a_resumed_run_skips(tmp_path: Path) -> None:
    # Arrange
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<abc@huta.pl>", record(), model=MODEL)

        # Act
        done = store.classified_keys()

    # Assert
    assert done == {"<abc@huta.pl>"}


def test_a_different_model_has_not_classified_anything_yet(tmp_path: Path) -> None:
    # Arrange -- a verdict from a smaller model is not this model's verdict
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<abc@huta.pl>", record(), model="qwen/qwen3-8b")

        # Act
        done = store.classified_keys(model=MODEL)

    # Assert
    assert done == set()


def test_verdicts_survive_closing_and_reopening_the_file(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "arbitrium.db"
    with VerdictStore(path) as store:
        store.save("<abc@huta.pl>", record(), model=MODEL)

    # Act
    with VerdictStore(path) as reopened:
        rows = reopened.records()

    # Assert
    assert [r.subject for r in rows] == ["Re: zgoda na przetwarzanie"]


def test_records_can_be_narrowed_to_the_mailboxes_of_this_run(tmp_path: Path) -> None:
    # Arrange
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<a@huta.pl>", record(mailbox="dostawcy"), model=MODEL)
        store.save("<b@huta.pl>", record(mailbox="archiwum"), model=MODEL)

        # Act
        rows = store.records(mailboxes=["dostawcy"])

    # Assert
    assert [r.mailbox for r in rows] == ["dostawcy"]


def test_records_come_back_oldest_first_with_undated_mail_last(tmp_path: Path) -> None:
    # Arrange -- a stable order, so a regenerated report does not reshuffle
    with VerdictStore(tmp_path / "arbitrium.db") as store:
        store.save("<c@huta.pl>", record(received_at=None, subject="bez daty"), model=MODEL)
        store.save("<b@huta.pl>", record(
            received_at=datetime(2026, 8, 22, 11, 2, tzinfo=timezone.utc), subject="druga"
        ), model=MODEL)
        store.save("<a@huta.pl>", record(
            received_at=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc), subject="pierwsza"
        ), model=MODEL)

        # Act
        rows = store.records()

    # Assert
    assert [r.subject for r in rows] == ["pierwsza", "druga", "bez daty"]


def test_a_fresh_database_records_its_schema_version(tmp_path: Path) -> None:
    # Arrange / Act
    path = tmp_path / "arbitrium.db"
    with VerdictStore(path) as store:
        version = store.schema_version

    # Assert
    assert version == SCHEMA_VERSION


def test_the_store_creates_the_directory_it_was_pointed_at(tmp_path: Path) -> None:
    # Arrange -- data/ is gitignored and will not exist on a fresh clone
    path = tmp_path / "data" / "nested" / "arbitrium.db"

    # Act
    with VerdictStore(path) as store:
        store.save("<abc@huta.pl>", record(), model=MODEL)

    # Assert
    assert path.exists()


# --- the runner resuming from the store -------------------------------------
#
# run_mailbox builds its own Outlook source, so these swap it for a fake. The
# behaviour under test is the reason the store exists at all.

from arbitrium.config import AttachmentsConfig, MailboxConfig  # noqa: E402
from arbitrium.ingestion.base import RawMessage  # noqa: E402
from arbitrium.verdict import MessageVerdict  # noqa: E402

BODY = "Dzien dobry, potwierdzamy i akceptujemy warunki. Pozdrawiam"


def mail(message_id: str) -> RawMessage:
    return RawMessage(
        message_id=message_id,
        received_at=datetime(2026, 8, 20, 9, 14, tzinfo=timezone.utc),
        sender_address="biuro@huta.pl",
        subject="Re: zgoda",
        body=BODY,
        folder="Skrzynka odbiorcza",
    )


class CountingClassifier:
    """A stand-in that records how often the model would have been called."""

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, text: str) -> MessageVerdict:
        self.calls += 1
        return MessageVerdict(
            status="zgoda",
            confidence=0.9,
            evidence="potwierdzamy i akceptujemy",
            rationale="Dostawca akceptuje.",
        )


def fake_outlook(messages, fail_after: int | None = None):
    """A source that yields the given messages, optionally dying part way."""

    class Source:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self, since: datetime | None = None):
            for index, message in enumerate(messages):
                if fail_after is not None and index == fail_after:
                    raise RuntimeError("LM Studio went away")
                yield message

    return lambda **kwargs: Source(**kwargs)


def classify_run(monkeypatch, store, path, messages, fail_after=None, seen=frozenset()):
    import analyze_mailbox

    monkeypatch.setattr(analyze_mailbox, "OutlookMapiSource", fake_outlook(messages, fail_after))
    classifier = CountingClassifier()
    run = analyze_mailbox.run_mailbox(
        MailboxConfig(name="dostawcy", store="dostawcy@firma.pl"),
        classifier,
        AttachmentsConfig(enabled=False),
        False,
        analyze_mailbox.Backfill(model=MODEL, store=store, seen=seen),
    )
    return run, classifier


def test_a_resumed_run_skips_what_the_store_already_holds(tmp_path, monkeypatch) -> None:
    # Arrange -- one full pass over two messages
    path = tmp_path / "arbitrium.db"
    messages = [mail("<a@huta.pl>"), mail("<b@huta.pl>")]
    with VerdictStore(path) as store:
        first, _ = classify_run(monkeypatch, store, path, messages)
    assert first.processed == 2

    # Act -- the same mailbox, the same store, nothing new in it
    with VerdictStore(path) as store:
        second, classifier = classify_run(
            monkeypatch, store, path, messages, seen=frozenset(store.classified_keys(model=MODEL))
        )

    # Assert -- the model is never asked again
    assert second.processed == 0
    assert second.skipped_known == 2
    assert classifier.calls == 0


def test_a_crash_keeps_every_verdict_reached_before_it(tmp_path, monkeypatch) -> None:
    # Arrange -- three messages, the source dies on the third
    path = tmp_path / "arbitrium.db"
    messages = [mail("<a@huta.pl>"), mail("<b@huta.pl>"), mail("<c@huta.pl>")]

    # Act
    with VerdictStore(path) as store:
        with pytest.raises(RuntimeError):
            classify_run(monkeypatch, store, path, messages, fail_after=2)

    # Assert -- the two finished messages are on disk, and a rerun skips them
    with VerdictStore(path) as store:
        assert store.classified_keys() == {"<a@huta.pl>", "<b@huta.pl>"}
