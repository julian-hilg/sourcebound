"""The Word plugin, offline: rendering, and what survives a person's edits.

The edits are made with python-docx and plain XML, the way Word writes them; no Word is needed.
"""
from __future__ import annotations

import json
import struct
import time
import zipfile
import zlib
from pathlib import Path

import pytest

pytest.importorskip("sourcebound_word", reason="the plugin is an extra: uv sync --extra word")
import yaml
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

TEXT = """# Large moves

In June, {{result:move.share}} of days saw a large move [@W-0001, p. 3]. That is **a lot**, says @W-0001; see {{ref:tab:kinds}}.

## Why

- First reason with `code`
- Second reason, {{result:move.n}} cases [@W-0002]

1. one
2. two

A second list:

1. again one

> A quote.

: Kinds of fails {#tab:kinds}

| Kind | Share |
| --- | --- |
| Observed | 20 % |
| Bonds | 2 % |

A last paragraph with {{result:move.share}} once more and a link to [the site](https://example.org).
"""


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    """A desk project with two results, two sources, one piece and the standard Word template."""
    lake = tmp_path / "lake"
    (lake / "registry").mkdir(parents=True)
    (tmp_path / "hub.toml").write_text(f"[lake]\nroot = '{lake.as_posix()}'\n", encoding="utf-8")
    monkeypatch.setenv("SB_CONFIG", str(tmp_path / "hub.toml"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in ("SB_LAKE_ROOT", "SB_CATALOG", "SB_DATA_PATH"):
        monkeypatch.delenv(k, raising=False)
    from sourcebound import assets, config, desk as desk_mod, pieces, plugins
    config._load_hub.cache_clear()
    plugins.load(fresh=True)
    root = tmp_path / "desk1"
    desk_mod.create(root, "desk1", "Desk One")
    monkeypatch.chdir(root)
    set_results(root, {"move.share": "20%", "move.n": "1,234,567"})
    (root / "evidence" / "sources.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": "W-0001", "title": "Report on returns", "publisher": "Example Institute", "date": "2024-11-18", "url": "file:r.pdf"},
        {"id": "W-0002", "title": "Roadmap", "publisher": "Research Council", "date": "2025-06-30", "url": "https://example.org/roadmap"}]}),
        encoding="utf-8")
    assets.new_template("report", "docx")
    pieces.add(config.project(root), piece_id="p1", title="Large moves", template="report", text=TEXT)
    return root


def set_results(root: Path, values: dict) -> None:
    (root / "results").mkdir(exist_ok=True)
    (root / "results" / "results.json").write_text(json.dumps(
        {k: {"value": v, "display": v, "unit": None, "provenance": {"script": "analysis/a.py", "git": "abc1234", "data": {}}}
         for k, v in values.items()}), encoding="utf-8")


def render_piece(root: Path) -> Path:
    from sourcebound import config, render
    m = render.render("p1", "report", project=config.project(root))
    return Path(m["folder"]) / m["files"][0]


def body_paragraphs(d):
    return [p for p in d.element.body.iter(qn("w:p"))]


def find(d, text: str):
    from sourcebound_word import ooxml
    return next(p for p in body_paragraphs(d) if text in ooxml.plain(p))


