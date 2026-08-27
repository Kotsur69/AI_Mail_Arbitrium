"""The report a stakeholder opens, written the way Polish Excel expects it.

CSV over XLSX was a stakeholder answer, not a shortcut: the file is meant to be
edited by hand, which is why the per-supplier sheet carries an empty `decyzja`
column. Two files rather than two sections in one, because a CSV with a blank
line and a second header stops being a spreadsheet.

Polish Excel opens a CSV as UTF-8 only when it starts with a byte order mark,
and splits on semicolons rather than commas because the comma is the decimal
separator here. Getting either wrong fails silently -- mojibake, or every row in
one column -- so both are constants tested against the bytes on disk.

PRIVACY: unlike the console output, these files carry real subjects, senders and
quotes. That is the point of them; a redacted report is not a report. The rule
the console follows is about stdout, which is what reaches an assistant's
context. A file on disk does not, until someone pastes it into one.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from arbitrium.verdict import Status

CSV_ENCODING = "utf-8-sig"
CSV_DELIMITER = ";"
CSV_LINE_TERMINATOR = "\r\n"

# Shown when a sender has no SMTP domain to group by -- an internal Exchange
# X.500 name, mostly. Named rather than blank so the row cannot be mistaken for
# a parsing accident.
UNKNOWN_SUPPLIER = "(brak domeny)"

DATE_FORMAT = "%Y-%m-%d %H:%M"

# Excel treats a cell opening with any of these as a formula, so a quoted body
# becomes executable content. Prefixing with an apostrophe forces text.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

MESSAGE_HEADERS = (
    "lp", "skrzynka", "dostawca", "nadawca", "data", "temat", "status",
    "do_weryfikacji", "powody", "cytat", "uzasadnienie", "zalaczniki",
    "status_zalacznika",
)

SUPPLIER_HEADERS = (
    "dostawca", "wiadomosci", "zgoda", "brak_zgody", "inne", "nie_dotyczy",
    "do_weryfikacji", "ostatnia_wiadomosc", "decyzja",
)

COUNTED_STATUSES: tuple[Status, ...] = ("zgoda", "brak_zgody", "inne", "nie_dotyczy")


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """One classified message, flattened to what a report needs.

    Deliberately not RawMessage plus MessageVerdict: the report must survive a
    message being dropped from memory, and must not tempt anyone into writing a
    whole body to disk.
    """

    mailbox: str
    supplier: str | None
    sender: str
    subject: str
    received_at: datetime | None
    status: Status
    review_reasons: tuple[str, ...] = field(default=())
    evidence: str = ""
    rationale: str = ""
    attachments_total: int = 0
    attachments_read: int = 0
    attachment_status: Status | None = None

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)

    @property
    def group(self) -> str:
        """The key the blueprint asked to group by, with absence made visible."""
        return self.supplier or UNKNOWN_SUPPLIER


@dataclass(frozen=True, slots=True)
class SupplierRollup:
    """Everything one supplier sent, counted. No verdict is derived from it.

    A supplier-level status would be a business rule nobody has agreed to yet --
    whether a later `brak_zgody` overrides an earlier `zgoda`, whether one
    consenting mailbox speaks for a domain. The counts and the empty `decyzja`
    column let a person answer that per supplier until someone answers it once.
    """

    supplier: str
    messages: int
    statuses: Counter[str]
    queued: int
    last_message: datetime | None


def neutralise(value: str) -> str:
    """Stop Excel from running a cell that happens to start like a formula."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def stamp(moment: datetime | None) -> str:
    return moment.strftime(DATE_FORMAT) if moment else ""


def attachment_note(record: MessageRecord) -> str:
    """How many files were readable, or nothing at all when there were none."""
    if not record.attachments_total:
        return ""
    return f"{record.attachments_read}/{record.attachments_total}"


def message_row(index: int, record: MessageRecord) -> list[str]:
    return [
        str(index),
        record.mailbox,
        record.group,
        record.sender,
        stamp(record.received_at),
        record.subject,
        record.status,
        "tak" if record.needs_review else "nie",
        ", ".join(record.review_reasons),
        record.evidence,
        record.rationale,
        attachment_note(record),
        record.attachment_status or "",
    ]


def supplier_rollups(records: Iterable[MessageRecord]) -> list[SupplierRollup]:
    """One row per supplier, ordered so the ones needing attention come first."""
    grouped: dict[str, list[MessageRecord]] = {}
    for record in records:
        grouped.setdefault(record.group, []).append(record)

    rollups = [
        SupplierRollup(
            supplier=supplier,
            messages=len(group),
            statuses=Counter(item.status for item in group),
            queued=sum(1 for item in group if item.needs_review),
            last_message=max(
                (item.received_at for item in group if item.received_at), default=None
            ),
        )
        for supplier, group in grouped.items()
    ]
    return sorted(rollups, key=lambda r: (-r.queued, -r.messages, r.supplier))


def supplier_row(rollup: SupplierRollup) -> list[str]:
    return [
        rollup.supplier,
        str(rollup.messages),
        *(str(rollup.statuses[status]) for status in COUNTED_STATUSES),
        str(rollup.queued),
        stamp(rollup.last_message),
        "",  # decyzja -- left for the reviewer to fill in
    ]


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> Path:
    """Write one file in the dialect Polish Excel opens without an import wizard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as handle:
        writer = csv.writer(
            handle,
            delimiter=CSV_DELIMITER,
            lineterminator=CSV_LINE_TERMINATOR,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(headers)
        writer.writerows([neutralise(str(cell)) for cell in row] for row in rows)
    return path


def write_messages_csv(path: Path, records: Iterable[MessageRecord]) -> Path:
    """Every message, in the order it was classified."""
    rows = (message_row(i, record) for i, record in enumerate(records, start=1))
    return write_csv(path, MESSAGE_HEADERS, rows)


def write_suppliers_csv(path: Path, records: Iterable[MessageRecord]) -> Path:
    """The per-supplier rollup, which is the sheet anyone actually reads."""
    rows = (supplier_row(rollup) for rollup in supplier_rollups(records))
    return write_csv(path, SUPPLIER_HEADERS, rows)


def suppliers_path(path: Path) -> Path:
    """The companion filename for the rollup, next to the file that was asked for."""
    return path.with_name(f"{path.stem}-dostawcy{path.suffix or '.csv'}")
