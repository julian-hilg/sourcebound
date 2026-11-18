"""sourcebound.charts: a chart block drawn as an image, checked, and the design's renderer hook."""
from __future__ import annotations

from pathlib import Path

import pytest

from sourcebound import assets, charts, plugins

DESIGN = {**assets.BASE_DESIGN, "id": "plain", "folder": None}

BLOCKS = [
    {"type": "bars", "groups": [{"label": "By value", "rows": [{"label": "ETFs", "value": 15, "hi": True}, {"label": "Bonds", "value": 2}]}]},
    {"type": "bars", "rows": [{"label": "A", "value": 3}, {"label": "B", "value": 1.5}], "max": 4},
    {"type": "columns", "items": [{"label": "2023", "value": 3}, {"label": "2024", "value": 5.5, "hi": True}]},
    {"type": "line", "x": [2020, 2021, 2022], "series": [{"label": "ETF", "values": [1, None, 3], "hi": True}, {"label": "Index", "values": [1, 2, 2.5]}],
     "refs": [{"y": 2, "label": "target"}]},
    {"type": "gantt", "ticks": ["T", "T+1", "T+2"], "rows": [{"label": "Exchange", "sub": "EU", "span": 2, "hi": True}, {"label": "Units", "span": 1, "ext": 2}]},
    {"type": "timeline", "events": [{"pos": 0, "time": "17:00", "what": "Recall deadline"}, {"pos": 100, "time": "23:59", "align": "right", "below": True, "accent": True}]},
    {"type": "windows", "months": ["Feb", "Mar"], "windows": [{"label": "Window 1", "start": 0, "width": 20, "dates": "01.-12.02."}]},
]


def png_size(path: Path) -> tuple[int, int]:
    return charts.rendered_size(path)


@pytest.fixture()
def fresh_registry():
    reg = plugins.load(fresh=True)
    yield reg
    plugins.load(fresh=True)


@pytest.mark.parametrize("block", BLOCKS, ids=[f"{b['type']}-{i}" for i, b in enumerate(BLOCKS)])
def test_every_chart_type_draws_a_png_of_the_asked_size(block, tmp_path):
    assert charts.check(block) == []
    out = charts.render(block, design=DESIGN, width_px=600, height_px=300, out=tmp_path / "c.png", lang="de", scale=2)
    assert png_size(out) == (1200, 600)


def test_svg_and_no_other_format(tmp_path):
    out = charts.render(BLOCKS[0], design=DESIGN, width_px=400, height_px=200, out=tmp_path / "c.svg", lang="en")
    assert out.read_text(encoding="utf-8").lstrip().startswith("<?xml") and "<svg" in out.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="written as .png or .svg"):
        charts.render(BLOCKS[0], design=DESIGN, width_px=400, height_px=200, out=tmp_path / "c.jpg", lang="en")


def test_check_names_what_is_wrong():
    assert charts.check({"type": "pie"})[0].startswith("`type` must be one of bars, columns, line, gantt, day, windows")
    assert "every row needs a `value`" in charts.check({"type": "bars", "rows": [{"label": "a", "value": "x"}]})[0]
    assert "`max` must be a number at least as large" in charts.check({"type": "bars", "rows": [{"label": "a", "value": 5}], "max": 4})[0]
    assert "needs one value per x position" in charts.check({"type": "line", "x": [1, 2], "series": [{"label": "s", "values": [1]}]})[0]
    assert "within the 2 ticks" in charts.check({"type": "gantt", "ticks": ["T", "T+1"], "rows": [{"span": 3}]})[0]
    assert "from 0 to 100" in charts.check({"type": "timeline", "events": [{"time": "x", "pos": 120}]})[0]
    assert "together at most 100" in charts.check({"type": "windows", "months": ["a"], "windows": [{"label": "w", "start": 90, "width": 20}]})[0]
    with pytest.raises(ValueError, match="every row needs a `value`"):
        charts.render({"type": "bars", "rows": [{"label": "a"}]}, design=DESIGN, width_px=100, height_px=100, out=Path("x.png"), lang="en")


