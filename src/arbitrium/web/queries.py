"""Read-only aggregation over the verdict store, shaped for the dashboard.

The connection is opened with `mode=ro`, so no route -- present or future --
can mutate a backfill that took hours. The dashboard is a reader; the CLI is
the only writer.

Aggregation happens in SQL rather than in Python because the store is expected
to hold a few thousand rows across a whole campaign, and the alternative is
loading all of them to count four statuses.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Sequence

from arbitrium.export import UNKNOWN_SUPPLIER
from arbitrium.store import text_to_reasons
from arbitrium.verdict import Status

COUNTED_STATUSES: tuple[Status, ...] = ("zgoda", "brak_zgody", "inne", "nie_dotyczy")

# The activity strip on the overview. Long enough to cover the campaign so far
# (the mailbox opened in late July), short enough to stay legible as bars.
TIMELINE_DAYS = 45

# A page of messages. An unbounded query over a finished campaign is the wrong
# default even when the table could render it.
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000

# The dashboard opens on what arrived last, so it inverts the store's order.
# Undated mail still sorts last: the `IS NULL` term stays ascending, and only
# the timestamp itself flips -- writing `ORDER_BY + " DESC"` would have
# reversed nothing but the tiebreaker.
NEWEST_FIRST = "ORDER BY received_utc IS NULL, received_utc DESC, rowid DESC"


class DatabaseMissing(RuntimeError):
    """No verdict database yet -- the pipeline has not run, or --db points elsewhere."""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the store read-only, or say plainly that there is nothing to read."""
    if not path.exists():
        raise DatabaseMissing(f"no verdict database at {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _where(mailbox: str | None, extra: Sequence[str] = ()) -> tuple[str, list[Any]]:
    """A WHERE clause for the one filter every query shares, plus any caller's own."""
    clauses = list(extra)
    params: list[Any] = []
    if mailbox:
        clauses.insert(0, "mailbox = ?")
        params.insert(0, mailbox)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params


def _distinct(connection: sqlite3.Connection, column: str) -> list[str]:
    rows = connection.execute(
        f"SELECT DISTINCT {column} AS value FROM verdicts "
        f"WHERE {column} IS NOT NULL ORDER BY value"
    )
    return [row["value"] for row in rows]


def totals(connection: sqlite3.Connection, mailbox: str | None) -> dict[str, int]:
    """Message counts by status, plus the size of the review queue.

    `review_reasons` is empty exactly when nothing queued the message, so the
    queue count is a string test rather than a second table.
    """
    where, params = _where(mailbox)
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS messages,
            SUM(status = 'zgoda') AS zgoda,
            SUM(status = 'brak_zgody') AS brak_zgody,
            SUM(status = 'inne') AS inne,
            SUM(status = 'nie_dotyczy') AS nie_dotyczy,
            SUM(review_reasons != '') AS review,
            SUM(attachments_total > 0) AS with_attachments,
            SUM(attachments_read) AS attachments_read,
            SUM(attachments_total) AS attachments_total
        FROM verdicts{where}
        """,
        params,
    ).fetchone()
    # SUM over zero rows is NULL, and the dashboard should render 0, not null.
    return {key: int(row[key] or 0) for key in row.keys()}


def review_breakdown(connection: sqlite3.Connection, mailbox: str | None) -> dict[str, int]:
    """How many messages each review reason queued.

    Reasons are stored joined into one column, so this counts in Python -- over
    the queued rows only, which is a fraction of the store.
    """
    where, params = _where(mailbox, ["review_reasons != ''"])
    counts: dict[str, int] = {}
    for row in connection.execute(f"SELECT review_reasons FROM verdicts{where}", params):
        for reason in text_to_reasons(row["review_reasons"]):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def timeline(connection: sqlite3.Connection, mailbox: str | None) -> list[dict[str, Any]]:
    """Messages per day over the window ending at the most recent message.

    Silent days are returned as zeroes rather than omitted. Skipping them would
    draw a weekend, a holiday or a stalled backfill as if it were a working day
    with mail on it, which is the one thing an activity strip must not do.
    """
    where, params = _where(mailbox, ["received_at IS NOT NULL"])
    rows = connection.execute(
        f"""
        SELECT substr(received_at, 1, 10) AS day,
               COUNT(*) AS messages,
               SUM(review_reasons != '') AS review
        FROM verdicts{where}
        GROUP BY day ORDER BY day DESC LIMIT ?
        """,
        [*params, TIMELINE_DAYS],
    ).fetchall()
    if not rows:
        return []

    counted = {row["day"]: row for row in rows}
    last = date.fromisoformat(max(counted))
    # The window is a fixed number of calendar days back from the newest
    # message, never further back than the oldest one that was counted.
    first = max(date.fromisoformat(min(counted)), last - timedelta(days=TIMELINE_DAYS - 1))

    days: list[dict[str, Any]] = []
    current = first
    while current <= last:
        key = current.isoformat()
        row = counted.get(key)
        days.append(
            {
                "day": key,
                "messages": row["messages"] if row else 0,
                "review": int(row["review"] or 0) if row else 0,
            }
        )
        current += timedelta(days=1)
    return days


def suppliers(connection: sqlite3.Connection, mailbox: str | None) -> list[dict[str, Any]]:
    """One row per supplier domain, the ones needing attention first.

    Deliberately carries no supplier-level status: which of a domain's replies
    speaks for it is a business rule nobody has agreed yet, so the dashboard
    shows the counts and lets a person decide, exactly as the CSV does.
    """
    where, params = _where(mailbox)
    rows = connection.execute(
        f"""
        SELECT
            COALESCE(supplier, ?) AS supplier,
            COUNT(*) AS messages,
            SUM(status = 'zgoda') AS zgoda,
            SUM(status = 'brak_zgody') AS brak_zgody,
            SUM(status = 'inne') AS inne,
            SUM(status = 'nie_dotyczy') AS nie_dotyczy,
            SUM(review_reasons != '') AS queued,
            MAX(received_at) AS last_message
        FROM verdicts{where}
        GROUP BY supplier
        ORDER BY queued DESC, messages DESC, supplier
        """,
        [UNKNOWN_SUPPLIER, *params],
    )
    return [
        {
            "supplier": row["supplier"],
            "messages": row["messages"],
            "statuses": {status: int(row[status] or 0) for status in COUNTED_STATUSES},
            "queued": int(row["queued"] or 0),
            "lastMessage": row["last_message"],
        }
        for row in rows
    ]


def _message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["dedupe_key"],
        "mailbox": row["mailbox"],
        "supplier": row["supplier"] or UNKNOWN_SUPPLIER,
        "sender": row["sender"],
        "subject": row["subject"],
        "receivedAt": row["received_at"],
        "status": row["status"],
        "reviewReasons": list(text_to_reasons(row["review_reasons"])),
        "evidence": row["evidence"],
        "rationale": row["rationale"],
        "attachmentsTotal": row["attachments_total"],
        "attachmentsRead": row["attachments_read"],
        "attachmentStatus": row["attachment_status"],
        "model": row["model"],
        "classifiedAt": row["classified_at"],
    }


def messages(
    connection: sqlite3.Connection,
    mailbox: str | None = None,
    status: str | None = None,
    supplier: str | None = None,
    review_only: bool = False,
    query: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """A filtered page of classified messages, plus how many matched in total.

    The free-text search covers what a reviewer actually squints at -- sender,
    subject, the quote and the one-line rationale. It is a LIKE rather than
    FTS: at campaign scale the scan is instant, and an FTS table would be a
    second thing to keep in step with the writer.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if supplier:
        # The rollup renders a missing domain under a placeholder; clicking it
        # has to come back here meaning "the ones with no domain at all".
        if supplier == UNKNOWN_SUPPLIER:
            clauses.append("supplier IS NULL")
        else:
            clauses.append("supplier = ?")
            params.append(supplier)
    if review_only:
        clauses.append("review_reasons != ''")
    if query and query.strip():
        clauses.append("(sender LIKE ? OR subject LIKE ? OR evidence LIKE ? OR rationale LIKE ?)")
        params.extend([f"%{query.strip()}%"] * 4)

    where, base = _where(mailbox, clauses)
    params = base + params

    total = connection.execute(f"SELECT COUNT(*) AS n FROM verdicts{where}", params).fetchone()["n"]

    size = max(1, min(limit, MAX_PAGE_SIZE))
    rows = connection.execute(
        f"SELECT * FROM verdicts{where} {NEWEST_FIRST} LIMIT ? OFFSET ?",
        [*params, size, max(0, offset)],
    )
    return {"total": total, "items": [_message(row) for row in rows]}


def overview(connection: sqlite3.Connection, mailbox: str | None) -> dict[str, Any]:
    """Everything the header and the KPI row need, in one round trip."""
    last = connection.execute("SELECT MAX(classified_at) AS at FROM verdicts").fetchone()["at"]
    return {
        "totals": totals(connection, mailbox),
        "reviewReasons": review_breakdown(connection, mailbox),
        "timeline": timeline(connection, mailbox),
        "mailboxes": _distinct(connection, "mailbox"),
        "models": _distinct(connection, "model"),
        "lastClassifiedAt": last,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
    }
