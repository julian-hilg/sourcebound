"""Figures cut out of a registered PDF: `sb figure crop W-0007 --page 4 --box 52,8,98,45`.

A report often holds charts that a piece may show again as they are (the publisher's own, or one's
own report in the house style).  The crop is taken from the archived copy of the source, so it can
always be traced back: the PNG lands in the piece's folder, and an `image` block names it (`src`)
and where it came from (`from: "W-0007, p. 4"`).

`--box` is left, top, right, bottom in percent of the page.  `--grid` writes the whole page with
a 10 % grid instead, to read the box off.  The page is drawn by poppler's `pdftoppm`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class CropError(RuntimeError):
    pass


def parse_box(text: str) -> tuple[float, float, float, float]:
    try:
        l, t, r, b = (float(v) for v in str(text).replace(";", ",").split(","))
    except ValueError:
        raise CropError("--box is four numbers: left,top,right,bottom in percent of the page (e.g. 52,8,98,45)") from None
    if not (0 <= l < r <= 100 and 0 <= t < b <= 100):
        raise CropError("--box: 0 <= left < right <= 100 and 0 <= top < bottom <= 100 (percent of the page)")
    return l, t, r, b


def _page_png(pdf: bytes, page: int, dpi: int, out_dir: Path) -> Path:
    exe = shutil.which("pdftoppm")
    if exe is None:
        raise CropError("pdftoppm (poppler) is not installed: it draws the PDF page. Install poppler-utils and try again.")
    src = out_dir / "source.pdf"
    src.write_bytes(pdf)
    prefix = out_dir / "page"
    done = subprocess.run([exe, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", str(src), str(prefix)],
                          capture_output=True, text=True)
    png = out_dir / "page.png"
    if done.returncode != 0 or not png.is_file():
        raise CropError(f"pdftoppm could not draw page {page}: {(done.stderr or done.stdout).strip() or 'no output'}")
    return png


def pages(pdf: bytes) -> int:
    import io

    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(pdf)).pages)


def trim_margin(im, *, white: int = 248, keep: int = 0):
    """`im` without the page's white margin around the figure (rows and columns that are all white)."""
    from PIL import ImageChops
    rgb = im.convert("RGB")
    bg = rgb.point(lambda v: 255 if v >= white else 0).convert("L")      # white -> 255, anything else -> 0
    box = ImageChops.invert(bg).getbbox()                                 # the box of everything not white
    if not box:
        return im
    l, t, r, b = box
    return im.crop((max(0, l - keep), max(0, t - keep), min(im.width, r + keep), min(im.height, b + keep)))


def crop(pdf: bytes, page: int, box: tuple[float, float, float, float], out: Path, *, dpi: int = 300, trim: bool = True) -> tuple[int, int]:
    """Cut `box` (percent of the page) out of `page` and write it as PNG, without the white page margin
    around it (`trim`). Returns its size in pixels."""
    from PIL import Image
    n = pages(pdf)
    if not 1 <= page <= n:
        raise CropError(f"--page {page}: the PDF has {n} pages")
    with tempfile.TemporaryDirectory() as tmp:
        with Image.open(_page_png(pdf, page, dpi, Path(tmp))) as im:
            w, h = im.size
            l, t, r, b = box
            part = im.crop((round(w * l / 100), round(h * t / 100), round(w * r / 100), round(h * b / 100)))
            if trim:
                part = trim_margin(part)
            out.parent.mkdir(parents=True, exist_ok=True)
            part.save(out, "PNG", optimize=True)
            return part.size


def grid(pdf: bytes, page: int, out: Path, *, dpi: int = 110) -> tuple[int, int]:
    """The whole page with a 10 % grid and its numbers, to read a `--box` off."""
    from PIL import Image, ImageDraw
    n = pages(pdf)
    if not 1 <= page <= n:
        raise CropError(f"--page {page}: the PDF has {n} pages")
    with tempfile.TemporaryDirectory() as tmp:
        with Image.open(_page_png(pdf, page, dpi, Path(tmp))) as im:
            im = im.convert("RGB")
            w, h = im.size
            d = ImageDraw.Draw(im)
            for k in range(0, 101, 5):
                x, y = round(w * k / 100), round(h * k / 100)
                strong = k % 10 == 0
                colour = (220, 30, 120) if strong else (240, 170, 205)
                d.line([(x, 0), (x, h)], fill=colour, width=2 if strong else 1)
                d.line([(0, y), (w, y)], fill=colour, width=2 if strong else 1)
                if strong:
                    d.text((x + 3, 3), str(k), fill=(220, 30, 120))
                    d.text((3, y + 3), str(k), fill=(220, 30, 120))
            out.parent.mkdir(parents=True, exist_ok=True)
            im.save(out, "PNG")
            return w, h


