"""Phase 1 proof of concept: read a real mailbox, classify it, print a table.

No database, no web UI, no attachment parsing yet. The point is to prove the
whole path end to end against real Polish mail and to find out what real prose
does to a classifier tuned on five hand-written samples.

PRIVACY: subjects, senders and bodies are REDACTED by default. This output gets
read by an assistant whose context leaves the machine, so content must be opted
into explicitly with --show-content, and only when a person is reading it.

READ-ONLY: nothing is written, moved, deleted, sent or marked as read.

Examples:
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --list-stores
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --store you@firma.com --limit 20
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --store you@firma.com --since 2026-08-01 --show-content
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mail_analyzer.classify import Classifier  # noqa: E402
from mail_analyzer.ingestion.base import RawMessage  # noqa: E402
from mail_analyzer.ingestion.outlook_mapi import OutlookMapiSource  # noqa: E402
from mail_analyzer.normalize import reply_text  # noqa: E402
from mail_analyzer.review import review_reasons  # noqa: E402


def tag(text: str) -> str:
    """A stable short handle for a redacted field, so rows stay discussable."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def list_stores() -> int:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    for store in ns.Stores:
        try:
            root = store.GetRootFolder()
            folders = [f.Name for f in root.Folders]
        except Exception:
            folders = []
        print(f"{store.DisplayName}")
        print(f"    folders: {', '.join(folders[:8])}{' ...' if len(folders) > 8 else ''}")
    return 0


def describe(message: RawMessage, show_content: bool) -> str:
    if show_content:
        return f"{(message.sender_address or '?')[:34]:34s} {message.subject[:44]}"
    domain = message.sender_domain or "(no smtp domain)"
    return f"{domain[:24]:24s} subj#{tag(message.subject)}  body {len(message.body):>6d} ch"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", help="mailbox display name, as shown by --list-stores")
    ap.add_argument("--folder", default="Skrzynka odbiorcza")
    ap.add_argument("--since", help="YYYY-MM-DD; only messages received on or after")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--show-content", action="store_true",
                    help="print real subjects and senders (a person is reading this)")
    ap.add_argument("--list-stores", action="store_true")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    if args.list_stores:
        return list_stores()
    if not args.store:
        ap.error("--store is required (see --list-stores)")

    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    source = OutlookMapiSource(store_name=args.store, folder_name=args.folder)
    classifier = Classifier(model=args.model) if args.model else Classifier()

    if not args.show_content:
        print("(content redacted -- pass --show-content to see subjects and senders)\n")

    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    queued = 0
    processed = 0
    empty_bodies = 0
    started = time.perf_counter()

    for message in source.fetch(since=since):
        if processed >= args.limit:
            break

        text = reply_text(message.body)
        if not text.strip():
            empty_bodies += 1
            continue

        verdict = classifier.classify(text)
        why = review_reasons(verdict, text)
        queued += bool(why)
        statuses[verdict.status] += 1
        for reason in why:
            reasons[reason.value] += 1
        if message.sender_domain:
            domains[message.sender_domain] += 1
        processed += 1

        flag = ",".join(r.value for r in why) or "AUTO"
        print(f"{processed:3d}  {verdict.status:11s} {flag:34s} {describe(message, args.show_content)}")

    elapsed = time.perf_counter() - started
    print("\n" + "-" * 78)
    print(f"classified     : {processed} messages in {elapsed:.0f}s "
          f"({elapsed / processed:.1f}s each)" if processed else "classified     : 0")
    if empty_bodies:
        print(f"skipped        : {empty_bodies} with no text body after normalisation")
    print(f"statuses       : {dict(statuses)}")
    print(f"review queue   : {queued}/{processed} "
          f"({queued * 100 // processed if processed else 0}%)  {dict(reasons)}")
    print(f"sender domains : {len(domains)} distinct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
