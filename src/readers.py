"""Format-dispatching attachment reader: txt/pdf/docx/xlsx -> plain text."""
import io
from pathlib import Path


class UnreadableAttachment(Exception):
    """Raised when an attachment yields no usable text (empty, scanned, corrupt, garbled)."""


def _looks_garbled(text: str) -> bool:
    if not text.strip():
        return True
    bad = sum(1 for c in text if c == "\ufffd" or (ord(c) < 32 and c not in "\n\r\t"))
    return bad / len(text) > 0.02


def read_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def read_pdf(data: bytes) -> str:
    import pypdf
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        raise UnreadableAttachment(f"cannot parse PDF: {e}") from e


def read_docx(data: bytes) -> str:
    import docx
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise UnreadableAttachment(f"cannot parse DOCX: {e}") from e
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(c.text.replace("\n", "; ") for c in row.cells))
    return "\n".join(lines)


def read_xlsx(data: bytes) -> str:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        raise UnreadableAttachment(f"cannot parse XLSX: {e}") from e
    lines = []
    for ws in wb:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


READERS = {".txt": read_txt, ".pdf": read_pdf, ".docx": read_docx, ".xlsx": read_xlsx}


def read_attachment(path: str, data: bytes) -> str:
    """Return plain text for an attachment, or raise UnreadableAttachment."""
    if not data:
        raise UnreadableAttachment("empty (0-byte) file")
    reader = READERS.get(Path(path).suffix.lower())
    if reader is None:
        raise UnreadableAttachment(f"unsupported format: {Path(path).suffix}")
    text = reader(data)
    if _looks_garbled(text):
        raise UnreadableAttachment("no text layer or garbled content")
    return text
