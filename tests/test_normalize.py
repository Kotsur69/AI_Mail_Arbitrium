"""Reducing a raw mail body to just the part the sender actually wrote.

These tests pin the cutting rules themselves. They do NOT claim cutting changes
what the model decides -- measured against a ~630-character quoted block full of
consent wording, it changed no verdicts at all. The value here is context
economy and behaviour that stays predictable on threads longer than any tested.
"""

from mail_analyzer.normalize import reply_text, strip_disclaimer

REPLY = "Dzien dobry,\n\nPotwierdzamy i akceptujemy warunki.\n\nPozdrawiam\nJan Kowalski"


def test_plain_body_is_returned_unchanged() -> None:
    assert reply_text(REPLY) == REPLY


def test_polish_outlook_attribution_line_cuts_the_history() -> None:
    body = REPLY + "\n\nW dniu 4 sierpnia 2026 napisano:\n> Prosimy o wyrazenie zgody\n> na nowe warunki."

    assert reply_text(body) == REPLY


def test_english_attribution_line_cuts_the_history() -> None:
    body = REPLY + "\n\nOn Tue, 4 Aug 2026 at 10:00, Anna wrote:\n> Prosimy o wyrazenie zgody."

    assert reply_text(body) == REPLY


def test_original_message_separator_cuts_the_history() -> None:
    body = REPLY + "\n\n-----Oryginalna wiadomosc-----\nOd: Anna\nTemat: Zgoda\n\nProsimy o zgode."

    assert reply_text(body) == REPLY


def test_outlook_header_block_cuts_the_history() -> None:
    body = REPLY + "\n\n________________________________\nOd: Anna Nowak\nWyslano: 4 sierpnia 2026\nDo: dostawca\nTemat: Prosba o zgode\n\nProsimy o zgode."

    assert reply_text(body) == REPLY


def test_leading_quote_block_survives_when_there_is_no_reply_above_it() -> None:
    # Never return empty: a body that is only quoted history must still be
    # classifiable, so the caller sees the original text rather than nothing.
    body = "> Prosimy o wyrazenie zgody\n> na nowe warunki."

    assert reply_text(body) == body


def test_quoted_request_cannot_leak_into_the_reply() -> None:
    # The model tolerated leakage in testing, but the cut should still be clean.
    body = REPLY + "\n\nW dniu 4 sierpnia napisano:\n> Czy wyrazaja Panstwo zgode?"

    assert "wyrazaja" not in reply_text(body)


def test_legal_disclaimer_is_removed() -> None:
    body = REPLY + "\n\nTa wiadomosc i wszelkie zalaczone do niej pliki sa poufne i przeznaczone wylacznie dla adresata."

    assert strip_disclaimer(body).strip() == REPLY


def test_disclaimer_removal_leaves_a_clean_body_alone() -> None:
    assert strip_disclaimer(REPLY) == REPLY


def test_crlf_and_nbsp_are_normalised_away() -> None:
    body = "Dzien dobry,\r\n\r\nPotwierdzamy i akceptujemy warunki."

    out = reply_text(body)

    assert "\r" not in out
    assert " " not in out


def test_runs_of_blank_lines_collapse() -> None:
    body = "Dzien dobry,\n\n\n\n\nPotwierdzamy."

    assert reply_text(body) == "Dzien dobry,\n\nPotwierdzamy."
