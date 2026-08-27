"""Reading a scan, and knowing not to trust it as far as a text layer.

Every fixture is built in memory: Pillow draws a page-sized image and saves it
as a PDF, which is structurally what a scanner produces -- an image in a PDF
wrapper with nothing to extract text from. No checked-in binaries, so nothing
here can drift away from the parsers it exercises.

The vision model is faked throughout. What is under test is the decision of
*when* to call it, what gets sent, and what the pipeline does with the answer.
None of that needs twenty gigabytes of weights resident to verify, and a test
that did would never run in CI.
"""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image, ImageDraw

from arbitrium.attachments.base import Attachment, Kind
from arbitrium.attachments.extract import extract, extract_all
from arbitrium.attachments.vision import (
    MAX_EDGE,
    MAX_SCAN_PAGES,
    VisionReader,
    data_uri,
    looks_like_scan,
    measure,
    page_images,
    shrink,
)
from arbitrium.review import ReviewReason, review_reasons
from arbitrium.verdict import MessageVerdict

A4_AT_150DPI = (1240, 1754)
CONSENT = "Wyrazamy zgode na proponowane warunki wspolpracy."


def image_bytes(size: tuple[int, int], fmt: str = "PNG", text: str = "") -> bytes:
    """One image, drawn rather than loaded, so its dimensions are the test's."""
    img = Image.new("RGB", size, "white")
    if text:
        ImageDraw.Draw(img).text((40, 60), text, fill="black")
    buffer = BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def scan_pdf(pages: int = 1, size: tuple[int, int] = A4_AT_150DPI) -> bytes:
    """A PDF that is nothing but page images -- a scan, with no text layer."""
    sheets = [Image.new("RGB", size, "white") for _ in range(pages)]
    for sheet in sheets:
        ImageDraw.Draw(sheet).text((100, 200), CONSENT, fill="black")
    buffer = BytesIO()
    sheets[0].save(
        buffer, format="PDF", resolution=150.0, save_all=True, append_images=sheets[1:]
    )
    return buffer.getvalue()


class FakeVision:
    """The OpenAI-compatible client, faked, recording everything it was handed."""

    def __init__(self, reply: str = CONSENT) -> None:
        self.reply = reply
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def reader(reply: str = CONSENT) -> tuple[VisionReader, FakeVision]:
    client = FakeVision(reply)
    return VisionReader(client=client, model="fake-vl"), client


# --- telling a scan from a signature logo -----------------------------------
#
# This is the gate that decides whether a 32B vision model runs at all. On the
# one real mailbox measured, 13 of 15 attachments were signature logos; sending
# those to a VLM would cost seconds each to learn they say "Sp. z o.o.".


def test_a_page_sized_image_looks_like_a_scan():
    # Arrange
    page = image_bytes(A4_AT_150DPI)

    # Act / Assert
    assert looks_like_scan(page) is True


def test_a_signature_logo_does_not_look_like_a_scan():
    # Arrange
    logo = image_bytes((180, 60))

    # Act / Assert
    assert looks_like_scan(logo) is False


def test_bytes_that_are_not_an_image_at_all_are_not_a_scan():
    assert looks_like_scan(b"this is not a picture") is False


def test_measure_reports_the_dimensions_it_will_be_judged_on():
    assert measure(image_bytes((640, 480))) == (640, 480)


def test_measure_returns_none_for_something_undecodable():
    assert measure(b"\x00\x01\x02") is None


# --- getting the pixels out of a scanned PDF --------------------------------


def test_page_images_pulls_the_embedded_scan_out_of_a_pdf():
    # Arrange
    pdf = scan_pdf(pages=1)

    # Act
    images = page_images(pdf)

    # Assert
    assert len(images) == 1
    assert measure(images[0]) == A4_AT_150DPI


def test_page_images_reads_every_page_up_to_the_cap():
    # Arrange -- a consent runs a page or two; a catalogue must not be paid for.
    pdf = scan_pdf(pages=MAX_SCAN_PAGES + 3)

    # Act
    images = page_images(pdf)

    # Assert
    assert len(images) == MAX_SCAN_PAGES


def test_page_images_of_a_pdf_with_no_images_is_empty():
    assert page_images(b"%PDF-1.4 not really a pdf") == []


# --- what actually goes over the wire ---------------------------------------


