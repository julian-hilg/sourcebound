"""The pptx plugin: a deck as a PowerPoint file in a master, with the built-in (neutral) design."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("sourcebound_pptx", reason="the plugin is an extra: uv pip install -e plugins/pptx")
import yaml
from pptx import Presentation

from sourcebound import assets, charts, config, plugins, render
from sourcebound_pptx import master as m
from sourcebound_pptx import slides
from sourcebound_pptx.style import Measure

DECK = {
    "deck": {"title": "Test deck", "lang": "en", "prefix": "t", "tracker": "Test series"},
    "slides": [
        {"layout": "cover", "eyebrow": "Market note", "title": "Fat tails in daily returns", "sub": "What a normal curve misses", "note": "November 2026"},
        {"title": "Large moves occur more often than a normal curve predicts",
         "blocks": [{"type": "bars", "name": "Share of days", "unit": "in %", "max": 20, "grow": True,
                     "groups": [{"label": "By value", "rows": [{"label": "Observed", "value": "{{result:move.obs}}", "text": "about {{result:move.obs}}", "hi": True},
                                                               {"label": "Normal curve", "value": 2}]}]},
                    {"type": "comments", "items": [{"head": "Tails", "text": "The tails are heavier [@W-0001]."}, {"head": "Size", "text": "And 44 % larger."}]}],
         "source": "[@W-0001]; @W-0002"},
        {"title": "Three numbers and a table",
         "blocks": [{"type": "kpis", "items": [{"n": "{{result:move.obs}} %", "t": "of days"}, {"n": "1.800 €", "t": "per year"}, {"n": "3", "t": "markets"}]},
                    {"type": "table", "name": "Markets", "columns": ["Market", "Days", "Share"], "rows": [["EUR/USD", "250", "15 %"], ["GBP/USD", "250", "12 %"]]}],
         "source": "@W-0002"},
        {"title": "What it means",
         "blocks": [{"type": "bullets", "items": ["Risk models understate losses.", "Options are priced for it."]},
                    {"type": "quote", "text": "Tails are where the money is.", "by": "A trader"},
                    {"type": "callout", "n": "15 %", "text": "of days move more than two standard deviations."}],
         "source": False},
        {"title": "Sources", "blocks": [{"type": "sources", "items": "auto"}]},
    ],
}


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    """A desk with one piece, two sources and one recorded result, and a pptx template from the scaffold."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in ("SB_CONFIG", "SB_CATALOG", "SB_DATA_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SB_LAKE_ROOT", str(tmp_path / "lake"))
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.toml").write_text("[lake]\nroot = '%s'\n" % (tmp_path / "lake").as_posix(), encoding="utf-8")
    config._load_hub.cache_clear()
    plugins.load(fresh=True)
    monkeypatch.chdir(hub)
    from sourcebound.cli import main
    main(["new", "desk", "--title", "A desk", "--kind", "desk"])
    p = hub / "desk"
    monkeypatch.chdir(p)
    (p / "evidence" / "sources.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": "W-0001", "title": "Report on returns", "url": "https://www.example.org/report", "publisher": "Example Institute", "date": "2024-11-18"},
        {"id": "W-0002", "title": "Roadmap", "url": "https://example.com/roadmap", "publisher": "Research Council", "date": "2025-06-30"}]}))
    (p / "results" / "results.json").write_text(json.dumps({"move.obs": {"value": 15.0, "display": "15", "unit": "%", "provenance": {}}}), encoding="utf-8")
    main(["piece", "add", "A post", "--id", "post", "--template", "pptx-test"])
    (p / "pieces" / "post" / "text.md").write_text("# A post\n\nLarge moves occur [@W-0001].\n", encoding="utf-8")
    write_deck(p, DECK)
    main(["template", "new", "pptx-test", "--kind", "pptx"])
    yield p
    plugins.load(fresh=True)


