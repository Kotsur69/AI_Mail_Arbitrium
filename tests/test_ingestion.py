"""The shape every mail source must produce, whatever it reads from.

Outlook MAPI is the chosen route, but the golden set and every test run off
exported files, so both must yield the same record. Anything a source cannot
answer is None -- never a guess, never an empty string standing in for absent.
"""

from datetime import datetime, timezone

import pytest

from arbitrium.ingestion.base import RawMessage, dedupe_key, sender_domain
from arbitrium.ingestion.outlook_mapi import PR_INTERNET_MESSAGE_ID, PR_SMTP_ADDRESS


def msg(**over: object) -> RawMessage:
    base = {
        "message_id": "<abc123@dostawca.pl>",
        "received_at": datetime(2026, 8, 4, 10, 30, tzinfo=timezone.utc),
        "sender_address": "jan.kowalski@dostawca.pl",
        "subject": "Re: Prosba o zgode",
        "body": "Potwierdzamy.",
        "folder": "Skrzynka odbiorcza",
        "attachment_names": (),
    }
    return RawMessage(**{**base, **over})


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("jan.kowalski@dostawca.pl", "dostawca.pl"),
        ("JAN.KOWALSKI@Dostawca.PL", "dostawca.pl"),
        ("  jan@dostawca.pl  ", "dostawca.pl"),
        ("", None),
        ("not-an-address", None),
        # Exchange hands back an X.500 DN for internal senders, not an SMTP address.
        ("/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=abc", None),
    ],
)
def test_sender_domain_extraction(address: str, expected: str | None) -> None:
    assert sender_domain(address) == expected


def test_message_id_is_the_dedupe_key_when_present() -> None:
    assert dedupe_key(msg()) == "<abc123@dostawca.pl>"


def test_dedupe_key_falls_back_when_the_message_id_is_missing() -> None:
    # Some items (drafts, non-SMTP) carry no Message-ID; they still need a key.
    a = dedupe_key(msg(message_id=None))
    b = dedupe_key(msg(message_id=None))

    assert a == b
    assert a != dedupe_key(msg(message_id=None, subject="inny temat"))


def test_dedupe_key_is_stable_across_folders() -> None:
    # Outlook rewrites EntryID on a folder move, so the key must ignore folder.
    assert dedupe_key(msg()) == dedupe_key(msg(folder="Archiwum"))


def test_has_attachments_follows_the_names() -> None:
    assert msg().has_attachments is False
    assert msg(attachment_names=("aneks.pdf",)).has_attachments is True


def test_domain_is_derived_not_stored_separately() -> None:
    assert msg().sender_domain == "dostawca.pl"
    assert msg(sender_address="").sender_domain is None


def test_raw_message_is_immutable() -> None:
    # Verdicts are attached downstream; the ingested record itself never mutates.
    with pytest.raises(Exception):
        msg().subject = "zmienione"  # type: ignore[misc]


class FakeComItem:
    """Stands in for an Outlook MailItem, including its failure modes."""

    Class = 43

    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)

    def __getattr__(self, name: str) -> object:  # unset properties raise, as COM does
        raise AttributeError(name)


class FakePropertyAccessor:
    """Tag-aware, because message-id and SMTP address share this one interface.

    A fake that ignored the tag would hand the Message-ID back as the sender.
    """

    def __init__(self, message_id: object = "", smtp: object = "") -> None:
        self._by_tag = {PR_INTERNET_MESSAGE_ID: message_id, PR_SMTP_ADDRESS: smtp}

    def GetProperty(self, tag: str) -> object:
        value = self._by_tag.get(tag, "")
        if isinstance(value, Exception):
            raise value
        return value


def test_mapi_item_maps_onto_the_shared_record() -> None:
    from arbitrium.ingestion.outlook_mapi import to_raw_message

    item = FakeComItem(
        PropertyAccessor=FakePropertyAccessor(message_id="<abc@dostawca.pl>", smtp="jan@dostawca.pl"),
        ReceivedTime=datetime(2026, 8, 4, 10, 30),
        SenderEmailAddress="jan@dostawca.pl",
        Subject="Re: zgoda",
        Body="Potwierdzamy.",
        Attachments=None,
    )

    out = to_raw_message(item, "Skrzynka odbiorcza")

    assert out.message_id == "<abc@dostawca.pl>"
    assert out.sender_domain == "dostawca.pl"
    assert out.folder == "Skrzynka odbiorcza"


