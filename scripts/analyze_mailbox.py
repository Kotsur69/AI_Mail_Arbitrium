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
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --all --no-attachments
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --all --csv raport.csv
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --all --db data/arbitrium.db
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --report-only --db data/arbitrium.db --csv raport.csv
  .venv/Scripts/python.exe scripts/analyze_mailbox.py --store you@firma.pl --show-content
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from arbitrium.attachments.base import Extraction  # noqa: E402
from arbitrium.attachments.extract import attachment_text, extract_all  # noqa: E402
from arbitrium.attachments.vision import VisionReader  # noqa: E402
from arbitrium.classify import Classifier  # noqa: E402
from arbitrium.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    AppConfig,
    AttachmentsConfig,
    CampaignConfig,
    LlmConfig,
    MailboxConfig,
    VisionConfig,
    load_config,
)
from arbitrium.export import (  # noqa: E402
    MessageRecord,
    suppliers_path,
    write_messages_csv,
    write_suppliers_csv,
)
from arbitrium.ingestion.base import RawMessage, dedupe_key  # noqa: E402
from arbitrium.ingestion.outlook_mapi import OutlookMapiSource  # noqa: E402
from arbitrium.normalize import reply_text  # noqa: E402
from arbitrium.review import review_reasons, supporting_status  # noqa: E402
from arbitrium.store import VerdictStore  # noqa: E402


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


def attachment_note(extractions: list[Extraction], show_content: bool) -> str:
    """A compact account of the files on a message, redacted like everything else.

    A filename is content -- "oferta_ArcelorMittal.pdf" names a supplier -- so
    redacted rows carry counts and formats only.
    """
    if not extractions:
        return ""
    if show_content:
        return "  att: " + ", ".join(
            item.filename if item.has_text else f"{item.filename} ({item.error})"
            for item in extractions
        )
    readable = sum(1 for item in extractions if item.has_text)
    kinds = "/".join(sorted({item.kind.value for item in extractions}))
    return f"  att {readable}/{len(extractions)} {kinds}"


@dataclass(frozen=True, slots=True)
class Backfill:
    """The store a run resumes from, and what it already holds.

    Constructed even without --db, with no store and an empty set, so the
    classify loop has one code path rather than a branch on every message.
    """

    model: str
    store: VerdictStore | None = None
    seen: frozenset[str] = frozenset()

    def done(self, key: str) -> bool:
        return key in self.seen

    def keep(self, key: str, record: MessageRecord) -> None:
        if self.store is not None:
            self.store.save(key, record, self.model)


class Run:
    """What one mailbox produced, kept addable so several can share a total."""

    def __init__(self) -> None:
        self.records: list[MessageRecord] = []
        self.skipped_known = 0
        self.statuses: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        self.domains: Counter[str] = Counter()
        self.attachment_problems: Counter[str] = Counter()
        self.processed = 0
        self.queued = 0
        self.empty_bodies = 0
        self.attachments_seen = 0
        self.attachments_read = 0
        self.attachments_transcribed = 0
        self.seconds = 0.0

    def absorb(self, other: Run) -> None:
        self.records += other.records
        self.skipped_known += other.skipped_known
        self.statuses += other.statuses
        self.reasons += other.reasons
        self.domains += other.domains
        self.attachment_problems += other.attachment_problems
        self.processed += other.processed
        self.queued += other.queued
        self.empty_bodies += other.empty_bodies
        self.attachments_seen += other.attachments_seen
        self.attachments_read += other.attachments_read
        self.attachments_transcribed += other.attachments_transcribed
        self.seconds += other.seconds

    def report(self, title: str) -> None:
        print("\n" + "-" * 78)
        print(f"mailbox        : {title}")
        if self.skipped_known:
            print(f"already judged : {self.skipped_known} kept from an earlier run")
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
        if self.attachments_seen:
            unreadable = f"  unread: {dict(self.attachment_problems)}" if self.attachment_problems else ""
            print(f"attachments    : {self.attachments_read}/{self.attachments_seen} "
                  f"with readable text{unreadable}")
        if self.attachments_transcribed:
            print(f"scans read     : {self.attachments_transcribed} by the vision model "
                  f"-- each queued for a person to confirm")


def read_attachments(
    message: RawMessage,
    settings: AttachmentsConfig,
    run: Run,
    vision: VisionReader | None = None,
) -> tuple[list[Extraction], str]:
    """Extract what the files on a message say, counting what could not be read."""
    if not settings.enabled or not message.attachments:
        return [], ""

    extractions = extract_all(message.attachments, vision)
    run.attachments_seen += len(extractions)
    for item in extractions:
        if item.has_text:
            run.attachments_read += 1
            run.attachments_transcribed += item.via_vision
        else:
            run.attachment_problems[item.error or "nieznany powod"] += 1

    return extractions, attachment_text(extractions, settings.max_chars)