def test_render_links_numbers_and_sources(desk):
    from sourcebound_word import ooxml, roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    texts = [ooxml.plain(p) for p in body_paragraphs(d)]
    assert texts[0] == "Large moves" and d.paragraphs[0].style.name == "Title"
    assert "In June, 20% of days saw a large move [1, p. 3]. That is a lot, says Example Institute [1]; see Table 1." in texts
    assert not any("{{" in t for t in texts)                    # every placeholder and the content marker are gone
    tags = [ooxml.sdt_tag(s) for s in ooxml.controls_in(d.element.body)]
    assert tags == ["sb:result:move.share", "sb:cite:W-0001|p. 3", "sb:citet:W-0001", "sb:result:move.n", "sb:cite:W-0002",
                    "sb:result:move.share", "sb:sources"]
    styles = [p.style.name for p in d.paragraphs]
    assert {"Heading 1", "List Bullet", "List Number", "Quote", "Caption"} <= set(styles)
    # each numbered list has a numbering instance of its own that starts at 1
    nums = [p._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}").get(qn("w:val")) for p in d.paragraphs if p.style.name == "List Number"]
    assert nums[0] == nums[1] != nums[2]
    assert d.tables[0].style.name == "SB Table" and [c.text for c in d.tables[0].rows[1].cells] == ["Observed", "20 %"]
    m = ooxml.read_manifest(d)
    assert (m["format"], m["target"], m["template"], m["project"]) == ("sourcebound-word", "pieces/p1", "report", "desk1")
    assert m["results"] == {"move.share": "20%", "move.n": "1,234,567"} and m["sources"]["order"] == ["W-0001", "W-0002"]
    assert m["sources"]["text"].split("\n")[1] == "[2]\tResearch Council (2025). Roadmap. https://example.org/roadmap"
    st = roundtrip.status(f)
    assert st["paragraphs"]["changed"] == st["paragraphs"]["added"] == st["paragraphs"]["deleted"] == st["stale"] == st["typed_over"] == []
    assert not roundtrip.edited(f)
    assert json.loads((f.parent / "render.json").read_text(encoding="utf-8"))["results"] == {"move.n": "1,234,567", "move.share": "20%"}


def test_status_tells_what_a_person_changed(desk):
    from sourcebound_word import roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    find(d, "A quote.").find(f".//{qn('w:t')}").text = "A better quote."                       # reworded
    last = find(d, "A last paragraph")
    d.element.body.remove(find(d, "First reason"))                                               # deleted
    new = d.add_paragraph("A sentence the person added.")                                        # added
    last.addnext(new._p)
    why, lst = find(d, "A second list:"), find(d, "again one")
    lst.addnext(why)                                                                             # moved below its list
    d.save(str(f))
    st = roundtrip.status(f)["paragraphs"]
    assert st["changed"] == [{"was": "A quote.", "now": "A better quote."}]
    assert st["added"] == ["A sentence the person added."]
    assert st["deleted"] == ["First reason with code"]
    assert st["moved"] in (["A second list:"], ["again one"])     # two neighbours swapped: either one "moved"
    assert roundtrip.edited(f)


def test_refresh_updates_numbers_and_leaves_the_persons_text(desk):
    from sourcebound_word import ooxml, roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    controls = ooxml.controls_in(d.element.body)
    ooxml.set_sdt_text(controls[0], "one in five")                  # typed over the first 20%
    n = controls[3]                                                 # move.n: the control deleted, its text gone with it
    n.getparent().remove(n)
    find(d, "A quote.").find(f".//{qn('w:t')}").text = "My own words."
    d.save(str(f))
    set_results(desk, {"move.share": "21%", "move.n": "1,300,000"})
    st = roundtrip.status(f)
    assert st["stale"] == []                                        # one share is typed over, the other shown below
    assert st["typed_over"] == [{"tag": "sb:result:move.share", "was": "20%", "now": "one in five"}]
    assert [r["tag"] for r in st["removed_controls"]] == ["sb:result:move.n"]
    rep = roundtrip.refresh(f)
    # the control that was typed over keeps its text; the same key elsewhere in the file follows the result
    assert rep["changes"] == [{"what": "number", "key": "move.share", "from": "20%", "to": "21%"}]
    assert rep["kept"] == [{"key": "move.share", "typed": "one in five", "rendered": "20%"}]
    d2 = Document(str(f))
    texts = [ooxml.plain(p) for p in body_paragraphs(d2)]
    assert any(t.startswith("In June, one in five of days saw a large move") for t in texts)
    assert any("with 21% once more" in t for t in texts) and "My own words." in texts
    assert roundtrip.refresh(f)["changes"] == []                    # nothing left to do: the file is not written again


def test_refresh_renumbers_citations_and_regenerates_the_source_list(desk):
    from sourcebound_word import ooxml, roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    d.element.body.remove(find(d, "In June"))                       # the paragraph with both citations of W-0001
    d.save(str(f))
    rep = roundtrip.refresh(f)
    assert {"what": "citation", "key": "W-0002", "from": "[2]", "to": "[1]"} in rep["changes"]
    d2 = Document(str(f))
    src = next(s for s in d2.element.body.iter(qn("w:sdt")) if ooxml.sdt_tag(s) == "sb:sources")
    assert ooxml.plain(src) == "[1]\tResearch Council (2025). Roadmap. https://example.org/roadmap"
    # a source list the person edited is theirs until they ask for a new one
    ooxml.set_sdt_text(src, "My own list")
    d2.save(str(f))
    assert "edited by hand" in roundtrip.refresh(f)["note"]
    assert roundtrip.status(f)["sources_list"]["edited"]
    assert roundtrip.refresh(f, sources=True)["changes"][-1]["what"] == "source list"


