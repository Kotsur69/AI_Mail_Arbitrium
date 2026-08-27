"""The CSV a stakeholder opens, and the rollup they actually read.

Two things are easy to get wrong here and both are silent: a file Polish Excel
splits into one column because it guessed the delimiter, and a quote that
starts with "=" arriving as a formula. Every test below is one of those, or the
grouping the blueprint asked for.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from arbitrium.export import (
    CSV_DELIMITER,
    UNKNOWN_SUPPLIER,
    MessageRecord,
    supplier_rollups,
    write_messages_csv,
    write_suppliers_csv,
)


def record(**overrides: object) -> MessageRecord:
    base = {
        "mailbox": "dostawcy",
        "supplier": "huta.pl",
        "sender": "biuro@huta.pl",
        "subject": "Re: zgoda na przetwarzanie",
        "received_at": datetime(2026, 8, 20, 9, 14),
        "status": "zgoda",
        "review_reasons": (),
        "evidence": "Potwierdzamy i akceptujemy",
        "rationale": "Dostawca jednoznacznie akceptuje.",
        "attachments_total": 0,
        "attachments_read": 0,
        "attachment_status": None,
    }
    return MessageRecord(**{**base, **overrides})  # type: ignore[arg-type]


def read_back(path: Path) -> list[dict[str, str]]:
    """The file as Excel would see it: BOM stripped, semicolon delimited."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=CSV_DELIMITER))


def test_file_carries_the_three_things_polish_excel_needs(tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / "raport.csv"

    # Act
    write_messages_csv(target, [record()])
    raw = target.read_bytes()

    # Assert -- BOM so Excel reads UTF-8, semicolons, CRLF line endings
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b";" in raw
    assert raw.rstrip().endswith(b"\r\n".rstrip()) or b"\r\n" in raw


def test_semicolon_in_a_subject_does_not_become_a_new_column(tmp_path: Path) -> None:
    # Arrange -- a subject containing the delimiter itself
    target = tmp_path / "raport.csv"

    # Act
    write_messages_csv(target, [record(subject="Zgoda; ale z zastrzezeniem")])
    rows = read_back(target)

    # Assert
    assert rows[0]["temat"] == "Zgoda; ale z zastrzezeniem"


def test_newline_in_a_quote_survives_the_round_trip(tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / "raport.csv"

    # Act
    write_messages_csv(target, [record(evidence="Potwierdzamy\nakceptujemy")])
    rows = read_back(target)

    # Assert
    assert rows[0]["cytat"] == "Potwierdzamy\nakceptujemy"


def test_quote_that_looks_like_a_formula_is_neutralised(tmp_path: Path) -> None:
    # Arrange -- a body can legitimately start with "=", and Excel would run it
    target = tmp_path / "raport.csv"

    # Act
    write_messages_csv(target, [record(evidence="=SUMA(A1:A9) zgoda")])
    rows = read_back(target)

    # Assert -- prefixed, so it lands as text and the reviewer still sees it
    assert rows[0]["cytat"] == "'=SUMA(A1:A9) zgoda"


def test_row_reports_status_and_why_it_was_queued(tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / "raport.csv"
    queued = record(status="inne", review_reasons=("ambiguous_status", "no_evidence"))

    # Act
    write_messages_csv(target, [queued])
    rows = read_back(target)

    # Assert
    assert rows[0]["status"] == "inne"
    assert rows[0]["do_weryfikacji"] == "tak"
    assert rows[0]["powody"] == "ambiguous_status, no_evidence"


def test_clean_verdict_is_not_marked_for_review(tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / "raport.csv"

    # Act
    write_messages_csv(target, [record()])
    rows = read_back(target)

    # Assert
    assert rows[0]["do_weryfikacji"] == "nie"
    assert rows[0]["powody"] == ""


def test_rollup_counts_each_status_per_supplier() -> None:
    # Arrange
    records = [
        record(supplier="huta.pl", status="zgoda"),
        record(supplier="huta.pl", status="brak_zgody"),
        record(supplier="stal.pl", status="zgoda"),
    ]

    # Act
    rollups = {r.supplier: r for r in supplier_rollups(records)}

    # Assert
    assert rollups["huta.pl"].messages == 2
    assert rollups["huta.pl"].statuses["zgoda"] == 1
    assert rollups["huta.pl"].statuses["brak_zgody"] == 1
    assert rollups["stal.pl"].messages == 1


def test_rollup_flags_a_supplier_with_any_queued_message() -> None:
    # Arrange
    records = [
        record(supplier="huta.pl", status="zgoda"),
        record(supplier="huta.pl", status="inne", review_reasons=("ambiguous_status",)),
    ]

    # Act
    rollup = supplier_rollups(records)[0]

    # Assert
    assert rollup.queued == 1


def test_rollup_keeps_the_most_recent_message_date() -> None:
    # Arrange
    records = [
        record(received_at=datetime(2026, 8, 1, 8, 0)),
        record(received_at=datetime(2026, 8, 20, 9, 14)),
        record(received_at=None),
    ]

    # Act
    rollup = supplier_rollups(records)[0]

    # Assert
    assert rollup.last_message == datetime(2026, 8, 20, 9, 14)


def test_sender_without_a_domain_groups_under_a_named_placeholder() -> None:
    # Arrange -- Exchange hands back an X.500 name for internal senders
    records = [record(supplier=None, sender="/o=firma/cn=Recipients/cn=kowalski")]

    # Act
    rollup = supplier_rollups(records)[0]

    # Assert
    assert rollup.supplier == UNKNOWN_SUPPLIER


def test_supplier_file_leaves_the_decision_column_for_the_reviewer(tmp_path: Path) -> None:
    # Arrange -- the CSV was chosen because it can be edited by hand
    target = tmp_path / "raport-dostawcy.csv"

    # Act
    write_suppliers_csv(target, [record()])
    rows = read_back(target)

    # Assert
    assert rows[0]["decyzja"] == ""
    assert rows[0]["dostawca"] == "huta.pl"
    assert rows[0]["wiadomosci"] == "1"
