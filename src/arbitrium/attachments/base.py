"""What an attachment is, before anyone tries to read it.

Pure data and pure classification by filename: no parsers, no I/O, no Outlook.
The kind decides which extractor runs and, just as importantly, which
attachments are never opened at all -- a signature logo is an attachment too,
and every one of those that gets loaded is bytes moved for nothing.

Nothing here is ever silently dropped. An attachment we cannot read still comes
back as an Extraction carrying the reason, because "the contract was in a scan
we could not open" and "there was no contract" must not look the same to the
person working the review queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(str, Enum):
    """What we expect to be able to do with an attachment."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    TEXT = "text"
    IMAGE = "image"
    LEGACY_OFFICE = "legacy_office"
    UNSUPPORTED = "unsupported"


EXTENSIONS: dict[str, Kind] = {
    "pdf": Kind.PDF,
    "docx": Kind.DOCX,
    "docm": Kind.DOCX,
    "xlsx": Kind.XLSX,
    "xlsm": Kind.XLSX,
    "txt": Kind.TEXT,
    "csv": Kind.TEXT,
    "md": Kind.TEXT,
    "log": Kind.TEXT,
    # Scans and photographed signatures. There is no text layer to pull, so
    # these are the hand-off point to a vision model, not a failure.
    "png": Kind.IMAGE,
    "jpg": Kind.IMAGE,
    "jpeg": Kind.IMAGE,
    "gif": Kind.IMAGE,
    "bmp": Kind.IMAGE,
    "tif": Kind.IMAGE,
    "tiff": Kind.IMAGE,
    # Word 97-2003 and friends. Real, still in circulation, and readable by
    # neither python-docx nor openpyxl -- named so the reason is reportable.
    "doc": Kind.LEGACY_OFFICE,
    "xls": Kind.LEGACY_OFFICE,
    "ppt": Kind.LEGACY_OFFICE,
    "rtf": Kind.LEGACY_OFFICE,
}

EXTRACTABLE: frozenset[Kind] = frozenset({Kind.PDF, Kind.DOCX, Kind.XLSX, Kind.TEXT})
"""The kinds worth spending bytes on. Everything else is described, not loaded."""

# A supplier's signed consent is a page or two. Anything past this is a catalogue
# or a media file that wandered into the thread, and pulling it over COM costs
# more than it can possibly say.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Attachment:
    """One attachment, with its bytes only if something was going to read them."""

    filename: str
    data: bytes | None = None
    size_bytes: int | None = None

    @property
    def extension(self) -> str:
        """The lowercased final suffix, or "" for a name that has none."""
        name = self.filename.strip().rstrip(".")
        if "." not in name:
            return ""
        return name.rsplit(".", 1)[1].lower()

    @property
    def kind(self) -> Kind:
        return EXTENSIONS.get(self.extension, Kind.UNSUPPORTED)

    @property
    def is_extractable(self) -> bool:
        """Whether this is worth loading: a readable kind, of a sane size."""
        if self.kind not in EXTRACTABLE:
            return False
        return self.size_bytes is None or self.size_bytes <= MAX_ATTACHMENT_BYTES


@dataclass(frozen=True, slots=True)
class Extraction:
    """The outcome of trying to read one attachment. Text, or a stated reason."""

    filename: str
    kind: Kind
    text: str = ""
    error: str | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())
