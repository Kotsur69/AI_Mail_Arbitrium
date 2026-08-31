"""Fill a throwaway database with invented supplier replies, to look at the UI.

The real mailbox does not exist yet, and a dashboard reviewed against an empty
database only proves the empty state renders. This writes a campaign's worth of
plausible Polish replies -- consenting, refusing, evasive, off-topic, scanned,
contradicting their own attachment -- so every branch of the interface has
something to draw.

Everything is fabricated. Domains sit under .example.test, which RFC 6761
reserves and nobody can register, and the verdicts are stamped `demo` so a real
run's `--model` filter reclassifies rather than trusting any of it.

Writes to data/demo.db by default, never to the real store.

  .venv/Scripts/python.exe scripts/seed_demo.py
  .venv/Scripts/python.exe scripts/serve_dashboard.py --db data/demo.db
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from arbitrium.export import MessageRecord  # noqa: E402
from arbitrium.store import VerdictStore  # noqa: E402

DEFAULT_PATH = Path("data") / "demo.db"

# Verdicts written by this script are marked as such, so nothing downstream
# mistakes them for something a model actually concluded.
DEMO_MODEL = "demo"

MAILBOX = "dostawcy"

# The campaign opened in late July, which is the window the real backfill has to
# cover. Anchoring the fixtures to it keeps the activity strip honest.
CAMPAIGN_START = datetime(2026, 7, 28, 8, 0)


def _record(
    days: int,
    hour: int,
    domain: str,
    person: str,
    subject: str,
    status: str,
    evidence: str,
    rationale: str,
    reasons: tuple[str, ...] = (),
    attachments: tuple[int, int] = (0, 0),
    attachment_status: str | None = None,
) -> MessageRecord:
    total, read = attachments
    return MessageRecord(
        mailbox=MAILBOX,
        supplier=domain,
        sender=f"{person}@{domain}",
        subject=subject,
        received_at=CAMPAIGN_START + timedelta(days=days, hours=hour),
        status=status,
        review_reasons=reasons,
        evidence=evidence,
        rationale=rationale,
        attachments_total=total,
        attachments_read=read,
        attachment_status=attachment_status,
    )


# One row per interesting shape, not per supplier: the point is coverage of the
# states a reviewer has to tell apart, not volume.
FIXTURES: tuple[MessageRecord, ...] = (
    _record(
        0, 3, "stalmet.example.test", "k.nowak",
        "Re: Zgoda na publikacje danych kontaktowych",
        "zgoda",
        "Wyrazamy zgode na publikacje danych kontaktowych naszej firmy",
        "Dostawca jednoznacznie wyraza zgode w tresci wiadomosci.",
    ),
    _record(
        1, 1, "polimer-tech.example.test", "biuro",
        "Odp: Prosba o zgode",
        "brak_zgody",
        "Nie wyrazamy zgody na udostepnienie tych informacji",
        "Dostawca odmawia wprost, bez warunkow.",
    ),
    _record(
        1, 6, "drewmax.example.test", "m.zielinska",
        "Re: Zgoda na publikacje danych kontaktowych",
        "inne",
        "Zgodzimy sie, jesli beda to wylacznie dane firmowe, bez numerow prywatnych",
        "Zgoda warunkowa -- wymaga decyzji czlowieka.",
        reasons=("ambiguous_status",),
    ),
    _record(
        2, 2, "logitrans.example.test", "sekretariat",
        "Faktura 08/2026",
        "nie_dotyczy",
        "W zalaczeniu przesylamy fakture za sierpien",
        "Wiadomosc nie odnosi sie do prosby o zgode.",
        reasons=("off_topic",),
        attachments=(1, 1),
    ),
    _record(
        3, 4, "chemexpol.example.test", "j.wisniewski",
        "Re: Zgoda -- podpisane oswiadczenie",
        "zgoda",
        "Oswiadczam, ze wyrazam zgode na przetwarzanie i publikacje danych",
        "Zgoda w podpisanym skanie zalaczonym do pustej wiadomosci.",
        reasons=("vision_transcript",),
        attachments=(1, 1),
        attachment_status="zgoda",
    ),
    _record(
        4, 0, "hutmet.example.test", "a.kaczmarek",
        "Re: Prosba o zgode",
        "brak_zgody",
        "Nie wyrazamy zgody",
        "Tresc odmawia, ale zalacznik zawiera podpisana zgode.",
        reasons=("body_attachment_conflict",),
        attachments=(2, 2),
        attachment_status="zgoda",
    ),
    _record(
        5, 5, "elektrobud.example.test", "p.lewandowski",
        "Re: Zgoda na publikacje danych kontaktowych",
        "zgoda",
        "Tak",
        "Cytat zbyt krotki, by uzasadnial decyzje.",
        reasons=("evidence_too_short",),
    ),
    _record(
        6, 2, "termoplast.example.test", "kontakt",
        "Potwierdzenie",
        "zgoda",
        "Potwierdzamy przyjecie zgloszenia",
        "Potwierdzenie odbioru mylnie odczytane jako zgoda.",
        reasons=("evidence_not_grounded",),
    ),
    _record(
        8, 7, "stalmet.example.test", "m.dabrowski",
        "Re: Zgoda na publikacje danych kontaktowych",
        "zgoda",
        "Podtrzymujemy wczesniejsza zgode dla calej grupy kapitalowej",
        "Druga zgoda z tej samej domeny, szerszy zakres.",
    ),
    _record(
        9, 3, "metalplast.example.test", "d.szymanska",
        "Odp: Zgoda",
        "inne",
        "Czy moglibyscie doprecyzowac, ktorych danych dokladnie dotyczy prosba",
        "Kontrpytanie zamiast odpowiedzi.",
        reasons=("ambiguous_status",),
    ),
    _record(
        11, 1, "drewmax.example.test", "biuro",
        "Nieobecnosc",
        "nie_dotyczy",
        "Przebywam na urlopie do 15 wrzesnia",
        "Automatyczna odpowiedz o nieobecnosci.",
        reasons=("off_topic",),
    ),
    _record(
        12, 6, "polimer-tech.example.test", "zarzad",
        "Re: Odp: Prosba o zgode",
        "brak_zgody",
        "Podtrzymujemy stanowisko o braku zgody na publikacje",
        "Odmowa potwierdzona przez zarzad.",
    ),
    _record(
        14, 2, "ekopak.example.test", "handlowy",
        "Re: Prosba o zgode",
        "zgoda",
        "Wyrazamy zgode zgodnie z trescia Panstwa pisma",
        "Zgoda odwolujaca sie wprost do prosby.",
        attachments=(1, 0),
    ),
    _record(
        16, 4, "instalmax.example.test", "serwis",
        "Oferta wspolpracy",
        "nie_dotyczy",
        "Chcielibysmy przedstawic nasza oferte na rok 2027",
        "Korespondencja handlowa, nie odpowiedz na prosbe.",
        reasons=("off_topic",),
    ),
    _record(
        18, 0, "chemexpol.example.test", "sekretariat",
        "Re: Zgoda -- korekta",
        "inne",
        "Prosimy o wstrzymanie publikacji do czasu weryfikacji przez dzial prawny",
        "Wycofanie do czasu opinii prawnej.",
        reasons=("ambiguous_status",),
    ),
)


def seed(path: Path) -> int:
    """Write the fixtures, replacing any earlier demo run at the same path."""
    stamped = datetime.now()
    with VerdictStore(path) as store:
        for index, record in enumerate(FIXTURES, start=1):
            # A stable key so re-running replaces rather than duplicates, and so
            # it can never collide with a real RFC 5322 Message-ID.
            store.save(f"demo-{index:03d}@example.test", record, DEMO_MODEL, stamped)
    return len(FIXTURES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_PATH, help="Where to write demo data")
    args = parser.parse_args(argv)

    count = seed(args.db)
    print(f"Zapisano {count} przykladowych werdyktow do {args.db}")
    print(f"Podglad:  .venv/Scripts/python.exe scripts/serve_dashboard.py --db {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
