"""Mailboxes as configuration, not as command-line archaeology.

Adding a mailbox should mean adding four lines to a TOML file. Nothing here
knows about Outlook: a mailbox entry is a name, a store to read, and the window
to read it over, which is exactly as much as any mail source would need.

Everything is validated on load, because a typo in a store name should fail
before the model is loaded, not after twenty minutes of backfill.
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "mailboxes.toml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "mailboxes.toml.example"

# Keys a [[mailbox]] may inherit from [defaults]. `name` and `store` never can:
# they are what makes an entry that entry.
INHERITABLE = ("folder", "since", "limit", "enabled")


class LlmConfig(BaseModel):
    """Which local endpoint to talk to. Defaults match a stock LM Studio server."""

    base_url: str = "http://localhost:1234/v1"
    model: str = "qwen/qwen3-30b-a3b-2507"


class AttachmentsConfig(BaseModel):
    """Whether attachments are read, and how much of them the model is shown.

    On by default: a supplier who answers with a signed PDF and an empty body
    has still answered, and the run that ignores the PDF records silence.
    """

    enabled: bool = True
    # Matched to Classifier.max_body_chars on purpose. Set it higher and the
    # classifier trims the tail itself, without the marker that tells a reviewer
    # why a quote they can see in the file is not in the prompt.
    max_chars: int = Field(default=12_000, ge=0, description="Cap on the combined text")


class CampaignConfig(BaseModel):
    """The request the suppliers were actually sent.

    Without this the classifier is asked whether a message "expresses
    agreement" while never being shown what the agreement is about, and
    "Potwierdzam odbior" becomes consent -- a false positive measured on a real
    inbox, and the project's one documented accuracy limitation.

    Empty by default, and empty means absent rather than "a request with no
    subject": a run against a mailbox nobody has described should behave exactly
    as it did before, not as though the campaign were blank.
    """

    subject: str = Field(default="", description="Subject line the request went out under")
    description: str = Field(
        default="", description="What the suppliers were actually asked to agree to"
    )

    @property
    def configured(self) -> bool:
        return bool(self.subject.strip() or self.description.strip())

    def as_prompt_text(self) -> str:
        """The campaign as the classifier should read it, or "" for none."""
        if not self.configured:
            return ""
        lines = []
        if self.subject.strip():
            lines.append(f"Temat: {self.subject.strip()}")
        if self.description.strip():
            lines.append(f"Tresc prosby: {self.description.strip()}")
        return "\n".join(lines)


class VisionConfig(BaseModel):
    """Whether scanned attachments are read, and by which model.

    Off by default, unlike attachments. It needs a second set of weights
    resident in LM Studio alongside the classifier, and a backfill that reported
    every scan as unreadable is a better failure than one that dies at message
    four hundred because nobody loaded the vision model.
    """

    enabled: bool = False
    model: str = "qwen2.5-vl-32b-instruct"
    base_url: str | None = Field(
        default=None,
        description="Endpoint serving the vision model. None means share the classifier's, "
        "which is right whenever LM Studio has both models loaded at once.",
    )
    max_pages: int = Field(
        default=4, ge=1, description="Pages of one scanned document sent to the model"
    )


class MailboxConfig(BaseModel):
    """One mailbox to analyse."""

    name: str = Field(min_length=1, description="Short handle used on the command line")
    store: str = Field(min_length=1, description="Mailbox name or SMTP address, matched loosely")
    folder: str | None = Field(
        default=None,
        description="Folder path, e.g. 'Inbox/Dostawcy'. None means the store's inbox, "
        "whatever the Outlook display language calls it.",
    )
    since: date | None = Field(default=None, description="Ignore mail received before this day")
    limit: int = Field(default=0, ge=0, description="0 means no limit")
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _no_spaces(cls, value: str) -> str:
        # The name is typed as a CLI argument, so keep it typeable.
        if any(c.isspace() for c in value):
            raise ValueError(f"mailbox name {value!r} must not contain whitespace")
        return value

    @property
    def since_datetime(self) -> datetime | None:
        """The `since` day as the instant it starts, which is what a source filters on."""
        return None if self.since is None else datetime.combine(self.since, time.min)


class AppConfig(BaseModel):
    """The whole configuration file."""

    llm: LlmConfig = LlmConfig()
    attachments: AttachmentsConfig = AttachmentsConfig()
    vision: VisionConfig = VisionConfig()
    campaign: CampaignConfig = CampaignConfig()
    mailboxes: tuple[MailboxConfig, ...] = ()

    @field_validator("mailboxes")
    @classmethod
    def _unique_names(cls, value: tuple[MailboxConfig, ...]) -> tuple[MailboxConfig, ...]:
        seen: set[str] = set()
        for box in value:
            if box.name in seen:
                raise ValueError(f"duplicate mailbox name {box.name!r}")
            seen.add(box.name)
        return value

    @property
    def enabled(self) -> tuple[MailboxConfig, ...]:
        return tuple(box for box in self.mailboxes if box.enabled)

    def mailbox(self, name: str) -> MailboxConfig:
        """One mailbox by name, or an error that says what the alternatives are."""
        for box in self.mailboxes:
            if box.name == name:
                return box
        known = ", ".join(box.name for box in self.mailboxes) or "(none configured)"
        raise KeyError(f"no mailbox named {name!r}. Configured: {known}")


def _merge_defaults(defaults: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill each entry from [defaults], without letting a default invent an entry."""
    inherited = {k: v for k, v in defaults.items() if k in INHERITABLE}
    return [{**inherited, **entry} for entry in entries]


def parse_config(raw: dict[str, Any]) -> AppConfig:
    """Build an AppConfig from already-parsed TOML. Kept separate so it is testable."""
    return AppConfig(
        llm=LlmConfig(**raw.get("llm", {})),
        attachments=AttachmentsConfig(**raw.get("attachments", {})),
        vision=VisionConfig(**raw.get("vision", {})),
        campaign=CampaignConfig(**raw.get("campaign", {})),
        mailboxes=tuple(
            MailboxConfig(**entry)
            for entry in _merge_defaults(raw.get("defaults", {}), raw.get("mailbox", []))
        ),
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Read the configuration file, or explain how to create one."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"no configuration at {path}. Copy {EXAMPLE_CONFIG_PATH.name} next to it and edit, "
            f"or run analyze_mailbox.py --init-config to generate one from Outlook."
        )
    with path.open("rb") as handle:
        return parse_config(tomllib.load(handle))
