"""Text of a PDF: `pdftotext` (poppler) where it is installed, else pypdf (pure Python, always there).

pdftotext keeps the layout better (columns, tables); pypdf needs nothing installed, which matters on
Windows, where poppler is rarely present. The result says which one read the file.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def engine() -> str:
    return "pdftotext" if shutil.which("pdftotext") else "pypdf"


def text(pdf: bytes | Path, *, page: int | None = None) -> tuple[str, str]:
    """(text, engine). `page` counts from 1; None reads the whole file."""
    if engine() == "pdftotext":
        with tempfile.TemporaryDirectory() as tmp:          # a named file: Windows cannot reopen an open one
            f = Path(tmp) / "source.pdf"
            f.write_bytes(pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes())
            args = ["pdftotext", "-layout", *(["-f", str(page), "-l", str(page)] if page else []), str(f), "-"]
            out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
            return out.stdout, "pdftotext"
    import io

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf) if isinstance(pdf, bytes) else str(pdf))
    pages = reader.pages if page is None else reader.pages[page - 1: page]
    return "\n\f".join((p.extract_text() or "") for p in pages), "pypdf"