def test_one_unreadable_property_does_not_lose_the_message() -> None:
    from arbitrium.ingestion.outlook_mapi import to_raw_message

    # Body blocked by the object model guard; everything else still readable.
    item = FakeComItem(
        PropertyAccessor=FakePropertyAccessor(message_id=RuntimeError("blocked")),
        ReceivedTime=datetime(2026, 8, 4, 10, 30),
        SenderEmailAddress="jan@dostawca.pl",
        Subject="Re: zgoda",
    )

    out = to_raw_message(item, "Skrzynka odbiorcza")

    assert out.message_id is None
    assert out.body == ""
    assert out.subject == "Re: zgoda"


def test_restrict_clause_uses_us_dates_whatever_the_system_locale() -> None:
    from arbitrium.ingestion.outlook_mapi import restrict_clause

    clause = restrict_clause(datetime(2026, 8, 4, 0, 0))

    assert clause == "[ReceivedTime] >= '08/04/2026 12:00 AM'"


def test_outlook_source_satisfies_the_mail_source_protocol() -> None:
    from arbitrium.ingestion.base import MailSource
    from arbitrium.ingestion.outlook_mapi import OutlookMapiSource

    assert isinstance(OutlookMapiSource("skrzynka@firma.pl"), MailSource)


class FakeExchangeUser:
    PrimarySmtpAddress = "jan.kowalski@firma.pl"


class FakeSender:
    def GetExchangeUser(self) -> FakeExchangeUser:
        return FakeExchangeUser()


def test_exchange_dn_sender_is_resolved_to_a_real_smtp_address() -> None:
    from arbitrium.ingestion.outlook_mapi import sender_address

    item = FakeComItem(
        PropertyAccessor=FakePropertyAccessor(smtp="jan.kowalski@firma.pl"),
        SenderEmailAddress="/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=abc",
    )

    assert sender_address(item) == "jan.kowalski@firma.pl"


def test_sender_falls_back_to_the_exchange_user_when_the_proptag_is_blocked() -> None:
    from arbitrium.ingestion.outlook_mapi import sender_address

    item = FakeComItem(
        PropertyAccessor=FakePropertyAccessor(smtp=RuntimeError("blocked")),
        Sender=FakeSender(),
        SenderEmailAddress="/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=abc",
    )

    assert sender_address(item) == "jan.kowalski@firma.pl"


def test_sender_keeps_the_plain_smtp_address_when_there_is_one() -> None:
    from arbitrium.ingestion.outlook_mapi import sender_address

    item = FakeComItem(
        PropertyAccessor=FakePropertyAccessor(),
        SenderEmailAddress="jan@dostawca.pl",
    )

    assert sender_address(item) == "jan@dostawca.pl"


def test_sender_returns_the_dn_rather_than_inventing_when_nothing_resolves() -> None:
    from arbitrium.ingestion.base import sender_domain
    from arbitrium.ingestion.outlook_mapi import sender_address

    dn = "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=abc"
    item = FakeComItem(PropertyAccessor=FakePropertyAccessor(smtp=RuntimeError("no")), SenderEmailAddress=dn)

    assert sender_address(item) == dn
    assert sender_domain(sender_address(item)) is None


# --- store and folder resolution -------------------------------------------
# A mailbox is configured by whatever a person can see in Outlook, so both
# lookups have to survive display languages, punctuation and near-misses.


class FakeFolder:
    def __init__(self, name: str, *children: "FakeFolder") -> None:
        self.Name = name
        self.Folders = list(children)


class FakeStore:
    def __init__(self, display_name: str, root: FakeFolder, inbox: FakeFolder | None = None) -> None:
        self.DisplayName = display_name
        self._root = root
        self._inbox = inbox

    def GetRootFolder(self) -> FakeFolder:
        return self._root

    def GetDefaultFolder(self, _kind: int) -> FakeFolder:
        if self._inbox is None:
            raise RuntimeError("this store has no default inbox")
        return self._inbox


