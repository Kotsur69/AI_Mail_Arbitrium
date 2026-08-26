"""Read messages out of a classic Outlook profile over COM.

Requires classic OUTLOOK.EXE with the target mailbox added to the profile. New
Outlook (olk.exe) exposes no object model at all, so it cannot be used here --
probe_outlook.py reports which of the two a machine is actually running.

COM also requires an interactive logged-in desktop session: a Windows service
cannot drive Outlook. That is the standing constraint on any scheduled run.

Read-only by construction: nothing here writes, moves, deletes, sends, or marks
as read.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterator

from arbitrium.attachments.base import Attachment
from arbitrium.ingestion.base import RawMessage

log = logging.getLogger(__name__)

PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
# SenderEmailAddress returns an X.500 DN for Exchange-internal senders, which
# has no domain to group a supplier by. This proptag carries the real SMTP one.
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"
# The attachment's raw content. Reading it here keeps the file in memory --
# SaveAsFile is the usual route and it puts supplier documents on disk.
PR_ATTACH_DATA_BIN = "http://schemas.microsoft.com/mapi/proptag/0x37010102"

# Outlook's Restrict parser wants US-format dates regardless of system locale.
RESTRICT_DATE_FORMAT = "%m/%d/%Y %I:%M %p"

OL_MAIL_ITEM = 43
OL_FOLDER_INBOX = 6

# Outlook names its folders in the display language, so a config file cannot
# hard-code one. These are the fallbacks used when the store refuses to hand
# over its default inbox.
INBOX_ALIASES = ("skrzynka odbiorcza", "inbox", "posteingang", "boite de reception")


def restrict_clause(since: datetime) -> str:
    """A server-side date filter, so a backlog scan does not pull every item."""
    return f"[ReceivedTime] >= '{since.strftime(RESTRICT_DATE_FORMAT)}'"


def _get(item: Any, name: str, default: Any = None) -> Any:
    """Read one COM property, tolerating the many ways a single item can fail."""
    try:
        return getattr(item, name)
    except Exception:  # noqa: BLE001 - COM raises anything; one bad item must not stop the run
        return default


def _message_id(item: Any) -> str | None:
    try:
        value = item.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID)
    except Exception:  # noqa: BLE001
        return None
    return value or None


def sender_address(item: Any) -> str:
    """The sender's SMTP address, trying the routes that survive Exchange.

    SenderEmailAddress alone yields "/O=EXCHANGELABS/OU=.../CN=abc" for internal
    senders -- unusable for grouping. Three fallbacks, best first.
    """
    try:
        smtp = item.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS)
        if smtp and "@" in smtp:
            return smtp
    except Exception:  # noqa: BLE001
        pass

    try:
        resolved = item.Sender.GetExchangeUser().PrimarySmtpAddress
        if resolved and "@" in resolved:
            return resolved
    except Exception:  # noqa: BLE001
        pass

    return _get(item, "SenderEmailAddress", "") or ""


def _attachment_bytes(attachment: Any) -> bytes | None:
    """The attachment's content, read straight out of the store.

    Outlook refuses this property for some item types -- embedded messages, OLE
    objects -- and None is the honest answer there. SaveAsFile would work around
    it, at the cost of writing supplier contracts to disk; extraction is
    in-memory precisely so that never happens, so the refusal is accepted and
    reported instead.
    """
    try:
        raw = attachment.PropertyAccessor.GetProperty(PR_ATTACH_DATA_BIN)
        return bytes(raw) if raw else None
    except Exception:  # noqa: BLE001 - COM raises anything; one attachment must not stop the run
        return None


def _attachments(item: Any) -> tuple[Attachment, ...]:
    """Every attachment, with bytes loaded only for the kinds we can read.

    A signature logo is an attachment too. Pulling its content over COM buys
    nothing, so only extractable kinds within the size cap are fetched.
    """
    try:
        collection = item.Attachments
        count = collection.Count
    except Exception:  # noqa: BLE001
        return ()

    found: list[Attachment] = []
    for index in range(1, count + 1):
        try:
            com = collection.Item(index)
            name = com.FileName or ""
        except Exception:  # noqa: BLE001
            continue
        if not name:
            continue

        size = _get(com, "Size")
        stub = Attachment(name, size_bytes=size if isinstance(size, int) else None)
        data = _attachment_bytes(com) if stub.is_extractable else None
        found.append(Attachment(name, data, len(data) if data is not None else stub.size_bytes))

    return tuple(found)


def _received_at(item: Any) -> datetime | None:
    raw = _get(item, "ReceivedTime")
    if raw is None:
        return None
    try:
        # pywin32 hands back a PyTime; datetime(...) round-trips it safely.
        return datetime(raw.year, raw.month, raw.day, raw.hour, raw.minute, raw.second)
    except Exception:  # noqa: BLE001
        return None


def to_raw_message(item: Any, folder_name: str) -> RawMessage:
    """Map one Outlook item onto the source-independent record.

    Takes a duck-typed item so it can be exercised without Outlook present.
    """
    return RawMessage(
        message_id=_message_id(item),
        received_at=_received_at(item),
        sender_address=sender_address(item),
        subject=_get(item, "Subject", "") or "",
        body=_get(item, "Body", "") or "",
        folder=folder_name,
        attachments=_attachments(item),
    )


def find_store(namespace: Any, wanted: str) -> Any:
    """The store whose display name best matches `wanted`.

    Matching is deliberately loose. A store shows up in Outlook as an address
    ("zgody@firma.pl"), as a display name ("Zgody - Dostawcy"), or as either one
    with a suffix, and which of those a person types should not decide whether
    the run works. Exact wins over prefix, prefix over substring, so a loose
    match can never shadow a store someone named exactly.
    """
    needle = wanted.strip().lower()
    names: list[str] = []
    exact = prefix = contains = None

    for store in namespace.Stores:
        name = (_get(store, "DisplayName", "") or "").strip()
        names.append(name)
        low = name.lower()
        if low == needle:
            exact = exact or store
        elif low.startswith(needle) or needle.startswith(low):
            prefix = prefix or store
        elif needle in low:
            contains = contains or store

    match = exact or prefix or contains
    if match is not None:
        return match
    raise LookupError(
        f"store {wanted!r} not in this Outlook profile. Available: {', '.join(names) or '(none)'}"
    )


def _child(folder: Any, wanted: str) -> Any:
    """One subfolder by name, case-insensitively, falling back to a substring."""
    needle = wanted.strip().lower()
    names: list[str] = []
    fuzzy = None

    for sub in folder.Folders:
        name = (_get(sub, "Name", "") or "").strip()
        names.append(name)
        if name.lower() == needle:
            return sub
        if fuzzy is None and needle in name.lower():
            fuzzy = sub

    if fuzzy is not None:
        return fuzzy
    raise LookupError(f"folder {wanted!r} not found. Available: {', '.join(names) or '(none)'}")


def default_inbox(store: Any) -> Any:
    """The store's own inbox, whatever the display language calls it."""
    try:
        folder = store.GetDefaultFolder(OL_FOLDER_INBOX)
        if folder is not None:
            return folder
    except Exception:  # noqa: BLE001 - archive and public-folder stores have no default inbox
        pass

    root = store.GetRootFolder()
    for sub in root.Folders:
        if (_get(sub, "Name", "") or "").strip().lower() in INBOX_ALIASES:
            return sub
    raise LookupError(
        f"store {_get(store, 'DisplayName', '?')!r} has no inbox; name a folder explicitly"
    )