def write_deck(p: Path, data: dict) -> None:
    (p / "pieces" / "post" / "slides.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def doc_of(p: Path):
    return render.from_piece(config.project(p), "post")


def texts(shape) -> str:
    return "\n".join(par.text for par in shape.text_frame.paragraphs) if shape.has_text_frame else ""


def test_plugin_and_starting_template(desk):
    reg = plugins.load()
    assert reg.renderers["pptx"].plugin == "pptx" and "pptx" in reg.scaffolds and "pptx" in reg.checks
    t = assets.template("pptx-test")
    assert t["kind"] == "pptx" and (t["width"], t["height"]) == (1080, 1350)
    prs = Presentation(str(Path(t["folder"]) / "master.pptx"))
    assert round(prs.slide_width / 360000, 3) == 28.575 and [lay.name for lay in prs.slide_layouts] == ["Cover", "Content"]
    content = m.layout(prs, "Content")
    assert {ph.name for ph in content.placeholders} == {"Tracker", "Title", "Body", "Page"}
    assert m.fonts_in(prs) <= {"Source Sans 3"}                       # the design's fonts only, in theme and placeholders


def test_render_writes_editable_slides(desk):
    man = render.render("post", "pptx-test", project=config.project(desk))
    out = Path(man["folder"])
    assert "t.pptx" in man["files"] and "layout.json" in man["files"] and any(f.startswith("charts/t_s2_") for f in man["files"])
    prs = Presentation(str(out / "t.pptx"))
    assert len(prs.slides) == 5
    cover, bars, kpis, words, sources = prs.slides
    assert cover.slide_layout.name == "Cover" and bars.slide_layout.name == "Content"
    assert cover.shapes.title.text == "Fat tails in daily returns"
    assert {ph.name for ph in cover.placeholders} >= {"Eyebrow", "Subtitle", "Note"}
    assert bars.shapes.title.text == "Large moves occur more often than a normal curve predicts"
    every = "\n".join(texts(s) for s in bars.shapes)
    assert "Share of days" in every and "in %" in every and "Source: Example Institute, Report on returns; Research Council" in every
    assert "/  Test series" in every and "02 / 05" in every and "The tails are heavier (Example Institute 2024)." in every
    pics = [s for s in bars.shapes if s.shape_type == 13]
    assert len(pics) == 1 and pics[0]._element.nvPicPr.cNvPr.get("descr").startswith("Share of days, in %: By value: Observed about 15")
    kp = "\n".join(texts(s) for s in kpis.shapes)
    assert "15 %" in kp and "1.800 €" in kp                   # a number and its unit are kept together
    table = next(s for s in kpis.shapes if s.has_table).table
    assert [c.text for c in table.rows[0].cells] == ["Market", "Days", "Share"] and table.cell(1, 0).text == "EUR/USD"
    assert table.cell(1, 2).text_frame.paragraphs[0].alignment is not None
    assert "Risk models understate losses." in "\n".join(texts(s) for s in words.shapes)
    assert "Example Institute: Report on returns" in "\n".join(texts(s) for s in sources.shapes)
    for slide in prs.slides:                                         # no empty placeholder is left with its prompt
        assert all(texts(ph).strip() for ph in slide.placeholders)
    # runs carry the design's faces; bold comes from the heading face or a bold flag, never from the master
    faces = {r.font.name for s in prs.slides for sh in s.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs}
    assert faces == {"Source Sans 3"}
    layout = json.loads((out / "layout.json").read_text(encoding="utf-8"))
    assert [x["slide"] for x in layout["slides"]] == [1, 2, 3, 4, 5] and layout["chart_renderer"] == "builtin"


def test_what_does_not_fit_stops_the_render(desk):
    long = copy.deepcopy(DECK)
    long["slides"][1]["title"] = "A title that goes on and on " * 6
    long["slides"][3]["blocks"][0]["items"] = [f"Point {i} that takes a whole line of the slide to say, more or less." for i in range(30)]
    write_deck(desk, long)
    with pytest.raises(ValueError) as e:
        render.render("post", "pptx-test", project=config.project(desk))
    msg = str(e.value)
    assert "no file was written" in msg and "slide 2, title: runs to" in msg and "slide 4: the content is" in msg
    assert not list((desk / "pieces" / "post" / "render").glob("*/t.pptx"))


def test_check_before_layout(desk, tmp_path):
    doc, design = doc_of(desk), assets.design()
    t = assets.template("pptx-test")
    assert slides.check(doc, t, design) == []
    gone = tmp_path / "copy"
    shutil.copytree(t["folder"], gone)
    (gone / "master.pptx").unlink()
    assert "the master master.pptx is missing" in slides.check(doc, {**t, "folder": str(gone)}, design)[0]
    renamed = {**t, "layouts": {**t["layouts"], "content": {**t["layouts"]["content"], "name": "Inhalt"}}}
    assert any("no layout named 'Inhalt'" in p for p in slides.check(doc, renamed, design))
    assert any("is not 1080 x 1080" in p for p in slides.check(doc, {**t, "height": 1080}, design))
    assert any("colour 'nope'" in p for p in slides.check(doc, {**t, "styles": {"title": {"color": "nope"}}}, design))
    reg = plugins.load()
    plugins.Api(plugins.Plugin("firm"), reg).chart_renderer("columns-only", charts.draw, types=("columns",))
    limited = {**design, "charts": {**design["charts"], "renderer": "columns-only"}}
    assert "slide 2: bars charts are not supported in pptx yet by chart renderer `columns-only`" in slides.check(doc, t, limited)


def test_measure_breaks_lines_at_spaces_only(desk):
    meas = Measure(assets.design())
    st = {"font": "body", "size": 20, "line": 1.5}
    one = meas.width("word", st)
    assert meas.width("word word", st) > 2 * one
    assert meas.lines("1.800 € and more", st, meas.width("1.800 €", st) + 1) == ["1.800 €", "and", "more"]
    assert meas.height("a b", st, 10_000) == 30.0
    assert meas.width("ab", {**st, "caps": True}) > meas.width("ab", st)


def test_exhibits_are_numbered_only_where_the_template_asks(desk):
    from sourcebound_pptx.slides import Ctx
    design = assets.design()
    design = {**design, "charts": {**(design.get("charts") or {}), "caption": {"prefix": {"de": "Abb. ", "en": "Figure "}}}}
    deck = {"lang": "de"}
    plain = Ctx(None, {"kind": "pptx"}, design, deck)
    assert plain.fig_prefix is None and plain.tab_prefix is None          # a post: the design's Word captions do not number it
    numbered = Ctx(None, {"kind": "pptx", "numbering": {"figure": {"de": "Abb. "}, "table": {"de": "Tabelle "}}}, design, deck)
    assert (numbered.fig_prefix, numbered.tab_prefix) == ("Abb. ", "Tabelle ")