# ------------------------------------------------------------------ a project's own figures: figures/<name>.yaml
#
#     figures/zulage.yaml        one figure: what it shows, where the numbers come from, the chart block
#     figures/zulage.png         drawn by `sb figure render` in a design's chart style (also .svg)
#     figures/zulage.figure.json what was drawn: values of the results used, sources, design, size, when
#
# A figure is one block in the vocabulary of a deck (bars, columns, line, gantt, timeline/day, windows),
# so a chart drawn for a report looks like the same chart on a slide. Numbers are recorded results
# (`{{result:key}}` as a value) or numbers typed from a source named under `source:`.

SIZES = {                                  # px at 96 dpi; text_px is the label size
    "report": {"width": 605, "height": 340, "text_px": 9.3},    # 16 cm wide in a report, 7 pt labels
    "slide": {"width": 920, "height": 520, "text_px": 22},      # the content width of a 1080 px slide
    "square": {"width": 920, "height": 920, "text_px": 22},
}
NUMERIC = {"value", "values", "max", "min", "pos", "start", "width", "span", "ext", "height", "y"}
LAYOUT = {"pos", "start", "width", "span", "ext", "height"}      # positions and sizes, not data
_RESULT = re.compile(r"\{\{result:([^}]+)\}\}")
_EXAMPLES = {
    "bars": {"type": "bars", "rows": [{"label": "A", "value": 3.2, "hi": True}, {"label": "B", "value": 1.4}]},
    "columns": {"type": "columns", "items": [{"label": "2024", "value": 1.2}, {"label": "2025", "value": 1.6, "hi": True}]},
    "line": {"type": "line", "x": ["2023", "2024", "2025"], "series": [{"label": "Reihe", "values": [1.0, 1.4, 1.9], "hi": True}]},
    "timeline": {"type": "timeline", "events": [{"pos": 0, "time": "01.2026", "what": "Beginn"},
                                                {"pos": 100, "time": "01.2027", "what": "Start", "accent": True}]},
    "gantt": {"type": "gantt", "ticks": ["T", "T+1", "T+2"], "rows": [{"label": "Schritt", "span": 2, "hi": True}]},
    "windows": {"type": "windows", "months": ["Jan", "Feb", "Mär"], "windows": [{"label": "Fenster", "start": 10, "width": 40}]},
}
_HEAD = ("# A figure: one chart, drawn by `sb figure render` in the design's chart style.\n"
         "# chart: the block (fields as in `sb template guide` for slides); a value may be {{result:key}}.\n"
         "# source: where typed numbers come from, e.g. \"[@W-0001]\"; size: report | slide | square,\n"
         "# or {width, height, text_px} in px. design: empty = the project's piece_defaults, else the default.\n")


class FigureError(ValueError):
    pass


def figure_dir(project) -> Path:
    return project.root / "figures"


def figure_files(project) -> list[Path]:
    d = figure_dir(project)
    return sorted(f for f in d.glob("*.yaml") if f.is_file()) if d.is_dir() else []


def new_figure(project, name: str, kind: str = "bars", *, title: str = "") -> Path:
    """A starting figure file, to fill in: an example block of the type, the size, the source line."""
    import yaml
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,60}", name):
        raise FigureError("figure name: lowercase letters, digits, - and _ (e.g. zulage)")
    if kind not in _EXAMPLES:
        raise FigureError(f"--type must be one of {', '.join(_EXAMPLES)}")
    f = figure_dir(project) / f"{name}.yaml"
    if f.exists():
        raise FigureError(f"figures/{name}.yaml exists")
    body = {"title": title or name, "source": "", "note": "", "size": "report", "design": "", "chart": _EXAMPLES[kind]}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_HEAD + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return f


def _resolve(node, results: dict, used: set, missing: set, key=None):
    if isinstance(node, dict):
        return {k: _resolve(v, results, used, missing, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, results, used, missing, key) for v in node]
    if not isinstance(node, str):
        return node
    whole = _RESULT.fullmatch(node.strip())
    if whole and key in NUMERIC:
        k = whole.group(1).strip()
        if k not in results or not isinstance(results[k].get("value"), (int, float)):
            missing.add(k)
            return None
        used.add(k)
        return results[k]["value"]

    def text(m):
        k = m.group(1).strip()
        if k not in results:
            missing.add(k)
            return f"?{k}"
        used.add(k)
        return str(results[k]["display"])
    return _RESULT.sub(text, node)


