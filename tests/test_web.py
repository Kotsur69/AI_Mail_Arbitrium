"""The dashboard's read path: aggregation, filters, and the routes over them.

Two things here are worth more than the rest. The store is opened read-only, so
a bug in a future route cannot damage a backfill -- that is asserted, not
assumed. And a missing database has to render as an empty state rather than a
500, because that is what a fresh checkout looks like.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arbitrium.export import UNKNOWN_SUPPLIER, MessageRecord
from arbitrium.store import VerdictStore
from arbitrium.web import queries
from arbitrium.web.api import create_app

MODEL = "test"


def record(
    *,
    supplier: str | None = "alfa.example.test",
    sender: str = "biuro@alfa.example.test",
    subject: str = "Re: Zgoda",
    received: datetime | None = datetime(2026, 8, 10, 9, 0),
    status: str = "zgoda",
    reasons: tuple[str, ...] = (),
    evidence: str = "wyrazamy zgode",
    rationale: str = "Dostawca potwierdza.",
    mailbox: str = "dostawcy",
    attachments: tuple[int, int] = (0, 0),
) -> MessageRecord:
    total, read = attachments
    return MessageRecord(
        mailbox=mailbox,
        supplier=supplier,
        sender=sender,
        subject=subject,
        received_at=received,
        status=status,
        review_reasons=reasons,
        evidence=evidence,
        rationale=rationale,
        attachments_total=total,
        attachments_read=read,
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A small store covering every status, a queued row and an undated one."""
    path = tmp_path / "verdicts.db"
    rows = {
        "a@example.test": record(),
        "b@example.test": record(
            supplier="beta.example.test",
            sender="zarzad@beta.example.test",
            subject="Odp: Prosba",
            received=datetime(2026, 8, 12, 11, 0),
            status="brak_zgody",
            evidence="nie wyrazamy zgody",
        ),
        "c@example.test": record(
            supplier="beta.example.test",
            subject="Pytanie",
            received=datetime(2026, 8, 14, 8, 0),
            status="inne",
            reasons=("ambiguous_status",),
        ),
        "d@example.test": record(
            supplier=None,
            sender="/O=EXCHANGE/CN=NOWAK",
            subject="Faktura",
            received=datetime(2026, 8, 14, 15, 0),
            status="nie_dotyczy",
            reasons=("off_topic", "vision_transcript"),
            attachments=(2, 1),
        ),
        "e@example.test": record(
            supplier="gamma.example.test",
            subject="Bez daty",
            received=None,
            mailbox="inna",
        ),
    }
    with VerdictStore(path) as store:
        for key, value in rows.items():
            store.save(key, value, MODEL, datetime(2026, 8, 20, 12, 0))
    return path


def test_connect_refuses_a_missing_database(tmp_path: Path) -> None:
    with pytest.raises(queries.DatabaseMissing):
        with queries.connect(tmp_path / "absent.db"):
            pass


def test_connection_is_read_only(db: Path) -> None:
    """The dashboard must not be able to touch a backfill, even by accident."""
    with queries.connect(db) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM verdicts")


def test_totals_count_every_status_and_the_queue(db: Path) -> None:
    with queries.connect(db) as connection:
        result = queries.totals(connection, None)

    assert result["messages"] == 5
    assert result["zgoda"] == 2
    assert result["brak_zgody"] == 1
    assert result["inne"] == 1
    assert result["nie_dotyczy"] == 1
    assert result["review"] == 2
    assert result["with_attachments"] == 1
    assert result["attachments_read"] == 1
    assert result["attachments_total"] == 2


def test_totals_respect_the_mailbox_filter(db: Path) -> None:
    with queries.connect(db) as connection:
        assert queries.totals(connection, "inna")["messages"] == 1


def test_totals_are_zero_rather_than_null_when_nothing_matches(db: Path) -> None:
    """SUM over no rows is NULL in SQL, and the UI has to render a number."""
    with queries.connect(db) as connection:
        result = queries.totals(connection, "nieistniejaca")

    assert result == dict.fromkeys(result, 0)


def test_review_breakdown_counts_each_reason_separately(db: Path) -> None:
    with queries.connect(db) as connection:
        result = queries.review_breakdown(connection, None)

    assert result == {"off_topic": 1, "vision_transcript": 1, "ambiguous_status": 1}


def test_timeline_fills_silent_days(db: Path) -> None:
    """A day with no mail must appear as a zero, not be skipped."""
    with queries.connect(db) as connection:
        result = queries.timeline(connection, None)

    days = [point["day"] for point in result]
    assert days == ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
    assert [point["messages"] for point in result] == [1, 0, 1, 0, 2]
    assert result[-1]["review"] == 2