def test_a_source_list_word_moved_into_a_paragraph_is_still_the_source_list(desk):
    """Typing next to a one-line source list makes Word turn the block control into one inside the paragraph."""
    from sourcebound import pieces
    from sourcebound_word import ooxml, roundtrip
    pieces.update("p1", text="# Large moves\n\nOne source [@W-0001].\n\nAnother [@W-0002].\n")
    f = render_piece(desk)
    d = Document(str(f))
    body = d.element.body
    block = next(s for s in body.iter(qn("w:sdt")) if ooxml.sdt_tag(s) == "sb:sources")
    first = block.find(qn("w:sdtContent")).find(qn("w:p"))
    host = d.add_paragraph()                                        # what Word writes: <w:p><w:sdt>runs</w:sdt><w:r>typed</w:r></w:p>
    block.addprevious(host._p)
    for extra in block.find(qn("w:sdtContent")).findall(qn("w:p"))[1:]:
        extra.getparent().remove(extra)
    for r in list(first.iter(qn("w:r"))):
        block.find(qn("w:sdtContent")).append(r)
    first.getparent().remove(first)
    host._p.append(block)
    host.add_run(" My remark.")
    body.remove(find(d, "One source"))                              # and the first citation is gone
    d.save(str(f))
    st = roundtrip.status(f)
    assert st["sources_list"] == {"present": True, "edited": True, "expected": True}
    assert st["paragraphs"]["added"] == ["My remark."] and st["paragraphs"]["deleted"] == ["One source [@W-0001]."]
    rep = roundtrip.refresh(f, sources=True)
    assert rep["changes"][-1]["what"] == "source list"
    d2 = Document(str(f))
    src = next(s for s in d2.element.body.iter(qn("w:sdt")) if ooxml.sdt_tag(s) == "sb:sources")
    assert ooxml.plain(src) == "[1]\tResearch Council (2025). Roadmap. https://example.org/roadmap"
    assert ooxml.plain(src.getparent()).endswith(" My remark.")


def test_pull_writes_markdown_next_to_the_source_and_never_over_it(desk):
    from sourcebound_word import ooxml, roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    p = find(d, "A last paragraph")
    p.find(f".//{qn('w:t')}").text = "The closing paragraph with "
    new = d.add_paragraph()
    new.add_run("Added ")
    new.add_run("in bold").bold = True
    new.add_run(".")
    p.addnext(new._p)
    d.save(str(f))
    before = (desk / "pieces" / "p1" / "text.md").read_text(encoding="utf-8")
    rep = roundtrip.pull(f)
    out = desk / "pieces" / "p1" / "p1.from-word.md"
    assert Path(rep["written"]) == out and (desk / "pieces" / "p1" / "text.md").read_text(encoding="utf-8") == before
    md = out.read_text(encoding="utf-8")
    # what was not touched comes back exactly as it was written
    assert md.startswith("# Large moves\n\nIn June, {{result:move.share}} of days saw a large move [@W-0001, p. 3]. That is **a lot**, says @W-0001;")
    assert "- First reason with `code`\n- Second reason, {{result:move.n}} cases [@W-0002]" in md
    assert ": Kinds of fails {#tab:kinds}\n\n| Kind | Share |" in md
    # what was edited is converted from the file, with the links intact
    assert "The closing paragraph with {{result:move.share}} once more and a link to [the site](https://example.org)." in md
    assert "Added **in bold**." in md and "Sources" not in md
    assert (rep["changed"], rep["added"]) == (1, 1) and any(line.startswith("+Added") for line in rep["diff"])


