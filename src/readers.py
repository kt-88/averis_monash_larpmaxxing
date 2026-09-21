"""Format-dispatching attachment reader: txt/pdf/docx/xlsx -> plain text."""
import io
import re
from pathlib import Path

import docx
import openpyxl
import pdfplumber
import pypdfium2
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.cache import BudgetExceeded
from src.llm import llm_vision_text


class UnreadableAttachment(Exception):
    """Raised when an attachment yields no usable text (empty, corrupt, garbled, or a scanned image)."""


class ScannedDocument(UnreadableAttachment):
    """An image-only scan. It is never trusted for an automatic decision, so the email goes to a person.
    `text` is a vision-model transcript, kept only so the reviewer has something to read (empty if unavailable)."""

    def __init__(self, message: str, text: str = ""):
        super().__init__(message)
        self.text = text


def _looks_garbled(text: str) -> bool:
    if not text.strip():
        return True
    bad = sum(1 for c in text if c == "\ufffd" or (ord(c) < 32 and c not in "\n\r\t"))
    return bad / len(text) > 0.02

def _clean(cell) -> str:
    if cell is None:
        return ""
    s = re.sub(r"\s*\n\s*", " | ", str(cell).strip())
    return re.sub(r"[ \t]+", " ", s)


def row_to_line(cells) -> str | None:
    raw = [_clean(c) for c in cells]
    filled = [c for c in raw if c]
    if not filled:
        return None
    # merged cells repeat their text, so drop consecutive duplicates
    dedup = [c for i, c in enumerate(filled) if i == 0 or c != filled[i - 1]]
    if len(dedup) == 1:
        return f"{dedup[0]}:" if len(raw) > 1 else dedup[0]   # "Consignee | (empty)" -> "Consignee:"
    return f"{dedup[0]}: {' '.join(dedup[1:])}"


def read_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")  # Chinese PDFs often use GB18030/files with chinese text


def _outside(bboxes):
    """Keep only characters that are NOT inside any table box."""
    def keep(obj):
        if obj.get("object_type") != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= x <= x1 and t <= y <= b for x0, t, x1, b in bboxes)
    return keep


def _pdf_text(pdf) -> str:
    lines = []
    for page in pdf.pages:
        tables = page.find_tables()
        # use_text_flow: read the text in the order the PDF draws it. Sorting by position instead shuffles the letters
        # when a long label and its value overlap on the page ("...Consignee" + "CERIEX" -> "ConsCigEnReIEeX").
        body = page.filter(_outside([t.bbox for t in tables])).extract_text(use_text_flow=True) or ""
        lines += [l for l in body.splitlines() if l.strip()]
        for t in tables:
            for row in t.extract():
                if (ln := row_to_line(row)):
                    lines.append(ln)
    return "\n".join(lines)


VISION_PROMPT = ("Transcribe this shipping document exactly as 'Label: Value' lines, one per line. "
                 "Do not guess. Write ??? for any text you cannot read.")
SCAN_NOTE = "[Transcribed from a scanned image by Gemini. Check it against the original.]"
_ENOUGH_TEXT = 40   # letters and digits; fewer than this means the PDF has no real text layer


def _has_text(text: str) -> bool:
    return len(re.sub(r"\W", "", text)) >= _ENOUGH_TEXT


def _pdfium_text(data: bytes) -> str:
    """Text via PDFium (the engine inside Chrome). It repairs a broken cross-reference index that pdfminer refuses,
    and still cannot open a file that is genuinely corrupt (that raises, and the file is reported unreadable)."""
    pdf = pypdfium2.PdfDocument(data)
    try:
        return "\n".join(page.get_textpage().get_text_range().replace("\r\n", "\n") for page in pdf)
    finally:
        pdf.close()


def _page_images(pdf) -> list[bytes]:
    pages = []
    for page in pdf.pages[:3]:
        buf = io.BytesIO()
        page.to_image(resolution=150).original.save(buf, format="PNG")
        pages.append(buf.getvalue())
    return pages


def read_pdf(data: bytes) -> str:
    """Text of a PDF. A damaged file pdfminer refuses is retried with PDFium. An image-only scan is never trusted for
    an automatic decision: it is transcribed (for the reviewer) and raised as ScannedDocument, so the email is escalated."""
    pages: list[bytes] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = _pdf_text(pdf)
            if not _has_text(text):
                pages = _page_images(pdf)
    except Exception:
        text = _pdfium_text(data)                              # raises if the file is truly corrupt
    if _has_text(text):
        return text
    if not pages:
        raise UnreadableAttachment("PDF has no pages or no readable text")
    transcript = ""
    try:
        transcript = llm_vision_text(VISION_PROMPT, pages).strip()
    except Exception:                                          # incl. an exhausted budget: the email is escalated anyway
        pass
    raise ScannedDocument("scanned image (no text layer): a person must check it",
                          text=f"{SCAN_NOTE}\n{transcript}" if transcript else "")


def read_docx(data: bytes) -> str:
    d = docx.Document(io.BytesIO(data))
    lines = []
    for child in d.element.body.iterchildren():          # walk the body in document order
        if child.tag.endswith("}p"):                     # a paragraph
            t = Paragraph(child, d).text.strip()
            if t:
                lines.append(t)
        elif child.tag.endswith("}tbl"):                 # a table
            for row in Table(child, d).rows:
                if (ln := row_to_line([c.text for c in row.cells])):
                    lines.append(ln)
    return "\n".join(lines)



def read_xlsx(data: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            if (ln := row_to_line(list(row))):
                lines.append(ln)
    return "\n".join(lines)


READERS = {".txt": read_txt, ".pdf": read_pdf, ".docx": read_docx, ".xlsx": read_xlsx}


def read_attachment(path: str, data: bytes) -> str:
    """Return plain text for an attachment, or raise UnreadableAttachment."""
    if not data:
        raise UnreadableAttachment("empty (0-byte) file")
    reader = READERS.get(Path(path).suffix.lower())
    if reader is None:
        raise UnreadableAttachment(f"unsupported format: {Path(path).suffix}")
    try:
        text = reader(data)
    except (UnreadableAttachment, BudgetExceeded):
        raise                                            # already the right kind of error
    except Exception as e:                               # corrupt docx/xlsx/pdf etc.
        raise UnreadableAttachment(f"cannot parse {Path(path).name}: {e}") from e
    if _looks_garbled(text):
        raise UnreadableAttachment("no text layer or garbled content")
    return text