def test_style_from_the_design():
    st = charts.style_of({**DESIGN, "charts": {**DESIGN["charts"], "gridlines": True, "panel": "#eeeeee"}})
    assert (st.strong, st.neutral, st.grid, st.paper) == ("#1f3a5f", "#c9cfd8", True, "#eeeeee")
    assert st.series(8)[6] == st.palette[0]                                   # the palette is cycled
    assert st.value("#c9cfd8", False, True) == (st.text, False) and st.value("#1f3a5f", True, True) == (st.strong, True)
    assert charts.mix("#000000", "#ffffff", 0.5) == "#808080"
    assert charts.spread([10, 11, 12], 5, 0, 100) == [10, 15, 20]


def test_a_design_names_its_renderer_and_a_plugin_draws(tmp_path, fresh_registry):
    drawn = []

    def firm(block, *, design, width_px, height_px, out, lang, text_px=None, scale=2.0):
        drawn.append((block["type"], width_px, lang, text_px))
        style = charts.style_of(design)
        style.strong = "#ff0000"
        return charts.draw(block, design=design, width_px=width_px, height_px=height_px, out=out, lang=lang, scale=1, style=style)

    api = plugins.Api(plugins.Plugin("firm"), fresh_registry)
    api.chart_renderer("firm", firm, types=("bars", "timeline"))
    design = {**DESIGN, "charts": {**DESIGN["charts"], "renderer": "firm"}}
    assert charts.supported(design) == ("bars", "day")                       # an alias counts as its type
    notes: list = []
    out = charts.render(BLOCKS[5], design=design, width_px=300, height_px=200, out=tmp_path / "t.png", lang="en", text_px=12, notes=notes)
    assert drawn == [("day", 300, "en", 12)] and png_size(out) == (300, 200) and notes == []
    with pytest.raises(charts.Unsupported, match="does not draw line charts"):
        charts.render(BLOCKS[3], design=design, width_px=300, height_px=200, out=tmp_path / "l.png", lang="en")


def test_a_missing_renderer_falls_back_with_a_note(tmp_path, fresh_registry):
    design = {**DESIGN, "charts": {**DESIGN["charts"], "renderer": "nowhere"}}
    notes: list = []
    charts.render(BLOCKS[2], design=design, width_px=200, height_px=100, out=tmp_path / "c.png", lang="en", notes=notes)
    assert len(notes) == 1 and "renderer `nowhere`, which no installed plugin provides" in notes[0]
    assert charts.renderer(design)[0] == charts.BUILTIN


def test_font_files_of_the_design_are_found_by_name(tmp_path):
    import matplotlib
    src = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "House-Bold.ttf").write_bytes(src.read_bytes())
    design = {**DESIGN, "folder": str(tmp_path), "charts": {**DESIGN["charts"], "fonts": ["fonts/House-Bold.ttf"]}}
    assert charts.design_font_files(design) == [tmp_path / "fonts" / "House-Bold.ttf"]
    assert charts.font_file("DejaVu Sans", weight=700, design=design) == tmp_path / "fonts" / "House-Bold.ttf"
    assert charts.font_file("DejaVuSans-Bold", design=design) == tmp_path / "fonts" / "House-Bold.ttf"   # the PostScript name
    assert charts.font_file("No Such Face 123", design=design) is None


def test_a_design_whose_fonts_are_not_installed_falls_back_to_sans_serif(tmp_path):
    from sourcebound import assets, charts
    design = assets.design()
    design = {**design, "fonts": {**design["fonts"], "body": ["No Such Face", "sans-serif"], "heading": ["No Such Face"], "files": []}}
    regular, strong = charts._font_props(design)
    assert regular.get_family() == ["sans-serif"] and strong.get_weight() in ("bold", 700)
    out = charts.render({"type": "bars", "rows": [{"label": "A", "value": 1}]}, design=design, width_px=400, height_px=200,
                        out=tmp_path / "c.png", lang="en")
    assert out.stat().st_size > 1000