def _typed_numbers(node, key=None) -> bool:
    """A data number typed into the block (not a result, not a position): the figure needs a source line."""
    if isinstance(node, dict):
        return any(_typed_numbers(v, k) for k, v in node.items())
    if isinstance(node, list):
        return any(_typed_numbers(v, key) for v in node)
    return key in NUMERIC - LAYOUT and isinstance(node, (int, float)) and not isinstance(node, bool)


def load_figure(project, name: str) -> dict:
    import yaml
    f = figure_dir(project) / f"{name.removesuffix('.yaml')}.yaml"
    if not f.is_file():
        raise FigureError(f"no figures/{name}.yaml (sb figure new {name} --type bars)")
    try:
        spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise FigureError(f"figures/{f.name} is not valid YAML: {e}")
    if not isinstance(spec, dict) or not isinstance(spec.get("chart"), dict):
        raise FigureError(f"figures/{f.name}: `chart:` (the block) is missing")
    return {**spec, "name": f.stem, "file": f}


def check_figure(project, name: str) -> list[str]:
    """What stops this figure from being drawn, in sentences."""
    from . import charts, results
    spec = load_figure(project, name)
    used, missing = set(), set()
    block = _resolve(spec["chart"], results.load(project), used, missing)
    out = [f"result {k} is used but not recorded" for k in sorted(missing)]
    if not missing:
        out += charts.check(block)
    if _typed_numbers(spec["chart"]) and not str(spec.get("source") or "").strip():
        out.append("the chart holds typed numbers: name their source (source: \"[@W-0001]\") or use {{result:key}}")
    size = spec.get("size") or "report"
    if isinstance(size, str) and size not in SIZES:
        out.append(f"size must be one of {', '.join(SIZES)}, or width, height and text_px")
    return out


def render_figure(project, name: str, *, design_id: str | None = None, fmt: str = "png") -> dict:
    """Draw figures/<name>.yaml; returns the manifest written beside the image."""
    import json
    from datetime import datetime, timezone
    from . import assets, charts, render, results
    spec = load_figure(project, name)
    problems = check_figure(project, name)
    if problems:
        raise FigureError(f"figures/{spec['name']}.yaml not drawn:\n  " + "\n  ".join(problems))
    if fmt not in ("png", "svg"):
        raise FigureError("format: png or svg")
    current = results.load(project)
    used, missing = set(), set()
    block = _resolve(spec["chart"], current, used, missing)
    for k in ("name", "unit"):                     # the caption belongs to the document, not into the image
        block.pop(k, None)
    size = spec.get("size") or "report"
    size = dict(SIZES[size]) if isinstance(size, str) else {**SIZES["report"], **size}
    design = assets.design(design_id or spec.get("design") or (project.meta.get("piece_defaults") or {}).get("design") or None)
    out = figure_dir(project) / f"{spec['name']}.{fmt}"
    notes: list[str] = []
    charts.render(block, design=design, width_px=int(size["width"]), height_px=int(size["height"]), out=out,
                  lang="de" if project.german else "en", text_px=size.get("text_px"), notes=notes)
    manifest = {"format": "sourcebound-figure", "version": 1, "figure": spec["name"], "file": out.name,
                "title": spec.get("title") or spec["name"], "design": design["id"], "size": size,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "results": {k: current[k]["display"] for k in sorted(used)},
                "sources": render.cited(str(spec.get("source") or "")), "notes": notes}
    (figure_dir(project) / f"{spec['name']}.figure.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                                                     encoding="utf-8")
    return {**manifest, "path": str(out)}


def figure_list(project) -> list[dict]:
    """Every figure file with its state: not drawn, drawn, stale (older numbers) or changed since drawn."""
    import json
    from . import render, results
    current = results.load(project)
    out = []
    for f in figure_files(project):
        m = f.parent / f"{f.stem}.figure.json"
        if not m.exists():
            out.append({"figure": f.stem, "title": "", "state": "not drawn", "stale": []})
            continue
        man = json.loads(m.read_text(encoding="utf-8"))
        stale = render.stale(man, current)
        older = f.stat().st_mtime > m.stat().st_mtime + 1
        state = "stale" if stale else "changed since drawn" if older else "drawn"
        out.append({"figure": f.stem, "title": man.get("title", ""), "state": state, "stale": stale, "file": man.get("file"),
                    "design": man.get("design"), "at": man.get("at")})
    return out
