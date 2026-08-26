"""Read a mailbox, classify what is in it, print a table.

Mailboxes live in config/mailboxes.toml, so switching or adding one is an edit
to that file rather than a different command line. --store still takes an ad hoc
mailbox for a one-off look.

PRIVACY: subjects, senders and bodies are REDACTED by default. This output gets
read by an assistant whose context leaves the machine, so content must be opted
into explicitly with --show-content, and only when a person is reading it.

READ-ONLY: nothing is written, moved, deleted, sent or marked as read.

Examples:
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --init-config
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --list-stores
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --mailbox dostawcy
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --all --limit 20
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --store you@firma.pl --show-content
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
from mail_analyzer.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    AppConfig,
    LlmConfig,
    MailboxConfig,
    load_config,
)
from mail_analyzer.ingestion.base import RawMessage  # noqa: E402
from mail_analyzer.ingestion.outlook_mapi import OutlookMapiSource  # noqa: E402
from mail_analyzer.normalize import reply_text  # noqa: E402
from mail_analyzer.review import review_reasons  # noqa: E402


def tag(text: str) -> str:
    """A stable short handle for a redacted field, so rows stay discussable."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def outlook_namespace() -> object:
    import pythoncom  # noqa: PLC0415 - Windows-only, imported where it is used
    import win32com.client  # noqa: PLC0415

    pythoncom.CoInitialize()
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")


def list_stores() -> int:
    """Print every mailbox this Outlook profile can see, with its top folders."""
    for store in outlook_namespace().Stores:
        try:
            folders = [f.Name for f in store.GetRootFolder().Folders]
        except Exception:  # noqa: BLE001 - a store can be offline or password-locked
            folders = []
        print(store.DisplayName)
        print(f"    folders: {', '.join(folders[:8])}{' ...' if len(folders) > 8 else ''}")
    return 0


def slugify(store: str) -> str:
    """A short, typeable handle derived from a mailbox name."""
    head = store.split("@")[0]
    cleaned = "".join(c if c.isalnum() else "-" for c in head.lower()).strip("-")
    return cleaned or "mailbox"


def is_mailbox(store: str) -> bool:
    """Whether a store is somewhere mail arrives, rather than an archive.

    A real mailbox shows up as a bare address. Archives and public folder trees
    carry a descriptive name that happens to contain one -- measured on a real
    profile, all three stores held an "@" and only one was a mailbox.
    """
    stripped = store.strip()
    return "@" in stripped and not any(c.isspace() for c in stripped)


def config_text(stores: list[str]) -> str:
    """A starter configuration file listing the mailboxes Outlook can see."""
    lines = ["# Generated from this Outlook profile. Edit freely.", "", "[defaults]", "limit = 0", ""]
    used: set[str] = set()

    for store in stores:
        name = slugify(store)
        while name in used:
            name += "-2"
        used.add(name)
        lines += [
            "[[mailbox]]",
            f'name = "{name}"',
            f'store = "{store}"',
            f"enabled = {str(is_mailbox(store)).lower()}",
            "",
        ]
    return "\n".join(lines)


def init_config(path: Path, force: bool = False) -> int:
    if path.exists() and not force:
        print(f"{path} already exists. Edit it, or pass --force to overwrite.")
        return 1

    stores = [store.DisplayName for store in outlook_namespace().Stores]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_text(stores), encoding="utf-8")
    print(f"wrote {path} with {len(stores)} mailbox entries -- edit it, then run --all")
    return 0


def describe(message: RawMessage, show_content: bool) -> str:
    if show_content:
        return f"{(message.sender_address or '?')[:34]:34s} {message.subject[:44]}"
    domain = message.sender_domain or "(no smtp domain)"
    return f"{domain[:24]:24s} subj#{tag(message.subject)}  body {len(message.body):>6d} ch"


