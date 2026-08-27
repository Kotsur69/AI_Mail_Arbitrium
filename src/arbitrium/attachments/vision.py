"""What a scan says, read by a vision model.

A supplier who prints the request, signs it, scans it and sends back a PDF has
answered as clearly as anyone. Until now the pipeline could only report that it
could not read them -- correct, and useless to the person who then had to open
every one by hand.

Two rules shape everything here.

**The vision model transcribes; it never judges.** It turns pixels into text,
and that text goes through the same classifier, the same grounding check and
the same review rules as a body or a .docx. A second model deciding "zgoda" on
its own would break the one invariant this project actually rests on: the model
classifies a single message, and Python does everything else.

**Transcription is not as trustworthy as a text layer, and the pipeline says
so.** `is_grounded` cannot catch a misread character, because the quote and the
source are then both the transcription -- a confident circle. So an attachment
read this way carries `via_vision`, and review.py queues the message for a
person to confirm. That is still an enormous improvement on the status quo: the
reviewer gets the transcription, a proposed status and a quote to check,
instead of a filename and a shrug.

Nothing is written to disk and nothing leaves the machine. The images go from
Outlook's store, through memory, to a model on localhost.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Sequence

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_VISION_MODEL = "qwen2.5-vl-32b-instruct"

# A signed consent runs a page or two. Past this it is a catalogue or a scanned
# contract annex, and every page is another second of a 32B model's time.
MAX_SCAN_PAGES = 4

# The gate that keeps signature logos away from the vision model. On the one
# real mailbox measured, 13 of 15 attachments were signature images; at a second
# or more each, sending those would pad the run to learn they say the company
# name. A scanned page is large in both directions -- the short-edge floor is
# what rejects a wide letterhead banner that clears the long one.
MIN_SCAN_LONG_EDGE = 600
MIN_SCAN_SHORT_EDGE = 400

# Qwen2.5-VL reads a page comfortably at this size, and 300 DPI A4 is 2480x3508
# -- four times the pixels for no more legibility, paid for in image tokens.
MAX_EDGE = 1600
JPEG_QUALITY = 80

# Generous: a dense scanned page of Polish prose runs well past a thousand.
MAX_TRANSCRIPT_TOKENS = 2000

# A vision model is slower than a text one, and a full page is its slow case.
REQUEST_TIMEOUT_SECONDS = 300

SYSTEM_PROMPT = """Jestes narzedziem OCR. Przepisujesz tekst z obrazow dokumentow.

Nie oceniasz, nie streszczasz, nie interpretujesz i nie odpowiadasz na pytania
zawarte w dokumencie. Twoim jedynym zadaniem jest wierne przepisanie tekstu."""

TRANSCRIBE_PROMPT = """Przepisz caly tekst widoczny na obrazach, doslownie.

ZASADY:
1. Zachowaj oryginalna pisownie, interpunkcje i polskie znaki diakrytyczne.
2. Zachowaj uklad: kolejne akapity w kolejnych liniach, tabele wiersz po wierszu.
3. Nie dodawaj komentarzy, naglowkow ani wyjasnien od siebie.
4. Nie tlumacz i nie poprawiaj tekstu, nawet jesli zawiera bledy.
5. Fragment nieczytelny oznacz jako [nieczytelne]. Nie zgaduj jego tresci.
6. Jesli na obrazach nie ma zadnego tekstu, nie pisz nic."""


def measure(data: bytes) -> tuple[int, int] | None:
    """The image's pixel dimensions, or None when it is not an image at all.

    Absent rather than zero: "we could not decode this" and "this is a 0x0
    image" have to stay distinguishable, and only one of them is a real file.
    """
    from PIL import Image  # noqa: PLC0415 - imaging imported where it is used

    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except Exception:  # noqa: BLE001 - a corrupt image must not end the run
        return None


def looks_like_scan(data: bytes) -> bool:
    """Whether this image is a document page rather than a signature logo.

    Decided on dimensions, not on filename or byte size, because a logo saved at
    low compression can outweigh a clean bitonal scan of a full page.
    """
    size = measure(data)
    if size is None:
        return False
    width, height = size
    return min(width, height) >= MIN_SCAN_SHORT_EDGE and max(width, height) >= MIN_SCAN_LONG_EDGE


def page_images(pdf: bytes, max_pages: int = MAX_SCAN_PAGES) -> list[bytes]:
    """The page images inside a PDF that has no text to extract.

    A scan *is* an image in a PDF wrapper, so the pixels are already there --
    pypdf hands them over without rasterising anything. That is why this needs
    no Poppler, no Ghostscript and no PyMuPDF: no page is ever rendered, only
    unwrapped.

    Letterhead logos are filtered out here rather than sent, for the same reason
    signature images never reach the model.
    """
    from pypdf import PdfReader  # noqa: PLC0415 - parser imported where it is used

    try:
        reader = PdfReader(BytesIO(pdf))
        pages = list(reader.pages)[:max_pages]
    except Exception:  # noqa: BLE001 - a malformed PDF is a reason, not a crash
        return []

    found: list[bytes] = []
    for page in pages:
        try:
            embedded = list(page.images)
        except Exception:  # noqa: BLE001 - one unreadable page must not lose the rest
            continue
        found.extend(image.data for image in embedded if looks_like_scan(image.data))
    return found


def shrink(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """Bring an oversized scan down to a size worth sending.

    An image already small enough is returned untouched: re-encoding it would
    cost quality on the one thing the model has to read, and buy nothing.
    """
    from PIL import Image  # noqa: PLC0415

    size = measure(data)
    if size is None or max(size) <= max_edge:
        return data

    try:
        with Image.open(BytesIO(data)) as image:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)
            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
            return buffer.getvalue()
    except Exception:  # noqa: BLE001 - send the original rather than nothing
        return data


def data_uri(data: bytes) -> str:
    """The image as an inline data URI, which is how a local endpoint takes it.

    Inline rather than a URL because there is no server to serve it from and,
    more to the point, a supplier's signed consent should not become a file on
    disk just to be read.
    """
    from PIL import Image  # noqa: PLC0415

    try:
        with Image.open(BytesIO(data)) as image:
            mime = Image.MIME.get(image.format or "", "image/png")
    except Exception:  # noqa: BLE001
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class VisionReader:
    """Turns page images into text, using a vision model on the local endpoint.

    Separate from `Classifier` on purpose. They are different weights doing
    different jobs, and LM Studio serves them under different ids -- collapsing
    them into one object would have meant one model field standing for two
    things, and no way to run the cheap classifier against the expensive OCR.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_VISION_MODEL,
        client: Any | None = None,
        max_pages: int = MAX_SCAN_PAGES,
    ) -> None:
        self.model = model
        self.max_pages = max_pages
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI  # noqa: PLC0415

            self._client = OpenAI(
                base_url=base_url, api_key="lm-studio", timeout=REQUEST_TIMEOUT_SECONDS
            )

    def transcribe(self, images: Sequence[bytes]) -> str:
        """Read every page of one document in a single call.

        Together rather than page by page: the second page of a scanned consent
        is often just a signature block, and a model shown that alone will
        transcribe a name where the document as a whole says agreement.
        """
        if not images:
            return ""

        parts: list[dict[str, Any]] = [{"type": "text", "text": TRANSCRIBE_PROMPT}]
        parts.extend(
            {"type": "image_url", "image_url": {"url": data_uri(shrink(page))}}
            for page in images[: self.max_pages]
        )

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": parts},
            ],
            temperature=0.0,
            seed=7,
            max_tokens=MAX_TRANSCRIPT_TOKENS,
        )
        return (response.choices[0].message.content or "").strip()