def find_folder(store: Any, path: str | None) -> Any:
    """Resolve a configured folder path against a store.

    `None` means the store's inbox. A path may be nested ("Inbox/Dostawcy").
    """
    if not path or not path.strip():
        return default_inbox(store)

    # Either separator, because both look right to somebody.
    steps = [step.strip() for step in path.replace("\\", "/").split("/") if step.strip()]
    folder = store.GetRootFolder()
    for step in steps:
        folder = _child(folder, step)
    return folder


class OutlookMapiSource:
    """A MailSource backed by a classic Outlook profile.

    `store_name` is matched loosely and `folder_name` may be None, so a mailbox
    can be configured by whatever a person can see in Outlook rather than by an
    exact, locale-dependent string.
    """

    def __init__(self, store_name: str, folder_name: str | None = None) -> None:
        self.store_name = store_name
        self.folder_name = folder_name

    def _folder(self, namespace: Any) -> Any:
        return find_folder(find_store(namespace, self.store_name), self.folder_name)

    def fetch(self, since: datetime | None = None) -> Iterator[RawMessage]:
        import pythoncom  # noqa: PLC0415 - Windows-only, imported where it is used
        import win32com.client  # noqa: PLC0415

        pythoncom.CoInitialize()
        try:
            namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            folder = self._folder(namespace)

            items = folder.Items
            items.Sort("[ReceivedTime]", True)
            if since is not None:
                items = items.Restrict(restrict_clause(since))

            item = items.GetFirst()
            while item is not None:
                if _get(item, "Class") == OL_MAIL_ITEM:
                    yield to_raw_message(item, folder.Name)
                else:
                    log.debug("skipping non-mail item in %s", folder.Name)
                item = items.GetNext()
        finally:
            pythoncom.CoUninitialize()