class Run:
    """What one mailbox produced, kept addable so several can share a total."""

    def __init__(self) -> None:
        self.statuses: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        self.domains: Counter[str] = Counter()
        self.processed = 0
        self.queued = 0
        self.empty_bodies = 0
        self.seconds = 0.0

    def absorb(self, other: Run) -> None:
        self.statuses += other.statuses
        self.reasons += other.reasons
        self.domains += other.domains
        self.processed += other.processed
        self.queued += other.queued
        self.empty_bodies += other.empty_bodies
        self.seconds += other.seconds

    def report(self, title: str) -> None:
        print("\n" + "-" * 78)
        print(f"mailbox        : {title}")
        if not self.processed:
            print("classified     : 0 messages")
            return
        print(f"classified     : {self.processed} messages in {self.seconds:.0f}s "
              f"({self.seconds / self.processed:.1f}s each)")
        if self.empty_bodies:
            print(f"skipped        : {self.empty_bodies} with no text body after normalisation")
        print(f"statuses       : {dict(self.statuses)}")
        print(f"review queue   : {self.queued}/{self.processed} "
              f"({self.queued * 100 // self.processed}%)  {dict(self.reasons)}")
        print(f"sender domains : {len(self.domains)} distinct")


def run_mailbox(box: MailboxConfig, classifier: Classifier, show_content: bool) -> Run:
    """Classify one configured mailbox. A limit of 0 means everything."""
    source = OutlookMapiSource(store_name=box.store, folder_name=box.folder)
    run = Run()
    started = time.perf_counter()

    for message in source.fetch(since=box.since_datetime):
        if box.limit and run.processed >= box.limit:
            break

        text = reply_text(message.body)
        if not text.strip():
            run.empty_bodies += 1
            continue

        verdict = classifier.classify(text)
        why = review_reasons(verdict, text)
        run.queued += bool(why)
        run.statuses[verdict.status] += 1
        for reason in why:
            run.reasons[reason.value] += 1
        if message.sender_domain:
            run.domains[message.sender_domain] += 1
        run.processed += 1

        flag = ",".join(r.value for r in why) or "AUTO"
        print(f"{run.processed:3d}  {verdict.status:11s} {flag:34s} "
              f"{describe(message, show_content)}")

    run.seconds = time.perf_counter() - started
    return run


def selected(args: argparse.Namespace, config: AppConfig | None) -> list[MailboxConfig]:
    """Which mailboxes this invocation asked for, from the config or from flags."""
    if args.store:
        return [MailboxConfig(name="adhoc", store=args.store, folder=args.folder,
                              since=args.since, limit=args.limit or 0)]
    if config is None:
        return []
    if args.all:
        return list(config.enabled)

    # An explicit flag beats the file, so narrowing one run needs no edit.
    box = config.mailbox(args.mailbox)
    return [box.model_copy(update={
        "folder": args.folder or box.folder,
        "since": args.since or box.since,
        "limit": box.limit if args.limit is None else args.limit,
    })]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mailbox", help="name of a mailbox in the config file")
    ap.add_argument("--all", action="store_true", help="every enabled mailbox in the config file")
    ap.add_argument("--store", help="ad hoc mailbox, bypassing the config file")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--folder", default=None, help="override the folder; default is the inbox")
    ap.add_argument("--since", help="YYYY-MM-DD; only messages received on or after")
    ap.add_argument("--limit", type=int, default=None, help="0 means no limit")
    ap.add_argument("--show-content", action="store_true",
                    help="print real subjects and senders (a person is reading this)")
    ap.add_argument("--list-stores", action="store_true")
    ap.add_argument("--init-config", action="store_true",
                    help="write a starter config from the mailboxes Outlook can see")
    ap.add_argument("--force", action="store_true", help="let --init-config overwrite")
    ap.add_argument("--model", default=None, help="override the model named in the config")
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.list_stores:
        return list_stores()
    if args.init_config:
        return init_config(args.config, force=args.force)
    if not (args.mailbox or args.all or args.store):
        ap.error("pass --mailbox NAME, --all, or --store ADDRESS (see --list-stores)")

    args.since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None
    config = None if args.store else load_config(args.config)
    boxes = selected(args, config)
    if not boxes:
        print("no enabled mailboxes in the config file")
        return 1

    llm = config.llm if config else LlmConfig()
    classifier = Classifier(base_url=llm.base_url, model=args.model or llm.model)

    if not args.show_content:
        print("(content redacted -- pass --show-content to see subjects and senders)\n")

    total = Run()
    for box in boxes:
        print(f"\n=== {box.name}  [{box.store}] ===")
        run = run_mailbox(box, classifier, args.show_content)
        run.report(f"{box.name} ({box.store})")
        total.absorb(run)

    if len(boxes) > 1:
        total.report(f"TOTAL over {len(boxes)} mailboxes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
