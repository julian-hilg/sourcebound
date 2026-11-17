"""PDF text without poppler, and a clear message when a viewer holds a rendered file."""
from __future__ import annotations

import io

import pytest


def _pdf(text: str) -> bytes:
    """A one-page PDF with `text`, written by hand (no PDF library needed to make it)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def test_pdf_text_without_pdftotext(monkeypatch):
    from sourcebound import pdftext
    monkeypatch.setattr(pdftext.shutil, "which", lambda name: None)
    text, engine = pdftext.text(_pdf("Settlement fails ETF"))
    assert engine == "pypdf" and "Settlement fails ETF" in text
    assert pdftext.text(_pdf("Seite eins"), page=1)[0].strip() == "Seite eins"


def test_a_file_held_by_a_viewer_is_named(tmp_path, monkeypatch):
    from sourcebound import plugins, render

    class Doc:
        kind, name, meta, folder, sections, data, results, text = "piece", "p1", {}, tmp_path, [], {}, {}, ""

    def held(doc, tpl, design, out):
        raise PermissionError(13, "in use", str(out / "deck.pdf"))

    reg = plugins.load(fresh=True)
    reg.renderers["testkind"] = plugins.Renderer("testkind", held)
    monkeypatch.setattr(render, "document", lambda target, project=None: Doc())
    monkeypatch.setattr(render.assets, "template", lambda i: {"kind": "testkind", "id": i})
    monkeypatch.setattr(render.assets, "design", lambda i: {"id": "d"})
    try:
        with pytest.raises(RuntimeError, match=r"deck\.pdf is open in another program"):
            render.render("p1", "t")
    finally:
        plugins.load(fresh=True)