def test_an_oversized_scan_is_shrunk_before_it_is_sent():
    # Arrange -- 300 DPI A4 is 2480px wide, which is tokens spent on nothing.
    huge = image_bytes((2480, 3508))

    # Act
    smaller = shrink(huge)

    # Assert
    measured = measure(smaller)
    assert measured is not None
    width, height = measured
    assert max(width, height) == MAX_EDGE
    assert width < height  # the page stays a portrait page


def test_an_image_already_small_enough_is_left_alone():
    # Arrange
    modest = image_bytes((800, 1000))

    # Act / Assert -- re-encoding a small image buys nothing and loses quality.
    assert measure(shrink(modest)) == (800, 1000)


def test_data_uri_is_something_a_vision_endpoint_will_accept():
    uri = data_uri(image_bytes((100, 100)))
    assert uri.startswith("data:image/")
    assert ";base64," in uri


def test_transcribe_sends_the_image_and_returns_what_came_back():
    # Arrange
    vision, client = reader(reply="Potwierdzamy zgode.")

    # Act
    text = vision.transcribe([image_bytes(A4_AT_150DPI)])

    # Assert
    assert text == "Potwierdzamy zgode."
    (call,) = client.calls
    assert call["model"] == "fake-vl"
    parts = call["messages"][-1]["content"]
    assert any(part.get("type") == "image_url" for part in parts)


def test_every_page_of_one_document_goes_in_a_single_call():
    # Arrange -- page 2 of a two-page consent often carries only the signature,
    # so the pages have to be read together or the answer is half a document.
    vision, client = reader()

    # Act
    vision.transcribe([image_bytes(A4_AT_150DPI), image_bytes(A4_AT_150DPI)])

    # Assert
    assert len(client.calls) == 1
    parts = client.calls[0]["messages"][-1]["content"]
    assert sum(1 for part in parts if part.get("type") == "image_url") == 2


def test_transcribing_nothing_never_calls_the_model():
    vision, client = reader()
    assert vision.transcribe([]) == ""
    assert client.calls == []


# --- the pipeline seam ------------------------------------------------------


def test_without_a_vision_reader_a_scan_still_reports_why_it_is_unreadable():
    # Arrange
    attachment = Attachment("zgoda.pdf", scan_pdf(), 4000)

    # Act
    result = extract(attachment)

    # Assert -- the old behaviour is untouched when vision is not configured.
    assert result.text == ""
    assert "wizyjnego" in (result.error or "")
    assert result.via_vision is False


def test_with_a_vision_reader_the_scan_becomes_text():
    # Arrange
    attachment = Attachment("zgoda.pdf", scan_pdf(), 40000)
    vision, client = reader(reply=CONSENT)

    # Act
    result = extract(attachment, vision=vision)

    # Assert
    assert CONSENT in result.text
    assert result.error is None
    assert result.via_vision is True
    assert len(client.calls) == 1


def test_a_scanned_image_attachment_is_read_rather_than_described():
    # Arrange -- a photographed consent arrives as a .jpg just as often as a PDF.
    attachment = Attachment("skan.jpg", image_bytes(A4_AT_150DPI, "JPEG"), 90000)
    vision, _ = reader(reply=CONSENT)

    # Act
    result = extract(attachment, vision=vision)

    # Assert
    assert result.kind is Kind.IMAGE
    assert CONSENT in result.text
    assert result.via_vision is True


def test_a_signature_logo_is_never_sent_to_the_vision_model():
    # Arrange
    attachment = Attachment("logo.png", image_bytes((180, 60)), 3000)
    vision, client = reader()

    # Act
    result = extract(attachment, vision=vision)

    # Assert -- the cheap answer stands, and no weights were spent on it.
    assert client.calls == []
    assert result.text == ""
    assert "obraz" in (result.error or "")


def test_a_pdf_that_has_a_text_layer_never_reaches_the_vision_model():
    # Arrange
    from tests.test_attachments import pdf_with_text

    attachment = Attachment("umowa.pdf", pdf_with_text("Wyrazamy zgode"), 2000)
    vision, client = reader()

    # Act
    result = extract(attachment, vision=vision)

    # Assert
    assert "zgode" in result.text
    assert client.calls == []
    assert result.via_vision is False


