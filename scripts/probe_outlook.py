"""Phase 1 recon: ask Outlook what mailboxes, folders and messages are reachable.

This answers three questions without anyone having to look them up:
  1. Which stores (mailboxes) this Outlook profile can see, and which one holds
     the supplier replies.
  2. Whether the Outlook object model guard blocks reads of .Body and
     .Attachments -- the single biggest risk to unattended operation.
  3. Whether PR_INTERNET_MESSAGE_ID is readable, since it is the only stable
     message key (EntryID gets rewritten when Outlook moves an item).

PRIVACY: this prints structure and counts only -- never a subject, body, sender
or recipient. The output is read by a person and by an assistant whose context
leaves this machine, so message content must not appear in it. Sender domains
are reported as a count, not a list.

READ-ONLY: nothing here writes, moves, deletes, sends or marks as read.

Launching Outlook: COM starts Outlook if it is not already running.

Run:  .venv/Scripts/python.exe scripts/probe_outlook.py
"""

from __future__ import annotations

import sys
import traceback
from collections import Counter
from datetime import datetime, timedelta

import pythoncom
import win32com.client

# MAPI proptag for the RFC 5322 Message-ID -- the stable cross-folder key.
PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"

MAX_FOLDER_DEPTH = 3
SAMPLE_ITEMS = 25


def say(*parts: object) -> None:
    print(*parts, flush=True)


def walk(folder: object, depth: int = 0, seen: list[tuple[str, int, int]] | None = None) -> list[tuple[str, int, int]]:
    """Collect (indented name, item count, depth) for a folder tree, counts only."""
    if seen is None:
        seen = []
    try:
        count = folder.Items.Count
    except Exception:
        count = -1
    seen.append((folder.Name, count, depth))
    if depth < MAX_FOLDER_DEPTH:
        try:
            for sub in folder.Folders:
                walk(sub, depth + 1, seen)
        except Exception:
            pass
    return seen


def probe_guard(items: object) -> None:
    """Try the two properties the object model guard protects."""
    try:
        item = items.GetFirst()
    except Exception as exc:
        say(f"    guard test    : cannot read first item -- {type(exc).__name__}")
        return
    if item is None:
        say("    guard test    : folder empty, nothing to test")
        return

    for label, getter in (
        ("body", lambda: len(item.Body or "")),
        ("attachments", lambda: item.Attachments.Count),
        ("sender domain", lambda: len((item.SenderEmailAddress or "").split("@")[-1])),
    ):
        try:
            size = getter()
            say(f"    guard test    : {label:14s} OK (len/count {size})")
        except Exception as exc:
            say(f"    guard test    : {label:14s} BLOCKED -- {type(exc).__name__}: {exc}")

    try:
        mid = item.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID)
        say(f"    message-id    : readable, {len(mid)} chars")
    except Exception as exc:
        say(f"    message-id    : NOT readable -- {type(exc).__name__}: {exc}")


def summarise_inbox(folder: object) -> None:
    """Date span, attachment prevalence and distinct-domain count. No content."""
    try:
        items = folder.Items
        total = items.Count
    except Exception as exc:
        say(f"    inbox         : unreadable -- {type(exc).__name__}")
        return

    say(f"    inbox items   : {total}")
    if total == 0:
        return

    oldest = newest = None
    with_attachments = 0
    domains: Counter[str] = Counter()
    ext: Counter[str] = Counter()
    sampled = 0

    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass

    item = items.GetFirst()
    while item is not None and sampled < SAMPLE_ITEMS:
        try:
            when = item.ReceivedTime
            when = datetime(when.year, when.month, when.day)
            oldest = when if oldest is None or when < oldest else oldest
            newest = when if newest is None or when > newest else newest
        except Exception:
            pass
        try:
            n = item.Attachments.Count
            if n:
                with_attachments += 1
                for i in range(1, n + 1):
                    name = item.Attachments.Item(i).FileName or ""
                    ext[name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"] += 1
        except Exception:
            pass
        try:
            addr = item.SenderEmailAddress or ""
            if "@" in addr:
                domains[addr.split("@")[-1].lower()] += 1
        except Exception:
            pass
        sampled += 1
        item = items.GetNext()

    say(f"    sampled       : {sampled} most recent")
    if oldest and newest:
        say(f"    date span     : {oldest:%Y-%m-%d} .. {newest:%Y-%m-%d}")
    say(f"    with attach.  : {with_attachments}/{sampled}")
    say(f"    distinct senders (domains, count only): {len(domains)}")
    if ext:
        say(f"    attach types  : {dict(ext.most_common(8))}")


def main() -> int:
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("Outlook.Application")
        ns = app.GetNamespace("MAPI")
    except Exception:
        say("FAILED to attach to Outlook:")
        traceback.print_exc()
        return 1

    try:
        say(f"outlook version : {app.Version}")
    except Exception:
        pass

    try:
        stores = list(ns.Stores)
    except Exception:
        stores = []
    say(f"stores visible  : {len(stores)}")
    say("=" * 74)

    for store in stores:
        try:
            name = store.DisplayName
        except Exception:
            name = "(unnamed)"
        say(f"\nSTORE  {name}")
        try:
            say(f"    type      : {store.ExchangeStoreType}   path set: {bool(store.FilePath)}")
        except Exception:
            pass

        try:
            root = store.GetRootFolder()
        except Exception as exc:
            say(f"    root folder unreachable -- {type(exc).__name__}")
            continue

        tree = walk(root)
        say(f"    folders   : {len(tree)} (to depth {MAX_FOLDER_DEPTH})")
        for fname, count, depth in tree[:40]:
            if count > 0 or depth <= 1:
                say(f"      {'  ' * depth}{fname}  [{count if count >= 0 else '?'}]")

        try:
            inbox = None
            for sub in root.Folders:
                if sub.Name.lower() in ("inbox", "skrzynka odbiorcza"):
                    inbox = sub
                    break
            if inbox is None:
                # Archive and public-folder stores have no inbox of their own.
                # Falling back to the default one would report another store's
                # numbers under this store's name.
                say("    probing inbox : (this store has no inbox -- skipped)")
                continue
            say(f"    probing inbox : {inbox.Name}")
            summarise_inbox(inbox)
            probe_guard(inbox.Items)
        except Exception as exc:
            say(f"    inbox probe failed -- {type(exc).__name__}: {exc}")

    say("\n" + "=" * 74)
    say("done -- no content printed, nothing modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
