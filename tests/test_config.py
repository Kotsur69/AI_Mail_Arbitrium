"""Configuration is the plug-and-go surface: adding a mailbox must stay a file edit."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from mail_analyzer.config import AppConfig, MailboxConfig, parse_config

RAW = {
    "llm": {"base_url": "http://localhost:9999/v1", "model": "some-model"},
    "defaults": {"limit": 50, "enabled": True},
    "mailbox": [
        {"name": "dostawcy", "store": "zgody@firma.pl", "folder": "Skrzynka odbiorcza",
         "since": date(2026, 7, 25)},
        {"name": "moja", "store": "you@firma.pl", "enabled": False},
    ],
}


def test_mailboxes_inherit_the_defaults_block() -> None:
    config = parse_config(RAW)

    assert [box.name for box in config.mailboxes] == ["dostawcy", "moja"]
    assert all(box.limit == 50 for box in config.mailboxes)


def test_an_entry_overrides_what_it_inherits() -> None:
    config = parse_config({**RAW, "defaults": {"limit": 50, "enabled": True}})

    assert config.mailbox("moja").enabled is False


def test_defaults_cannot_invent_an_entry() -> None:
    # name and store are what makes an entry that entry, so they never inherit.
    with pytest.raises(ValidationError):
        parse_config({"defaults": {"store": "zgody@firma.pl"}, "mailbox": [{"name": "x"}]})


def test_enabled_lists_only_the_switched_on_mailboxes() -> None:
    assert [box.name for box in parse_config(RAW).enabled] == ["dostawcy"]


def test_llm_settings_are_read_from_the_file() -> None:
    config = parse_config(RAW)

    assert config.llm.base_url == "http://localhost:9999/v1"
    assert config.llm.model == "some-model"


def test_llm_settings_fall_back_to_a_stock_lm_studio_server() -> None:
    config = parse_config({"mailbox": []})

    assert config.llm.base_url == "http://localhost:1234/v1"


def test_an_unknown_mailbox_names_the_ones_that_do_exist() -> None:
    with pytest.raises(KeyError, match="dostawcy"):
        parse_config(RAW).mailbox("nie-ma-takiej")


def test_duplicate_names_are_rejected() -> None:
    entry = {"name": "same", "store": "a@firma.pl"}

    with pytest.raises(ValidationError, match="duplicate"):
        parse_config({"mailbox": [entry, {**entry, "store": "b@firma.pl"}]})


def test_a_name_with_whitespace_is_rejected() -> None:
    # The name is typed as a CLI argument, so it has to stay one word.
    with pytest.raises(ValidationError):
        MailboxConfig(name="dwa slowa", store="a@firma.pl")


def test_since_becomes_the_instant_that_day_starts() -> None:
    box = MailboxConfig(name="x", store="a@firma.pl", since=date(2026, 7, 25))

    assert box.since_datetime == datetime(2026, 7, 25, 0, 0, 0)


def test_no_since_means_no_lower_bound() -> None:
    assert MailboxConfig(name="x", store="a@firma.pl").since_datetime is None


def test_a_folder_is_optional_so_the_inbox_can_be_found_by_the_source() -> None:
    assert MailboxConfig(name="x", store="a@firma.pl").folder is None


def test_an_empty_file_is_a_valid_but_empty_configuration() -> None:
    assert parse_config({}) == AppConfig()


# --- generated configuration ------------------------------------------------


def test_only_real_mailboxes_are_switched_on_in_a_generated_config() -> None:
    from analyze_mailbox import config_text

    # All three of these came off a real Outlook profile, and all three
    # contain an "@" -- only the first is somewhere mail arrives.
    text = config_text([
        "mateusz.mazur@firma.pl",
        "Archiwum online - mateusz.mazur@firma.pl",
        "Foldery publiczne - mateusz.mazur@firma.pl",
    ])

    assert text.count("enabled = true") == 1
    assert text.count("enabled = false") == 2


def test_a_generated_config_parses_back(tmp_path) -> None:
    import tomllib

    from analyze_mailbox import config_text
    from mail_analyzer.config import parse_config

    config = parse_config(tomllib.loads(config_text(["a@firma.pl", "b@firma.pl"])))

    assert [box.name for box in config.mailboxes] == ["a", "b"]


def test_generated_names_stay_unique() -> None:
    from analyze_mailbox import config_text

    text = config_text(["same@firma.pl", "same@inna.pl"])

    assert 'name = "same"' in text and 'name = "same-2"' in text


# --- flag overrides ---------------------------------------------------------


def args_for(*argv: str):
    from analyze_mailbox import build_parser

    return build_parser().parse_args(list(argv))


def two_mailboxes() -> AppConfig:
    return parse_config({"mailbox": [
        {"name": "a", "store": "a@firma.pl", "limit": 0, "folder": "Inbox"},
        {"name": "b", "store": "b@firma.pl", "limit": 0},
    ]})


def test_limit_applies_to_every_mailbox_under_all() -> None:
    # Without this, --all --limit 5 reads whole inboxes.
    from analyze_mailbox import selected

    boxes = selected(args_for("--all", "--limit", "5"), two_mailboxes())

    assert [box.limit for box in boxes] == [5, 5]


def test_a_flag_overrides_the_file_for_one_run() -> None:
    from analyze_mailbox import selected

    boxes = selected(args_for("--mailbox", "a", "--folder", "Dostawcy"), two_mailboxes())

    assert boxes[0].folder == "Dostawcy"


def test_without_flags_the_file_is_used_as_written() -> None:
    from analyze_mailbox import selected

    boxes = selected(args_for("--mailbox", "a"), two_mailboxes())

    assert (boxes[0].folder, boxes[0].limit) == ("Inbox", 0)


def test_an_ad_hoc_store_needs_no_config_file() -> None:
    from analyze_mailbox import selected

    boxes = selected(args_for("--store", "c@firma.pl", "--limit", "3"), None)

    assert (boxes[0].store, boxes[0].limit) == ("c@firma.pl", 3)
