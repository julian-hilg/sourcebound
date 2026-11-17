"""`sb word pdf`: the converter is registered; with Word or LibreOffice on the machine, a real PDF."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("sourcebound_word")


def test_the_plugin_registers_a_docx_to_pdf_converter():
    from sourcebound import plugins
    reg = plugins.load(fresh=True)
    conv = reg.converters.get((".docx", ".pdf"))
    assert conv is not None and conv.plugin == "word"
    assert ".docx -> .pdf" in next(p for p in plugins.listing() if p["name"] == "word")["converters"]


def test_no_engine_is_a_clear_error(tmp_path, monkeypatch):
    from sourcebound_word import pdf
    f = tmp_path / "a.docx"
    f.write_bytes(b"not used")
    monkeypatch.setattr(pdf, "engines", lambda: [])
    with pytest.raises(RuntimeError, match="no PDF engine"):
        pdf.to_pdf(f)
    monkeypatch.setattr(pdf, "engines", lambda: ["libreoffice"])
    with pytest.raises(RuntimeError, match="engine word is not available"):
        pdf.to_pdf(f, engine="word")


@pytest.mark.skipif(sys.platform != "win32", reason="Word fonts are read from the Windows registry")
def test_outlined_fonts_are_those_installed_as_otf_only(tmp_path, monkeypatch):
    from sourcebound_word import pdf
    f = tmp_path / "a.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/styles.xml", '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:rFonts w:ascii="NoSuchFontXyz"/>')
    assert pdf.outlined_fonts(f) == []              # Calibri is TrueType; an unknown font is not reported


def test_a_real_pdf_where_an_engine_exists(tmp_path):
    from sourcebound_word import pdf
    if not pdf.engines():
        pytest.skip("neither Word nor LibreOffice on this machine")
    import docx
    d = docx.Document()
    d.add_heading("Titel", 1)
    d.add_paragraph("Ein Absatz.")
    src = tmp_path / "x.docx"
    d.save(src)
    rep = pdf.to_pdf(src, timeout=240)
    out = Path(rep["pdf"])
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-" and rep["engine"] in ("word", "libreoffice")
