"""The slides plugin, offline. Layout tests need a Chromium and are skipped without one."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("sourcebound_linkedin", reason="the plugin is an extra: uv sync --extra linkedin")
import yaml

from sourcebound import assets, config, plugins, render
from sourcebound_linkedin import browser, deck, post, slides

DECK = {
    "deck": {"title": "Test deck", "lang": "en", "prefix": "t"},
    "slides": [
        {"title": "Large moves occur more often than a normal curve predicts",
         "blocks": [{"type": "bars", "name": "Share of days", "unit": "in %", "max": 20,
                     "groups": [{"label": "By value", "rows": [{"label": "Observed", "value": "{{result:move.obs}}", "text": "about {{result:move.obs}}", "hi": True},
                                                               {"label": "Government bonds", "value": 2}]}]},
                    {"type": "comments", "items": [{"head": "Primary market", "text": "The tails are heavier [@W-0001]."}]}],
         "source": "[@W-0001]; @W-0002"},
        {"title": "Sources", "blocks": [{"type": "sources", "items": "auto"}]},
    ],
}


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    """A desk project with one piece, two sources and one recorded result, in its own data root."""
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
    main(["piece", "add", "A post", "--id", "post", "--template", "slides-test"])
    (p / "pieces" / "post" / "text.md").write_text("# A post\n\nLarge moves occur [@W-0001]. The share is {{result:move.obs}} %.\n\n#FX #Markets\n", encoding="utf-8")
    (p / "pieces" / "post" / "slides.yaml").write_text(yaml.safe_dump(DECK, sort_keys=False), encoding="utf-8")
    main(["template", "new", "slides-test", "--kind", "slides"])
    return p


def doc_of(p: Path, data: dict | None = None):
    if data is not None:
        (p / "pieces" / "post" / "slides.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return render.from_piece(config.project(p), "post")


def test_plugin_registers_renderer_command_and_scaffold(desk):
    reg = plugins.load()
    assert reg.renderers["slides"].plugin == "linkedin" and "linkedin" in reg.commands and "slides" in reg.scaffolds
    t = assets.template("slides-test")
    assert t["kind"] == "slides" and (t["width"], t["height"]) == (1080, 1350)
    assert {f.name for f in Path(t["folder"]).iterdir()} >= {"template.yaml", "slides.html.j2", "slides.css", "layout.js"}


def test_numbers_and_sources_are_resolved(desk):
    doc = doc_of(desk)
    out = deck.prepare(doc.data["slides"], doc, assets.template("slides-test"), assets.design())
    first = out["slides"][0]
    row = first["blocks"][0]["groups"][0]["rows"][0]
    assert (row["value"], row["text"], row["pct"]) == (15.0, "about 15", 60.0)        # the value is the number, the text its display
    assert first["blocks"][0]["groups"][0]["rows"][1]["text"] == "2"
    assert first["source"] == "Example Institute, Report on returns; Research Council"          # [@key] names the work, @key the publisher
    assert first["blocks"][1]["items"][0]["text"] == "The tails are heavier (Example Institute 2024)."
    items = out["slides"][1]["blocks"][0]["items"]                                      # `auto`: every source the piece cites
    assert items == [{"text": "Example Institute: Report on returns", "where": "example.org"}, {"text": "Research Council: Roadmap", "where": "example.com"}]
    assert deck.alt_text(first).startswith("Large moves occur more often than a normal curve predicts. Share of days, in %: By value: Observed about 15, Government bonds 2. Primary market")


def test_checks_without_a_browser(desk):
    design = assets.design()
    assert deck.problems(DECK, doc_of(desk), design) == []
    bad = copy.deepcopy(DECK)
    rows = bad["slides"][0]["blocks"][0]["groups"][0]["rows"]
    rows[0]["value"] = "{{result:not.recorded}}"
    rows[1].update(value=25, hi=True)
    bad["slides"][0]["source"] = "[@W-0009]"
    bad["slides"].append({"title": "", "blocks": [{"type": "pie"}]})
    bad["slides"].append({"title": "No source line", "blocks": [{"type": "gantt", "ticks": ["T", "T+1"], "rows": [{"label": "a", "span": 3}]}]})
    bad["slides"].append({"title": "A timeline", "source": False, "blocks": [{"type": "day", "events": [{"pos": 140, "time": "17:00"}]}]})
    found = "\n".join(deck.problems(bad, doc_of(desk), design))
    for expected in ("result not.recorded is used but not recorded", "source W-0009 is cited but not registered",
                     "slide 1, bars: every row needs a `value` that is a number", "slide 3: needs a title",
                     "slide 3, block 1: `type` must be one of", "slide 4: an exhibit needs a source line",
                     "start + span + ext must be whole numbers within the 2 ticks", "`pos` is a position on the axis from 0 to 100"):
        assert expected in found, expected
    two = copy.deepcopy(DECK)
    two["slides"][0]["blocks"][0]["groups"][0]["rows"][1]["hi"] = True
    assert "more than one highlighted row in a group" in "\n".join(deck.problems(two, doc_of(desk), design))
    assert deck.problems(two, doc_of(desk), {**design, "charts": {**design["charts"], "highlight_one": False}}) == []
    with pytest.raises(ValueError, match="more than one highlighted row"):          # the core runs the check before rendering
        doc_of(desk, two)
        render.render("post", "slides-test", project=config.project(desk))


def test_design_becomes_css_variables(desk, tmp_path):
    design = assets.design()
    css, allowed, missing = slides.tokens({**design, "folder": str(tmp_path), "fonts": {**design["fonts"], "files": ["House-Light.otf"],
                                           "faces": [{"weight": 600, "local": ["House Medium"]}]}})
    assert "--c-primary: #1f3a5f;" in css and "--p-2: #0b84c6;" in css and "--w-medium: 600;" in css
    assert '--f-body: "SB Design Face", "Source Sans 3"' in css and 'src: local("House Medium")' in css
    assert missing == ["House-Light.otf"] and "font-weight: 300" not in css        # a file that is not there adds no face
    assert slides.mix("#000000", "#ffffff", 0.5) == "#808080" and set(allowed) >= {"#1f3a5f", "#ffffff", slides.mix(design["colors"]["ink"], "#ffffff", 0.12)}
    with pytest.raises(ValueError, match="not a hex colour"):
        slides.tokens({**design, "colors": {**design["colors"], "primary": "navy"}})
    html, prepared, _ = slides.build_html(doc_of(desk), assets.template("slides-test"), design)
    assert "--w: 1080px; --h: 1350px;" in html and 'style="width:60.0%"' in html and "Source: Example Institute, Report on returns" in html
    assert "<script" in html and "{{result:" not in html and "&lt;script" not in html


def test_post_text_limits_and_preview(desk):
    doc = doc_of(desk)
    text = post.post_text(doc)
    assert text == "Large moves occur [1]. The share is 15 %.\n\nSources:\n1. Example Institute: Report on returns\n\n#FX #Markets\n"
    assert post.hashtags(text) == ["#FX", "#Markets"]
    assert post.visible_part("a\nb\nc\nd") == ("a\nb\nc", True) and post.visible_part("short") == ("short", False)
    assert post.visible_part("word " * 100)[0].__len__() <= post.VISIBLE
    assert post.check("post", config.project(desk)) == ([], ["the slides are not rendered yet: sb render <piece> --template <slides template>"])
    (desk / "pieces" / "post" / "text.md").write_text("x " * 1600 + "#a #b #c #d #e #f\n", encoding="utf-8")
    errs, warns = post.check("post", config.project(desk))
    assert errs == ["the text has 3218 characters; LinkedIn takes 3000"] and any("6 hashtags" in w for w in warns)
    assert any("first line has" in w for w in warns)


def test_without_a_browser_only_the_page_is_written(desk, monkeypatch, capsys):
    monkeypatch.setenv("SB_CHROMIUM", str(desk / "no-such-browser"))
    assert browser.find() is None
    m = render.render("post", "slides-test", project=config.project(desk))
    out = Path(m["folder"])
    assert m["files"] == ["layout.json", "preview.json", "t.html"]
    assert any("No Chromium browser was found" in n for n in m["notes"])          # a note, printed once by `sb render`
    assert "No Chromium" not in capsys.readouterr().out
    assert json.loads((out / "layout.json").read_text(encoding="utf-8"))["browser"] is None
    pv = json.loads((out / "preview.json").read_text(encoding="utf-8"))
    assert pv["slides"][0]["file"] is None and pv["document"] is None and pv["characters"] == len(pv["text"])
    with pytest.raises(FileNotFoundError, match="has no images"):
        post.bundle("post", project=config.project(desk))


needs_browser = pytest.mark.skipif(browser.find() is None, reason="no Chromium browser on this machine")


@needs_browser
def test_render_writes_images_pdf_preview_and_bundle(desk):
    m = render.render("post", "slides-test", project=config.project(desk))
    out = Path(m["folder"])
    assert m["files"] == ["layout.json", "preview.json", "t.html", "t_carousel.pdf", "t_slide_1.png", "t_slide_2.png"]
    assert m["results"] == {"move.obs": "15"} and m["sources"] == ["W-0001"]
    png = (out / "t_slide_1.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) == (2160, 2700)
    assert (out / "t_carousel.pdf").read_bytes()[:5] == b"%PDF-"
    layout = json.loads((out / "layout.json").read_text(encoding="utf-8"))
    assert layout["problems"] == [] and layout["browser"]
    page = (out / "t.html").read_text(encoding="utf-8")
    assert "<script>" not in page                                   # the measured page is the photographed page
    pv = json.loads((out / "preview.json").read_text(encoding="utf-8"))
    assert [s["file"] for s in pv["slides"]] == ["t_slide_1.png", "t_slide_2.png"] and pv["document"] == "t_carousel.pdf"
    assert (pv["channel"], pv["limit"], pv["width"], pv["height"], pv["more"]) == ("linkedin", 3000, 1080, 1350, True)
    dest = post.bundle("post", project=config.project(desk))
    assert sorted(f.name for f in dest.iterdir()) == ["README.txt", "alt-texts.txt", "post.txt", "t_carousel.pdf", "t_slide_1.png", "t_slide_2.png"]
    assert (dest / "post.txt").read_text(encoding="utf-8") == pv["text"] and "sb piece set post --status published" in (dest / "README.txt").read_text(encoding="utf-8")
    assert post.check("post", config.project(desk)) == ([], [])
    (desk / "results" / "results.json").write_text(json.dumps({"move.obs": {"value": 16.0, "display": "16", "unit": "%", "provenance": {}}}), encoding="utf-8")
    assert "shows older values of move.obs" in post.check("post", config.project(desk))[1][0]


@needs_browser
def test_an_overfull_slide_is_refused(desk):
    data = copy.deepcopy(DECK)
    data["slides"][0]["title"] = "A title that goes on and on " * 6
    data["slides"][0]["blocks"] = [
        {"type": "day", "name": "Too many events", "events": [{"pos": p, "time": f"{p}:00", "what": "An event with a long description"} for p in (10, 12, 14, 16, 18)]},
        {"type": "bullets", "items": ["A bullet that fills the slide. " * 6] * 9},
        {"type": "kpis", "items": [{"n": "1,234,567,890,123 EUR", "t": "far too wide"}] * 4},
    ]
    data["slides"][0]["source"] = False
    doc_of(desk, data)
    with pytest.raises(ValueError) as e:
        render.render("post", "slides-test", project=config.project(desk))
    text = str(e.value)
    assert "nothing was photographed" in text
    for expected in ("slide 1, slide: the title runs to", "too tall for the slide", "overlaps a neighbour on both sides of the axis", "is wider than its box"):
        assert expected in text, expected
    out = desk / "pieces" / "post" / "render" / "slides-test"
    assert not list(out.glob("*.png")) and json.loads((out / "layout.json").read_text(encoding="utf-8"))["problems"]


@needs_browser
def test_safe_corrections_are_applied_and_reported(desk):
    data = copy.deepcopy(DECK)
    data["deck"].update(width=1080, height=1080)
    data["slides"][0]["title"] = "Corrections"
    data["slides"][0]["blocks"] = [
        {"type": "bars", "max": 100, "rows": [{"label": "A category with a rather long name indeed, longer than the column", "value": 100, "text": "100 % of instructions", "hi": True},
                                              {"label": "Short", "value": 3, "text": "3 %"}]},
        {"type": "day", "events": [{"pos": 0, "time": "09:00", "what": "The market opens for trading"}, {"pos": 12, "time": "10:00", "what": "A second event close by"},
                                   {"pos": 100, "time": "17:30", "what": "Close", "accent": True}]},
    ]
    data["slides"][0]["source"] = "@W-0001"
    doc_of(desk, data)
    m = render.render("post", "slides-test", project=config.project(desk))
    layout = json.loads((Path(m["folder"]) / "layout.json").read_text(encoding="utf-8"))
    said = " | ".join(r["what"] for r in layout["remedies"])
    assert layout["problems"] == [] and (layout["width"], layout["height"]) == (1080, 1080)
    assert "label column widened to" in said and "moved inside its bar" in said and "moved below the axis" in said
    png = (Path(m["folder"]) / "t_slide_1.png").read_bytes()
    assert (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) == (2160, 2160)


@needs_browser
def test_a_colour_outside_the_design_is_refused(desk):
    t = Path(assets.template("slides-test")["folder"])
    (t / "slides.css").write_text((t / "slides.css").read_text(encoding="utf-8") + "\n.title { color: #ff00aa; }\n")
    with pytest.raises(ValueError, match="colour #ff00aa is not in the design"):
        render.render("post", "slides-test", project=config.project(desk))


def test_references_and_amounts_do_not_break_across_lines(desk):
    nb = " "
    assert deck.keep_together("Honorarberater (§ 34h), §§ 34f, Art. 5 Nr. 3") == f"Honorarberater (§{nb}34h), §§{nb}34f, Art.{nb}5 Nr.{nb}3"
    assert deck.keep_together("1.800 € and 44 %, 5 Mrd. €, EUR 20") == f"1.800{nb}€ and 44{nb}%, 5{nb}Mrd.{nb}€, EUR{nb}20"
    assert deck.keep_together("2 children in 2024") == "2 children in 2024"           # a number without a unit stays as it is
    data = copy.deepcopy(DECK)
    data["slides"][0]["title"] = "Advisers under § 34h earn 44 % more"
    data["slides"][0]["blocks"][0]["groups"][0]["rows"][1]["label"] = "Bonds (§ 34f)"
    doc = doc_of(desk, data)
    out = deck.prepare(doc.data["slides"], doc, assets.template("slides-test"), assets.design())
    assert out["slides"][0]["title"] == f"Advisers under §{nb}34h earn 44{nb}% more"
    assert out["slides"][0]["blocks"][0]["groups"][0]["rows"][1]["label"] == f"Bonds (§{nb}34f)"
    assert out["slides"][0]["blocks"][0]["max"] == 20                                # numbers are not touched
    assert nb not in deck.alt_text(out["slides"][0])                                  # alt text stays plain


def test_kpis_wrap_after_three_and_four_go_in_two_rows(desk):
    def columns(n, width=1080, height=1350):
        data = copy.deepcopy(DECK)
        data["deck"].update(width=width, height=height)
        data["slides"][0]["blocks"] = [{"type": "kpis", "items": [{"n": f"{i}.800 €", "t": "a number"} for i in range(n)]}]
        html, _, _ = slides.build_html(doc_of(desk, data), assets.template("slides-test"), assets.design())
        return html.split('class="kpis" style="grid-template-columns:repeat(')[1].split(",")[0], html.count('class="kpi rs"')
    assert columns(3) == ("3", 1) and columns(4) == ("2", 2) and columns(5) == ("3", 2) and columns(6) == ("3", 2)
    assert columns(4, 1080, 1080) == ("2", 2) and columns(4, 1920, 1080) == ("4", 1)


def test_missing_fonts_are_named_by_family_and_weight():
    faces = [{"family": slides.ALIAS, "weight": "400", "local": ["House"], "ok": False},
             {"family": slides.ALIAS, "weight": "700", "local": ["House-Bold"], "ok": False},
             {"family": "House", "weight": "400", "local": ["House"], "ok": False},
             {"family": "House", "weight": "700", "local": ["House-Bold"], "ok": False},
             {"family": "House-Bold", "weight": "400 700", "local": ["House-Bold"], "ok": False},
             {"family": "Serif Face", "weight": "400 700", "local": ["Serif Face"], "ok": False},
             {"family": "Loaded", "weight": "400", "local": ["Loaded"], "ok": True}]
    design = {"fonts": {"body": ["House", "sans-serif"], "heading": ["Inter Display", "sans-serif"]}}
    fonts = {slides.ALIAS: False, "House": False, "Inter Display": False, "Helvetica": True}
    assert slides.missing_typefaces(faces, fonts, design) == ["House 400", "House-Bold 700", "Serif Face", "Inter Display"]
    assert slides.missing_typefaces([], {"Inter Display": True}, design) == []


def test_bundle_steps_follow_the_language_and_the_slide_count():
    v = dict(pdf="t_carousel.pdf", first="t_slide_1.png", last="t_slide_3.png", piece="p", chars=10, limit=3000, n=3,
             template="x", design="y", at="2026-11-17")
    de, en = post.steps("de", **v), post.steps("en", **v)
    assert de.startswith("So wird der Beitrag gepostet") and "t_carousel.pdf" in de and "Zeichen" in de
    assert en.startswith("How to post this") and post.steps("fr", **v) == en and post.steps(None, **v) == en
    one = post.steps("de", **{**v, "pdf": None, "n": 1, "last": "t_slide_1.png"})
    assert "Das Bild hinzufügen" in one and "Dokument" not in one


@needs_browser
def test_a_one_slide_deck_is_a_single_image(desk, capsys):
    data = copy.deepcopy(DECK)
    data["slides"] = data["slides"][:1]
    doc_of(desk, data)
    m = render.render("post", "slides-test", project=config.project(desk))
    out = Path(m["folder"])
    assert m["files"] == ["layout.json", "preview.json", "t.html", "t_slide_1.png"]          # no carousel PDF
    assert 'class="pg"' not in (out / "t.html").read_text(encoding="utf-8")                # no page counter
    assert json.loads((out / "preview.json").read_text(encoding="utf-8"))["document"] is None
    assert not any("one slide" in w for w in post.check("post", config.project(desk))[1])
    (desk / "pieces" / "post" / "piece.yaml").write_text(
        (desk / "pieces" / "post" / "piece.yaml").read_text(encoding="utf-8").replace("lang: en", "lang: de"), encoding="utf-8")
    data["deck"]["lang"] = "de"
    doc_of(desk, data)
    render.render("post", "slides-test", project=config.project(desk))
    readme = (post.bundle("post", project=config.project(desk)) / "README.txt").read_text(encoding="utf-8")
    assert readme.startswith("So wird der Beitrag gepostet") and "Das Bild hinzufügen: t_slide_1.png" in readme
    assert capsys.readouterr().out.count("missing fonts") == 0                                # notes are printed by `sb render`, not here


@needs_browser
def test_a_grown_block_is_spread_and_an_empty_slide_is_reported(desk):
    data = copy.deepcopy(DECK)
    data["slides"][0]["blocks"] = [{"type": "bars", "grow": True, "name": "Two bars", "max": 20,
                                    "rows": [{"label": "A", "value": 10, "hi": True}, {"label": "B", "value": 5}]}]
    data["slides"].insert(1, {"title": "Little on this slide", "source": "@W-0001",
                              "blocks": [{"type": "kpis", "items": [{"n": "1.800 €", "t": "one"}, {"n": "44 %", "t": "two"},
                                                                    {"n": "540 €", "t": "three"}, {"n": "300 €", "t": "four"}]}]})
    doc_of(desk, data)
    m = render.render("post", "slides-test", project=config.project(desk))
    layout = json.loads((Path(m["folder"]) / "layout.json").read_text(encoding="utf-8"))
    assert layout["problems"] == []
    assert any(r["slide"] == 1 and "spread over the height" in r["what"] for r in layout["remedies"])
    page = (Path(m["folder"]) / "t.html").read_text(encoding="utf-8")
    assert 'class="track" style="height:' in page                                        # bars got thicker
    # two bars cannot fill a slide even when grown (the limits leave space); the kpis and the sources slide are thin too
    assert [w["slide"] for w in layout["warnings"]] == [1, 2, 3]
    assert all("% of the content area is empty" in w["what"] for w in layout["warnings"])
    assert any(n.startswith("slide 2: about ") for n in m["notes"])