def test_tracked_changes_are_read_as_accepted(desk):
    from sourcebound_word import ooxml, roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    p = find(d, "A quote.")
    run = p.find(qn("w:r"))
    # Word's markup for "A quote." -> "A sharp quote." with tracking on: an insertion and a deletion
    ins = OxmlElement("w:ins")
    r1 = OxmlElement("w:r")
    t1 = OxmlElement("w:t")
    t1.text = "A sharp quote."
    r1.append(t1)
    ins.append(r1)
    dele = OxmlElement("w:del")
    r2 = OxmlElement("w:r")
    t2 = OxmlElement("w:delText")
    t2.text = "A quote."
    r2.append(t2)
    dele.append(r2)
    run.addprevious(ins)
    run.addprevious(dele)
    p.remove(run)
    d.save(str(f))
    st = roundtrip.status(f)
    assert st["paragraphs"]["changed"] == [{"was": "A quote.", "now": "A sharp quote."}]
    assert st["tracked_changes"] == {"insertions": 1, "deletions": 1}
    assert "> A sharp quote." in Path(roundtrip.pull(f)["written"]).read_text(encoding="utf-8")


def as_template(src: Path, dest: Path, *, macros: bool) -> None:
    """The same package with the content type of a .dotx (or a .dotm with a macro part), as Word saves one."""
    kind = ("application/vnd.ms-word.template.macroEnabledTemplate.main+xml" if macros
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml", kind.encode())
                if macros:
                    data = data.replace(b"</Types>", b'<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
            if macros and item.filename == "word/_rels/document.xml.rels":
                data = data.replace(b"</Relationships>", b'<Relationship Id="rId99" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/></Relationships>')
            zout.writestr(item, data)
        if macros:
            zout.writestr("word/vbaProject.bin", b"not a real macro project")


@pytest.mark.parametrize("suffix,macros", [(".dotx", False), (".dotm", True)])
def test_a_corporate_template_is_adopted_as_it_is(desk, tmp_path, suffix, macros):
    from sourcebound import assets, config, render
    from sourcebound_word import template
    # a "corporate" file: its own heading style, no code or source style, no content marker
    d = Document()
    d.styles.add_style("Firm Heading", 1).base_style = d.styles["Heading 1"]
    d.add_paragraph("Confidential cover page")
    d.save(str(tmp_path / "plain.docx"))
    corporate = tmp_path / f"Firm Report{suffix}"
    as_template(tmp_path / "plain.docx", corporate, macros=macros)
    with pytest.raises(ValueError):
        Document(str(corporate))                                    # python-docx alone refuses the file
    rep = template.inspect(corporate)
    assert rep["was_template"] and rep["macros"] is macros and not rep["marker"]
    assert rep["mapping"]["heading1"] == "Heading 1" and rep["mapping"]["code"] == "" and "Firm Heading" in rep["styles"]
    dest, _ = template.adopt(corporate, config.hub().registry, "firm", assets.design(None))
    assert (dest / f"template{suffix}").read_bytes() == corporate.read_bytes()          # the file itself is not changed
    cfg = yaml.safe_load((dest / "template.yaml").read_text(encoding="utf-8"))
    cfg["styles"]["heading1"] = "Firm Heading"                      # what the person edits after `sb word inspect`
    (dest / "template.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    m = render.render("p1", "firm", project=config.project(desk))
    out = Path(m["folder"]) / "p1.docx"
    d2 = Document(str(out))                                         # a plain .docx: opens without the workaround
    names = [p.style.name for p in d2.paragraphs]
    assert d2.paragraphs[0].text == "Confidential cover page" and "Firm Heading" in names and names[1] == "Title"
    assert not any("vba" in n for n in zipfile.ZipFile(out).namelist())
    cfg["styles"]["quote"] = "No Such Style"
    (dest / "template.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match="style `No Such Style` \\(role quote\\) is not in"):
        render.render("p1", "firm", project=config.project(desk))


def test_an_edited_file_is_not_overwritten_by_the_next_render(desk):
    from sourcebound_word import roundtrip
    f = render_piece(desk)
    d = Document(str(f))
    find(d, "A quote.").find(f".//{qn('w:t')}").text = "Mine."
    d.save(str(f))
    mine = f.read_bytes()
    again = render_piece(desk)
    assert again.name == "p1.rendered.docx" and f.read_bytes() == mine and not roundtrip.edited(again)


def test_a_long_key_gets_a_short_tag(desk):
    from sourcebound import pieces
    from sourcebound_word import ooxml, roundtrip
    key = "evaluation.a_very_long_result_key.with_many_parts.that_passes_the_limit_of_word"
    set_results(desk, {key: "42", "move.share": "20%", "move.n": "1"})
    pieces.update("p1", text=f"# Large moves\n\nThe answer is {{{{result:{key}}}}}.\n")
    f = render_piece(desk)
    d = Document(str(f))
    tag = ooxml.sdt_tag(ooxml.controls_in(d.element.body)[0])
    assert tag.startswith("sb:x:") and len(tag) <= 64 and ooxml.read_manifest(d)["controls"][tag]["key"] == key
    set_results(desk, {key: "43"})
    assert roundtrip.refresh(f)["changes"] == [{"what": "number", "key": key, "from": "42", "to": "43"}]
    assert f"The answer is {{{{result:{key}}}}}." in Path(roundtrip.pull(f)["written"]).read_text(encoding="utf-8")


def png(path: Path) -> None:
    """A 2 x 2 pixel PNG, written by hand (no imaging library is a dependency)."""
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x40\x60" * 2 for _ in range(2))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_a_deliverable_with_sections_figure_and_appendix(desk, tmp_path):
    from sourcebound import assets, config, render as core
    from sourcebound_word import ooxml, render, roundtrip
    png(tmp_path / "chart.png")
    p = config.project(desk)
    refs, web = core._evidence(p)
    doc = core.Document(project=p, name="paper", kind="deliverable", title="A Paper", lang="de", folder=desk / "deliverables" / "paper",
                        sections=[core.Section("01", "# Einleitung {#sec:intro}\n\nText mit {{result:move.share}} [@W-0001].\n\n"
                                               "![Die Grafik](figures/chart.png){#fig:c}\n\n![Fehlt](figures/none.pdf)\n", source="deliverables/paper/sections/01.md"),
                                  core.Section("90", "# Anhang\n\n{{table:t1}}\n\n: Die Tabelle {#tab:t}\n\nSiehe {{ref:fig:c}}, {{ref:tab:t}} und {{ref:sec:intro}}.\n",
                                               appendix=True, source="deliverables/paper/sections/90.md")],
                        meta={"subtitle": "Working Paper", "author": "A. Author"}, results={"move.share": {"display": "20 %"}},
                        tables={"t1": {"columns": ["Name", "Wert"], "rows": [["`a`", "1,5"], ["b", "–"]]}},
                        figures={"chart.png": tmp_path / "chart.png"}, references=refs, web_sources=web)
    out = tmp_path / "out"
    out.mkdir()
    f = render.render(doc, assets.template("report"), assets.design(None), out)[0]
    d = Document(str(f))
    texts = [ooxml.plain(x) for x in body_paragraphs(d)]
    assert texts[:3] == ["A Paper", "Working Paper", "A. Author 2026-11-16"[:10] + texts[2][10:]]
    assert "Abbildung 1. Die Grafik" in texts and "Tabelle 1. Die Tabelle" in texts
    assert "[none.pdf is not among the project's figures]" in texts
    assert "Siehe Abbildung 1, Tabelle 1 und Abschnitt “Einleitung”." in texts
    assert texts.index("Quellen") < texts.index("Anhang")           # the sources stand before the appendix
    assert len(d.inline_shapes) == 1 and [c.text for c in d.tables[0].rows[1].cells] == ["a", "1,5"]
    m = ooxml.read_manifest(d)
    assert m["notes"]["figures_not_shown"] == ["none.pdf"] and m["heading_shift"] == 0
    md = Path(roundtrip.pull(f, out=tmp_path / "back.md")["written"]).read_text(encoding="utf-8")
    assert md.index("<!-- section: deliverables/paper/sections/01.md -->") < md.index("# Einleitung {#sec:intro}") < md.index(
        "<!-- section: deliverables/paper/sections/90.md -->") < md.index("{{table:t1}}")


def test_the_standard_template_follows_the_design(desk, tmp_path):
    from sourcebound import assets, config
    d = assets.new_design("firm", "The Firm")
    png(d / "logo.png")
    cfg = yaml.safe_load((d / "design.yaml").read_text(encoding="utf-8"))
    cfg["colors"]["primary"], cfg["fonts"]["heading"], cfg["logo"]["file"] = "#223344", ["Firm Sans", "Arial"], "logo.png"
    (d / "design.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    folder = assets.new_template("firm-report", "docx", design_id="firm")
    spec = yaml.safe_load((folder / "template.yaml").read_text(encoding="utf-8"))
    assert (spec["kind"], spec["design"], spec["file"], spec["content_marker"]) == ("docx", "firm", "template.docx", "{{content}}")
    doc = Document(str(folder / "template.docx"))
    h1 = doc.styles["Heading 1"]
    assert str(h1.font.color.rgb) == "223344" and h1.font.name == "Firm Sans"
    assert h1.element.find(f".//{qn('w:rFonts')}").get(qn("w:asciiTheme")) is None      # or Word would use the theme's font
    assert {"SB Table", "SB Code", "SB Source"} <= {s.name for s in doc.styles}
    assert len(doc.sections[0].header._element.findall(f".//{qn('w:drawing')}")) == 1   # the logo
    assert "PAGE" in doc.sections[0].footer._element.xml
    assert [p.text for p in doc.paragraphs] == ["{{title}}", "{{subtitle}}", "{{author}}  {{date}}", "{{content}}"]


def test_twenty_pages_render_fast(desk):
    from sourcebound import config, pieces, render
    para = ("A paragraph of ordinary length with a number, {{result:move.share}}, a source [@W-0001] and some **bold** text. " * 4).strip()
    text = "# Large moves\n\n" + "\n\n".join(f"## Section {i}\n\n" + "\n\n".join([para] * 8) + "\n\n- a point\n- another point" for i in range(25))
    pieces.update("p1", text=text)
    assert len(text.split()) > 12_000                               # about twenty pages
    start = time.perf_counter()
    render.render("p1", "report", project=config.project(desk))
    took = time.perf_counter() - start
    print(f"{len(text.split())} words rendered in {took:.2f} s")
    assert took < 2.0


def store_of(f: Path) -> str:
    with zipfile.ZipFile(f) as z:
        parts = [z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("customXml/item") and "Props" not in n]
    return next((p for p in parts if "officeDocument/2006/bibliography" in p[:600]), "")


def test_cited_sources_are_in_words_own_store(desk):
    """References > Manage Sources lists what the text cites; the citations stay as rendered."""
    f = render_piece(desk)
    store = store_of(f)
    assert store.count("<b:Source>") == 2 and "<b:Tag>W0001</b:Tag>" in store and "<b:Year>2024</b:Year>" in store
    assert "<b:Corporate>Research Council</b:Corporate>" in store and "<b:URL>https://example.org/roadmap</b:URL>" in store
    assert 'StyleName="IEEE"' in store                                   # numbered, as the template's source list
    with zipfile.ZipFile(f) as z:
        assert "CITATION" not in z.read("word/document.xml").decode("utf-8")
    from sourcebound_word import ooxml
    assert ooxml.read_manifest(Document(str(f)))["notes"]["word_sources"] == {"mode": "store", "in_store": 2}


def test_a_template_can_ask_for_citation_fields_or_for_no_store(desk):
    from sourcebound import assets
    from sourcebound_word import ooxml, roundtrip
    cfg = Path(assets.template("report")["folder"]) / "template.yaml"
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    doc["sources"] = {**(doc.get("sources") or {}), "word": "fields"}
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    f = render_piece(desk)
    with zipfile.ZipFile(f) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert ' CITATION W0001 \\p "3" \\l 1033 ' in xml and " CITATION W0001 \\n \\l 1033 " in xml and xml.count("<w:citation/>") == 3
    d = Document(str(f))                                                # the text a reader sees is unchanged, and so is the round trip
    assert "saw a large move [1, p. 3]. That is a lot, says Example Institute [1]; see Table 1." in ooxml.plain(find(d, "In June"))
    assert roundtrip.status(f)["paragraphs"]["changed"] == [] and not roundtrip.edited(f)
    d.element.body.remove(find(d, "In June"))
    d.save(str(f))
    assert {"what": "citation", "key": "W-0002", "from": "[2]", "to": "[1]"} in roundtrip.refresh(f)["changes"]
    with zipfile.ZipFile(f) as z:
        assert " CITATION W0002 " in z.read("word/document.xml").decode("utf-8")      # still a field after the refresh
    doc["sources"]["word"] = "off"
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    f.unlink()
    assert "<b:Source>" not in store_of(render_piece(desk))        # the template's own (empty) store is left alone