def test_a_vision_model_that_fails_leaves_a_reason_not_a_crash():
    # Arrange -- LM Studio with no VL model loaded is the everyday case.
    class Broken(FakeVision):
        def _create(self, **kwargs):
            raise RuntimeError("model not loaded")

    attachment = Attachment("zgoda.pdf", scan_pdf(), 40000)
    vision = VisionReader(client=Broken(), model="fake-vl")

    # Act
    result = extract(attachment, vision=vision)

    # Assert
    assert result.text == ""
    assert result.error is not None
    assert result.via_vision is False


def test_a_scan_the_model_reads_as_blank_is_reported_as_blank():
    # Arrange
    attachment = Attachment("pusty.pdf", scan_pdf(), 40000)
    vision, _ = reader(reply="   ")

    # Act
    result = extract(attachment, vision=vision)

    # Assert -- an empty page and an unreadable one must not look the same.
    assert result.text == ""
    assert result.error is not None


def test_extract_all_passes_the_reader_through():
    # Arrange
    attachments = (Attachment("zgoda.pdf", scan_pdf(), 40000),)
    vision, client = reader()

    # Act
    results = extract_all(attachments, vision=vision)

    # Assert
    assert results[0].via_vision is True
    assert len(client.calls) == 1


# --- what the reviewer is told ----------------------------------------------


def test_a_verdict_resting_on_a_transcript_is_queued_for_a_person():
    # Arrange -- grounding cannot catch a misread character, because the quote
    # and the source are both the transcription. A person confirms the scan.
    verdict = MessageVerdict(
        status="zgoda", confidence=0.9, evidence=CONSENT, rationale="Zgoda wyrazona wprost."
    )

    # Act
    reasons = review_reasons(verdict, CONSENT, from_vision=True)

    # Assert
    assert ReviewReason.VISION_TRANSCRIPT in reasons


def test_the_same_verdict_off_a_real_text_layer_is_not_queued():
    # Arrange
    verdict = MessageVerdict(
        status="zgoda", confidence=0.9, evidence=CONSENT, rationale="Zgoda wyrazona wprost."
    )

    # Act
    reasons = review_reasons(verdict, CONSENT, from_vision=False)

    # Assert
    assert reasons == []


# --- deciding whether to use it at all --------------------------------------
#
# Loading a second model is a real cost and needs a person to have loaded the
# weights, so every one of these branches is a way for a run to fail slowly.


def flags(**overrides):
    from argparse import Namespace

    return Namespace(**{"vision": False, "no_vision": False, "vision_model": None, **overrides})


def build(settings=None, **overrides):
    from analyze_mailbox import build_vision

    from arbitrium.config import AttachmentsConfig, LlmConfig, VisionConfig

    return build_vision(
        settings or VisionConfig(), LlmConfig(), flags(**overrides), AttachmentsConfig()
    )


def test_scans_are_left_unread_unless_something_asks_for_them():
    assert build() is None


def test_the_flag_turns_vision_on_without_touching_the_config_file():
    assert build(vision=True) is not None


def test_the_config_file_can_turn_vision_on_for_every_run():
    from arbitrium.config import VisionConfig

    assert build(VisionConfig(enabled=True)) is not None


def test_no_vision_overrules_a_config_file_that_enabled_it():
    from arbitrium.config import VisionConfig

    assert build(VisionConfig(enabled=True), no_vision=True) is None


def test_no_vision_overrules_the_flag_too():
    # Arrange / Act / Assert -- the flag that stops work wins over the one that
    # starts it, so a scripted command can always be made safe by appending one.
    assert build(vision=True, no_vision=True) is None


def test_vision_is_off_when_attachments_are_not_being_read_at_all():
    from analyze_mailbox import build_vision

    from arbitrium.config import AttachmentsConfig, LlmConfig, VisionConfig

    # Arrange -- --no-attachments means no file is opened; a vision model would
    # have nothing to look at, and loading it would be pure cost.
    off = AttachmentsConfig(enabled=False)

    # Act
    reader_or_none = build_vision(
        VisionConfig(enabled=True), LlmConfig(), flags(vision=True), off
    )

    # Assert
    assert reader_or_none is None


def test_the_vision_model_can_be_overridden_for_one_run():
    reader_or_none = build(vision=True, vision_model="some-other-vl")
    assert reader_or_none is not None
    assert reader_or_none.model == "some-other-vl"