class FakeNamespace:
    def __init__(self, *stores: FakeStore) -> None:
        self.Stores = list(stores)


def store(display_name: str, *folder_names: str, inbox: str | None = None) -> FakeStore:
    folders = [FakeFolder(n) for n in folder_names]
    root = FakeFolder(display_name, *folders)
    match = next((f for f in folders if f.Name == inbox), None)
    return FakeStore(display_name, root, match)


def test_store_is_found_by_its_exact_display_name() -> None:
    from arbitrium.ingestion.outlook_mapi import find_store

    ns = FakeNamespace(store("zgody@firma.pl"), store("you@firma.pl"))

    assert find_store(ns, "you@firma.pl").DisplayName == "you@firma.pl"


def test_store_matching_ignores_case_and_padding() -> None:
    from arbitrium.ingestion.outlook_mapi import find_store

    ns = FakeNamespace(store("Zgody@Firma.pl"))

    assert find_store(ns, "  zgody@firma.pl ").DisplayName == "Zgody@Firma.pl"


def test_store_can_be_named_by_a_fragment() -> None:
    from arbitrium.ingestion.outlook_mapi import find_store

    ns = FakeNamespace(store("Zgody - Dostawcy (zgody@firma.pl)"))

    assert find_store(ns, "zgody@firma.pl").DisplayName.startswith("Zgody")


def test_an_exact_match_beats_a_loose_one() -> None:
    from arbitrium.ingestion.outlook_mapi import find_store

    ns = FakeNamespace(store("Archiwum zgody@firma.pl"), store("zgody@firma.pl"))

    assert find_store(ns, "zgody@firma.pl").DisplayName == "zgody@firma.pl"


def test_an_unknown_store_error_lists_what_is_available() -> None:
    from arbitrium.ingestion.outlook_mapi import find_store

    ns = FakeNamespace(store("zgody@firma.pl"))

    with pytest.raises(LookupError, match="zgody@firma.pl"):
        find_store(ns, "nie-ma@firma.pl")


def test_no_folder_means_the_store_default_inbox() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    target = store("zgody@firma.pl", "Skrzynka odbiorcza", "Wyslane", inbox="Skrzynka odbiorcza")

    assert find_folder(target, None).Name == "Skrzynka odbiorcza"


def test_inbox_is_recognised_by_name_when_the_store_offers_no_default() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    # Shared and delegated stores routinely refuse GetDefaultFolder.
    target = store("zgody@firma.pl", "Wyslane", "Skrzynka odbiorcza")

    assert find_folder(target, "").Name == "Skrzynka odbiorcza"


def test_a_store_with_no_inbox_at_all_says_so() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    with pytest.raises(LookupError, match="no inbox"):
        find_folder(store("Archiwum", "2025", "2026"), None)


def test_a_nested_folder_path_is_walked() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    inbox = FakeFolder("Skrzynka odbiorcza", FakeFolder("Dostawcy"))
    target = FakeStore("zgody@firma.pl", FakeFolder("root", inbox))

    assert find_folder(target, "Skrzynka odbiorcza/Dostawcy").Name == "Dostawcy"


def test_either_path_separator_works() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    inbox = FakeFolder("Inbox", FakeFolder("Suppliers"))
    target = FakeStore("zgody@firma.pl", FakeFolder("root", inbox))

    assert find_folder(target, r"Inbox\Suppliers").Name == "Suppliers"


def test_folder_names_match_case_insensitively() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    target = FakeStore("zgody@firma.pl", FakeFolder("root", FakeFolder("Dostawcy")))

    assert find_folder(target, "dostawcy").Name == "Dostawcy"


def test_an_unknown_folder_error_lists_what_is_available() -> None:
    from arbitrium.ingestion.outlook_mapi import find_folder

    target = FakeStore("zgody@firma.pl", FakeFolder("root", FakeFolder("Dostawcy")))

    with pytest.raises(LookupError, match="Dostawcy"):
        find_folder(target, "Zgody")