def test_timeline_is_empty_without_dated_mail(tmp_path: Path) -> None:
    path = tmp_path / "undated.db"
    with VerdictStore(path) as store:
        store.save("x@example.test", record(received=None), MODEL)

    with queries.connect(path) as connection:
        assert queries.timeline(connection, None) == []


def test_suppliers_group_by_domain_and_name_the_missing_one(db: Path) -> None:
    with queries.connect(db) as connection:
        rows = queries.suppliers(connection, None)

    by_name = {row["supplier"]: row for row in rows}
    assert by_name["beta.example.test"]["messages"] == 2
    assert by_name["beta.example.test"]["statuses"]["brak_zgody"] == 1
    assert UNKNOWN_SUPPLIER in by_name


def test_suppliers_put_the_queue_first(db: Path) -> None:
    with queries.connect(db) as connection:
        rows = queries.suppliers(connection, None)

    assert rows[0]["queued"] >= rows[-1]["queued"]
    assert rows[0]["queued"] > 0


def test_messages_are_newest_first_with_undated_last(db: Path) -> None:
    with queries.connect(db) as connection:
        page = queries.messages(connection)

    received = [item["receivedAt"] for item in page["items"]]
    assert received[0] == "2026-08-14T15:00:00"
    assert received[-1] is None


def test_messages_filter_by_status_and_queue(db: Path) -> None:
    with queries.connect(db) as connection:
        assert queries.messages(connection, status="zgoda")["total"] == 2
        assert queries.messages(connection, review_only=True)["total"] == 2


def test_messages_search_covers_quote_and_rationale(db: Path) -> None:
    with queries.connect(db) as connection:
        assert queries.messages(connection, query="nie wyrazamy")["total"] == 1
        assert queries.messages(connection, query="potwierdza")["total"] == 5
        assert queries.messages(connection, query="nieobecne")["total"] == 0


def test_messages_placeholder_supplier_means_no_domain(db: Path) -> None:
    """Clicking the '(brak domeny)' rollup row has to come back with that row."""
    with queries.connect(db) as connection:
        page = queries.messages(connection, supplier=UNKNOWN_SUPPLIER)

    assert page["total"] == 1
    assert page["items"][0]["supplier"] == UNKNOWN_SUPPLIER


def test_messages_page_size_is_capped(db: Path) -> None:
    with queries.connect(db) as connection:
        page = queries.messages(connection, limit=queries.MAX_PAGE_SIZE * 10)

    assert len(page["items"]) <= queries.MAX_PAGE_SIZE


def client(db_path: Path, tmp_path: Path) -> TestClient:
    """An app with no built frontend and no config file -- API surface only."""
    return TestClient(
        create_app(db_path=db_path, config_path=tmp_path / "absent.toml", dist_dir=tmp_path / "nil")
    )


def test_overview_route_reports_the_store(db: Path, tmp_path: Path) -> None:
    payload = client(db, tmp_path).get("/api/overview").json()

    assert payload["dbPresent"] is True
    assert payload["totals"]["messages"] == 5
    assert payload["models"] == [MODEL]
    assert sorted(payload["mailboxes"]) == ["dostawcy", "inna"]


def test_routes_render_a_missing_database_as_empty(tmp_path: Path) -> None:
    """A fresh checkout is a state to draw, not an error to raise."""
    api = client(tmp_path / "absent.db", tmp_path)

    overview = api.get("/api/overview")
    assert overview.status_code == 200
    assert overview.json()["dbPresent"] is False
    assert api.get("/api/suppliers").json() == {"items": []}
    assert api.get("/api/messages").json() == {"total": 0, "items": []}


def test_messages_route_passes_filters_through(db: Path, tmp_path: Path) -> None:
    api = client(db, tmp_path)

    assert api.get("/api/messages", params={"review": True}).json()["total"] == 2
    assert api.get("/api/messages", params={"status": "inne"}).json()["total"] == 1
    assert api.get("/api/messages", params={"mailbox": "inna"}).json()["total"] == 1


def test_messages_route_rejects_an_oversized_page(db: Path, tmp_path: Path) -> None:
    response = client(db, tmp_path).get("/api/messages", params={"limit": queries.MAX_PAGE_SIZE + 1})

    assert response.status_code == 422


def test_campaign_is_absent_without_configuration(db: Path, tmp_path: Path) -> None:
    campaign = client(db, tmp_path).get("/api/overview").json()["campaign"]

    assert campaign["configured"] is False
    assert campaign["subject"] == ""
