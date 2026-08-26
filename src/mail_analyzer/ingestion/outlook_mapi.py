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

from mail_analyzer.ingestion.base import RawMessage

log = logging.getLogger(__name__)

PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
# SenderEmailAddress returns an X.500 DN for Exchange-internal senders, which
# has no domain to group a supplier by. This proptag carries the real SMTP one.
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"

# Outlook's Restrict parser wants US-format dates regardless of system locale.
RESTRICT_DATE_FORMAT = "%m/%d/%Y %I:%M %p"

OL_MAIL_ITEM = 43


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


def _attachment_names(item: Any) -> tuple[str, ...]:
    try:
        attachments = item.Attachments
        count = attachments.Count
    except Exception:  # noqa: BLE001
        return ()
    names: list[str] = []
    for index in range(1, count + 1):
        try:
            names.append(attachments.Item(index).FileName or "")
        except Exception:  # noqa: BLE001
            names.append("")
    return tuple(n for n in names if n)


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
        attachment_names=_attachment_names(item),
    )


class OutlookMapiSource:
    """A MailSource backed by a classic Outlook profile."""

    def __init__(self, store_name: str, folder_name: str = "Skrzynka odbiorcza") -> None:
        self.store_name = store_name
        self.folder_name = folder_name

    def _folder(self, namespace: Any) -> Any:
        for store in namespace.Stores:
            if _get(store, "DisplayName", "") != self.store_name:
                continue
            root = store.GetRootFolder()
            for sub in root.Folders:
                if sub.Name == self.folder_name:
                    return sub
            raise LookupError(f"folder {self.folder_name!r} not in store {self.store_name!r}")
        raise LookupError(f"store {self.store_name!r} not in this Outlook profile")

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
