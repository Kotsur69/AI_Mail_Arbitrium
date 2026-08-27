"""Verdicts kept on disk, so an hours-long backfill can be resumed.

The mailbox has to be analysed back to late July at 6-12 s per message, which is
a run measured in hours. Without this, a crash, a closed laptop or an LM Studio
hiccup lost all of it, and a second opinion on one supplier meant classifying
everything again.

What is stored is the verdict and the few fields the report needs -- never the
message body. The blueprint prefers in-memory processing, and this stays close
to that: the store holds what was concluded, not what was read.

The key is `dedupe_key` from the ingestion layer, the RFC 5322 Message-ID where
there is one. It already survives Outlook moving an item between folders, so
archiving a message does not make it look unclassified.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable, Sequence

from arbitrium.export import MessageRecord

SCHEMA_VERSION = 1

REASON_SEPARATOR = ","

SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    dedupe_key        TEXT PRIMARY KEY,
    mailbox           TEXT NOT NULL,
    supplier          TEXT,
    sender            TEXT NOT NULL,
    subject           TEXT NOT NULL,
    received_at       TEXT,
    received_utc      REAL,
    status            TEXT NOT NULL,
    review_reasons    TEXT NOT NULL,
    evidence          TEXT NOT NULL,
    rationale         TEXT NOT NULL,
    attachments_total INTEGER NOT NULL,
    attachments_read  INTEGER NOT NULL,
    attachment_status TEXT,
    model             TEXT NOT NULL,
    classified_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS verdicts_mailbox ON verdicts(mailbox);
"""

COLUMNS = (
    "dedupe_key", "mailbox", "supplier", "sender", "subject", "received_at",
    "received_utc", "status", "review_reasons", "evidence", "rationale",
    "attachments_total", "attachments_read", "attachment_status", "model",
    "classified_at",
)

# Undated mail sorts last rather than first: it is the odd case, and a reviewer
# reading top to bottom should meet the timeline before the exceptions.
ORDER_BY = "ORDER BY received_utc IS NULL, received_utc, rowid"


class SchemaMismatch(RuntimeError):
    """The file on disk was written by a different version of this schema."""


def sort_key(moment: datetime | None) -> float | None:
    """A number that orders correctly across mixed UTC offsets.

    The ISO string is kept for fidelity, but sorting on it would put 12:00+02:00
    after 12:00+01:00, which is backwards. A backfill spanning a DST change hits
    exactly that.
    """
    return None if moment is None else moment.timestamp()


def reasons_to_text(reasons: Sequence[str]) -> str:
    return REASON_SEPARATOR.join(reasons)


def text_to_reasons(text: str) -> tuple[str, ...]:
    return tuple(part for part in text.split(REASON_SEPARATOR) if part)


def to_record(row: sqlite3.Row) -> MessageRecord:
    """Rebuild the report record, keeping absent fields absent."""
    received = row["received_at"]
    return MessageRecord(
        mailbox=row["mailbox"],
        supplier=row["supplier"],
        sender=row["sender"],
        subject=row["subject"],
        received_at=datetime.fromisoformat(received) if received else None,
        status=row["status"],
        review_reasons=text_to_reasons(row["review_reasons"]),
        evidence=row["evidence"],
        rationale=row["rationale"],
        attachments_total=row["attachments_total"],
        attachments_read=row["attachments_read"],
        attachment_status=row["attachment_status"],
    )


def to_row(
    key: str, record: MessageRecord, model: str, classified_at: datetime
) -> tuple[Any, ...]:
    return (
        key,
        record.mailbox,
        record.supplier,
        record.sender,
        record.subject,
        record.received_at.isoformat() if record.received_at else None,
        sort_key(record.received_at),
        record.status,
        reasons_to_text(record.review_reasons),
        record.evidence,
        record.rationale,
        record.attachments_total,
        record.attachments_read,
        record.attachment_status,
        model,
        classified_at.isoformat(),
    )


def mailbox_filter(mailboxes: Iterable[str] | None) -> tuple[str, list[str]]:
    """A WHERE fragment restricting to named mailboxes, or nothing at all."""
    names = list(mailboxes) if mailboxes is not None else []
    if not names:
        return "", []
    placeholders = ", ".join("?" for _ in names)
    return f"mailbox IN ({placeholders})", names


class VerdictStore:
    """Every message this pipeline has already judged, keyed so it can skip them."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._prepare()

    def _prepare(self) -> None:
        # WAL survives a crash mid-write, and FULL means a committed verdict is
        # really on the platter. One fsync against 6-12 s of inference is free.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")

        version = self.schema_version
        if version and version != SCHEMA_VERSION:
            raise SchemaMismatch(
                f"database uses schema v{version}, this build writes v{SCHEMA_VERSION}. "
                "Delete the file to start a fresh backfill, or point --db elsewhere."
            )

        self._connection.executescript(SCHEMA)
        self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._connection.commit()

    @property
    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def save(
        self,
        key: str,
        record: MessageRecord,
        model: str,
        classified_at: datetime | None = None,
    ) -> None:
        """Write one verdict and commit it.

        Committing per message rather than per run is the whole point: an
        interrupted backfill should lose the message in flight, not the hours
        before it.
        """
        placeholders = ", ".join("?" for _ in COLUMNS)
        self._connection.execute(
            f"INSERT OR REPLACE INTO verdicts ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            to_row(key, record, model, classified_at or datetime.now()),
        )
        self._connection.commit()

    def classified_keys(
        self, mailboxes: Iterable[str] | None = None, model: str | None = None
    ) -> set[str]:
        """The keys a resumed run may skip.

        Passing `model` narrows it to verdicts that model produced, so moving to
        a bigger model reclassifies rather than silently inheriting the smaller
        one's answers.
        """
        clause, params = mailbox_filter(mailboxes)
        conditions = [c for c in (clause, "model = ?" if model else "") if c]
        if model:
            params = [*params, model]
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._connection.execute(f"SELECT dedupe_key FROM verdicts{where}", params)
        return {row["dedupe_key"] for row in rows}

    def records(self, mailboxes: Iterable[str] | None = None) -> list[MessageRecord]:
        """Everything judged so far, oldest first, ready to be written as a report."""
        clause, params = mailbox_filter(mailboxes)
        where = f" WHERE {clause}" if clause else ""
        rows = self._connection.execute(f"SELECT * FROM verdicts{where} {ORDER_BY}", params)
        return [to_record(row) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> VerdictStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