def run_mailbox(
    box: MailboxConfig,
    classifier: Classifier,
    settings: AttachmentsConfig,
    show_content: bool,
    resume: Backfill,
    vision: VisionReader | None = None,
) -> Run:
    """Classify one configured mailbox. A limit of 0 means everything."""
    source = OutlookMapiSource(
        store_name=box.store, folder_name=box.folder, load_images=vision is not None
    )
    run = Run()
    started = time.perf_counter()

    for message in source.fetch(since=box.since_datetime):
        if box.limit and run.processed >= box.limit:
            break

        # Checked before anything is read or extracted, and before the limit
        # counts it, so --limit 20 on a resumed run means twenty *new* messages.
        key = dedupe_key(message)
        if resume.done(key):
            run.skipped_known += 1
            continue

        body = reply_text(message.body)
        extractions, attached = read_attachments(message, settings, run, vision)

        # A supplier who answers with nothing but a signed PDF has still
        # answered, so the attachment stands in as the message when the body is
        # empty. Counting that as silence would be the expensive kind of wrong.
        source_text = body if body.strip() else attached
        if not source_text.strip():
            run.empty_bodies += 1
            continue

        verdict = classifier.classify(source_text)

        # A second call only when there is a body for the attachment to
        # disagree with: the conflict is the finding, and when the attachment
        # already is the message there is nothing to compare it against.
        support = None
        if attached.strip() and body.strip():
            support = supporting_status(classifier.classify(attached), attached)

        # Only flag the transcript when it actually fed a verdict: as the
        # message itself where the body was empty, or as the attachment's vote.
        # A scan the model called ambiguous changed nothing, and queueing on it
        # would be a caveat about evidence nobody used.
        transcribed = any(item.via_vision and item.has_text for item in extractions)
        from_vision = transcribed and (not body.strip() or support is not None)

        why = review_reasons(verdict, source_text, support, from_vision)
        entry = MessageRecord(
            mailbox=box.name,
            supplier=message.sender_domain,
            sender=message.sender_address,
            subject=message.subject,
            received_at=message.received_at,
            status=verdict.status,
            review_reasons=tuple(r.value for r in why),
            evidence=verdict.evidence,
            rationale=verdict.rationale,
            attachments_total=len(extractions),
            attachments_read=sum(1 for item in extractions if item.has_text),
            attachment_status=support,
        )
        run.records.append(entry)
        resume.keep(key, entry)
        run.queued += bool(why)
        run.statuses[verdict.status] += 1
        for reason in why:
            run.reasons[reason.value] += 1
        if message.sender_domain:
            run.domains[message.sender_domain] += 1
        run.processed += 1

        flag = ",".join(r.value for r in why) or "AUTO"
        print(f"{run.processed:3d}  {verdict.status:11s} {flag:34s} "
              f"{describe(message, show_content)}"
              f"{attachment_note(extractions, show_content)}")

    run.seconds = time.perf_counter() - started
    return run


def overridden(box: MailboxConfig, args: argparse.Namespace) -> MailboxConfig:
    """This run's flags applied on top of the file.

    A flag always wins, and it wins for every selected mailbox -- narrowing a
    run should never mean editing configuration, and --all --limit 5 must not
    quietly read whole inboxes.
    """
    return box.model_copy(update={
        "folder": args.folder or box.folder,
        "since": args.since or box.since,
        "limit": box.limit if args.limit is None else args.limit,
    })


def selected(args: argparse.Namespace, config: AppConfig | None) -> list[MailboxConfig]:
    """Which mailboxes this invocation asked for, from the config or from flags."""
    if args.store:
        return [overridden(MailboxConfig(name="adhoc", store=args.store), args)]
    if config is None:
        return []

    boxes = list(config.enabled) if args.all else [config.mailbox(args.mailbox)]
    return [overridden(box, args) for box in boxes]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mailbox", help="name of a mailbox in the config file")
    ap.add_argument("--all", action="store_true", help="every enabled mailbox in the config file")
    ap.add_argument("--store", help="ad hoc mailbox, bypassing the config file")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--folder", default=None, help="override the folder; default is the inbox")
    ap.add_argument("--since", help="YYYY-MM-DD; only messages received on or after")
    ap.add_argument("--limit", type=int, default=None, help="0 means no limit")
    ap.add_argument("--no-attachments", action="store_true",
                    help="classify bodies only, without opening any files")
    ap.add_argument("--vision", action="store_true",
                    help="read scanned PDFs and photographed pages with a vision model")
    ap.add_argument("--no-vision", action="store_true",
                    help="leave scans unread even if the config file enables vision")
    ap.add_argument("--vision-model", default=None,
                    help="override the vision model named in the config")
    ap.add_argument("--csv", type=Path, default=None,
                    help="write the report to this file, plus a per-supplier rollup beside it")
    ap.add_argument("--db", type=Path, default=None,
                    help="SQLite file to record verdicts in, so an interrupted run resumes")
    ap.add_argument("--reclassify", action="store_true",
                    help="judge everything again, ignoring what the store already holds")
    ap.add_argument("--report-only", action="store_true",
                    help="write the CSV from --db without reading mail or loading the model")
    ap.add_argument("--show-content", action="store_true",
                    help="print real subjects and senders (a person is reading this)")
    ap.add_argument("--list-stores", action="store_true")
    ap.add_argument("--init-config", action="store_true",
                    help="write a starter config from the mailboxes Outlook can see")
    ap.add_argument("--force", action="store_true", help="let --init-config overwrite")
    ap.add_argument("--model", default=None, help="override the model named in the config")
    return ap


