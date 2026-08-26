"""The record every mail source produces, and the protocol they satisfy.

Outlook MAPI is the live route; exported files back the golden set and the
tests. Both yield RawMessage, so everything downstream -- normalisation,
classification, review, rollup -- never learns which one it is talking to.

Fields a source cannot answer are None. Never a guess, never an empty string
standing in for absent, because "no sender" and "sender we failed to read" have
to stay distinguishable when the review queue explains itself to a person.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

from arbitrium.attachments.base import Attachment


@dataclass(frozen=True, slots=True)
class RawMessage:
    """One message as read from a mailbox, before any processing."""

    message_id: str | None
    received_at: datetime | None
    sender_address: str
    subject: str
    body: str
    folder: str
    attachments: tuple[Attachment, ...] = field(default=())

    @property
    def sender_domain(self) -> str | None:
        return sender_domain(self.sender_address)

    @property
    def attachment_names(self) -> tuple[str, ...]:
        return tuple(a.filename for a in self.attachments)

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)


def sender_domain(address: str) -> str | None:
    """The SMTP domain, or None when there isn't one.

    Exchange returns an X.500 distinguished name for internal senders rather
    than an SMTP address; those have no domain and must not be coerced into one.
    """
    cleaned = (address or "").strip().lower()
    if cleaned.startswith("/o="):
        return None
    if cleaned.count("@") != 1:
        return None
    domain = cleaned.rsplit("@", 1)[1]
    return domain or None


def dedupe_key(message: RawMessage) -> str:
    """A key that survives Outlook moving the item between folders.

    RFC 5322 Message-ID when the item has one. EntryID deliberately is not used
    even as a fallback: Outlook rewrites it on a folder move, which would make
    the same message look new after archiving.
    """
    if message.message_id:
        return message.message_id

    stamp = message.received_at.isoformat() if message.received_at else ""
    digest = hashlib.sha256(
        "\x00".join((message.sender_address, message.subject, stamp, message.body)).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


@runtime_checkable
class MailSource(Protocol):
    """Anything that can hand over messages: Outlook, exported files, or a fake."""

    def fetch(self, since: datetime | None = None) -> Iterator[RawMessage]:
        """Yield messages received at or after `since`, newest first."""
        ...