def build_vision(
    settings: VisionConfig,
    llm: LlmConfig,
    args: argparse.Namespace,
    attachments: AttachmentsConfig,
) -> VisionReader | None:
    """The vision reader this run should use, or None to leave scans unread.

    Returning None rather than a disabled reader is deliberate: it is the same
    value the whole pipeline already understood to mean "no vision", so every
    call site keeps one branch instead of two, and the Outlook adapter can key
    off it to decide whether image bytes are worth pulling at all.
    """
    wanted = args.vision or (settings.enabled and not args.no_vision)
    if args.no_vision or not wanted or not attachments.enabled:
        return None

    model = args.vision_model or settings.model
    print(f"vision: scans will be read by {model} "
          f"(each one queued for a person to confirm)\n")
    return VisionReader(
        base_url=settings.base_url or llm.base_url,
        model=model,
        max_pages=settings.max_pages,
    )


def write_report(path: Path, records: list[MessageRecord]) -> None:
    """Write both report files and say plainly what is in them.

    The console redacts because its output reaches an assistant's context. These
    files do not, and a redacted report would be useless to the person the CSV
    was chosen for -- so they carry real content, and the run says so out loud
    rather than letting someone discover it by pasting one into a chat.
    """
    if not records:
        print("\nnothing classified, so no report was written")
        return

    messages = write_messages_csv(path, records)
    suppliers = write_suppliers_csv(suppliers_path(path), records)
    print(f"\nwrote {messages}  ({len(records)} messages)")
    print(f"wrote {suppliers}  (grouped by supplier, `decyzja` column left for you)")
    print("both files contain real subjects, senders and quotes -- do not paste them into a chat")


def stored_report(args: argparse.Namespace) -> int:
    """Rebuild the CSV from verdicts already on disk, touching neither mail nor model.

    This is what the store buys beyond resumability: changing a column, or
    reopening a report someone closed, costs seconds instead of hours.
    """
    if not (args.db and args.csv):
        print("--report-only needs --db to read from and --csv to write to")
        return 1

    with VerdictStore(args.db) as store:
        write_report(args.csv, store.records(mailboxes=[args.mailbox] if args.mailbox else None))
    return 0


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.list_stores:
        return list_stores()
    if args.init_config:
        return init_config(args.config, force=args.force)
    if args.report_only:
        return stored_report(args)
    if not (args.mailbox or args.all or args.store):
        ap.error("pass --mailbox NAME, --all, or --store ADDRESS (see --list-stores)")

    args.since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None
    config = None if args.store else load_config(args.config)
    boxes = selected(args, config)
    if not boxes:
        print("no enabled mailboxes in the config file")
        return 1

    llm = config.llm if config else LlmConfig()
    model = args.model or llm.model

    campaign = config.campaign if config else CampaignConfig()
    if campaign.configured:
        print(f"campaign: judging replies against {campaign.subject or '(no subject)'!r}\n")
    else:
        print("no [campaign] configured -- replies are judged without knowing what was "
              "asked, which reads 'Potwierdzam odbior' as consent. See the README.\n")
    classifier = Classifier(
        base_url=llm.base_url, model=model, campaign=campaign.as_prompt_text()
    )

    settings = config.attachments if config else AttachmentsConfig()
    if args.no_attachments:
        settings = settings.model_copy(update={"enabled": False})

    vision = build_vision(config.vision if config else VisionConfig(), llm, args, settings)

    if not args.show_content:
        print("(content redacted -- pass --show-content to see subjects and senders)\n")

    names = [box.name for box in boxes]
    store = VerdictStore(args.db) if args.db else None
    resume = Backfill(
        model=model,
        store=store,
        # --reclassify keeps the store but stops it being trusted, which is what
        # you want after changing the prompt rather than the model.
        seen=frozenset(
            () if store is None or args.reclassify
            else store.classified_keys(mailboxes=names, model=model)
        ),
    )
    if resume.seen:
        print(f"resuming: {len(resume.seen)} messages already judged by {model}\n")

    total = Run()
    try:
        for box in boxes:
            print(f"\n=== {box.name}  [{box.store}] ===")
            run = run_mailbox(box, classifier, settings, args.show_content, resume, vision)
            run.report(f"{box.name} ({box.store})")
            total.absorb(run)

        if len(boxes) > 1:
            total.report(f"TOTAL over {len(boxes)} mailboxes")

        if args.csv:
            # From the store when there is one, so a resumed run reports the
            # whole backfill rather than only what this session happened to add.
            write_report(args.csv, store.records(mailboxes=names) if store else total.records)
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
