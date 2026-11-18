"""Charts as images: one chart block, drawn in a design's chart style.

    from sourcebound import charts
    charts.check(block)                                  # problems, as a list of sentences
    charts.render(block, design=assets.design("x"), width_px=920, height_px=520,
                  out=Path("chart.png"), lang="de")      # .png or .svg

A block is a dict in the vocabulary of a deck (`slides.yaml`) or of a figure file: `type` is one
of CHART_TYPES, with the fields the linkedin plugin's README lists for it (`bars`: `groups` or
`rows`; `columns`: `items`; `line`: `x` and `series`; `gantt`: `ticks` and `rows`; `day` or
`timeline`: `events`; `windows`: `months` and `windows`). Numbers are numbers here: whoever reads
`{{result:key}}` resolves it before calling.

Sizes are CSS pixels (1 px = 1/96 inch = 0.75 pt): `width_px` x `height_px` is the space the
chart gets on the page, `text_px` the size of its labels (default `charts.text_px` of the design,
else 22), `scale` how many image pixels one CSS pixel gets (2: 1840 px wide for 920 px). A
report figure 16 cm wide is about 605 px with `text_px=9.3` (7 pt).

**Who draws.** The built-in renderer draws with matplotlib, styled from the design: colours,
palette, fonts (the design's font files are registered first), `charts.highlight_one`,
`charts.gridlines`. A design may name another renderer, which a plugin brings:

    # design.yaml
    charts: {renderer: firm}

    # the plugin (see plugins.py)
    def register(api):
        api.chart_renderer("firm", draw, types=("bars", "columns", "line"))

    def draw(block, *, design, width_px, height_px, out, lang, text_px=None, scale=2.0) -> Path

A renderer may draw everything itself, or build a `Style` and call `draw(..., style=...)` of
this module, so that only colours, fonts and rules change. When the named renderer is not
installed, the built-in one draws and `render(..., notes=[...])` says so. A design file stays
data: it names a renderer, it never holds code.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

CHART_TYPES = ("bars", "columns", "line", "gantt", "day", "windows")
ALIASES = {"timeline": "day"}
FORMATS = (".png", ".svg")
BUILTIN = "builtin"


class Unsupported(ValueError):
    """The renderer cannot draw this kind of block."""


# ------------------------------------------------------------------ checking a block
def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def kind(block: dict) -> str:
    t = str((block or {}).get("type") or "")
    return ALIASES.get(t, t)


def check(block: dict) -> list[str]:
    """What is wrong with a chart block, in sentences; empty when it can be drawn."""
    if not isinstance(block, dict):
        return ["a chart is a mapping with `type`"]
    t = kind(block)
    if t not in CHART_TYPES:
        return [f"`type` must be one of {', '.join(CHART_TYPES)} (or timeline), not {block.get('type')!r}"]
    out: list[str] = []
    if t == "bars":
        groups = block.get("groups") or ([{"rows": block["rows"]}] if block.get("rows") else [])
        if not isinstance(groups, list) or not groups:
            return ["bars: `groups` (each with `rows`) or `rows` is missing"]
        rows = [r for g in groups if isinstance(g, dict) for r in (g.get("rows") or [])]
        if not rows or not all(isinstance(r, dict) and r.get("label") not in (None, "") for r in rows):
            out.append("bars: every row needs a `label`")
        if any(not isinstance(r, dict) or not _num(r.get("value")) or r["value"] < 0 for r in rows):
            out.append("bars: every row needs a `value` that is a number of 0 or more")
        elif "max" in block and (not _num(block["max"]) or block["max"] <= 0 or any(r["value"] > block["max"] for r in rows)):
            out.append("bars: `max` must be a number at least as large as the largest value")
    elif t == "columns":
        items = block.get("items")
        if not isinstance(items, list) or not items:
            return ["columns: `items` must be a list with at least one entry"]
        if any(not isinstance(c, dict) or not _num(c.get("value")) or c["value"] < 0 for c in items):
            out.append("columns: every item needs a `value` that is a number of 0 or more")
        elif "max" in block and (not _num(block["max"]) or any(c["value"] > block["max"] for c in items)):
            out.append("columns: `max` must be a number at least as large as the largest value")
        if len(items) > 12:
            out.append("columns: more than 12 columns do not fit: aggregate, or use a line")
    elif t == "line":
        x, series = block.get("x"), block.get("series")
        if not isinstance(x, list) or len(x) < 2:
            out.append("line: `x` must list at least two positions")
        if not isinstance(series, list) or not series:
            return out + ["line: `series` must be a list with at least one entry"]
        for s in series:
            vals = s.get("values") if isinstance(s, dict) else None
            if not isinstance(vals, list) or len(vals) != len(x or []):
                out.append(f"line: series “{(s or {}).get('label')}” needs one value per x position")
            elif any(v is not None and not _num(v) for v in vals) or sum(1 for v in vals if v is not None) < 2:
                out.append(f"line: series “{s.get('label')}” needs at least two numbers (null marks a gap)")
        if len(series) > 6:
            out.append("line: more than 6 series cannot be labelled at their ends: show fewer")
    elif t == "gantt":
        ticks, rows = block.get("ticks"), block.get("rows")
        if not isinstance(ticks, list) or not ticks:
            return ["gantt: `ticks` must be a list"]
        if not isinstance(rows, list) or not rows:
            return ["gantt: `rows` must be a list with at least one entry"]
        n = len(ticks)
        for r in rows:
            if not isinstance(r, dict):
                out.append("gantt: every row is a mapping with `span`")
                continue
            start, span, ext = r.get("start", 0), r.get("span"), r.get("ext", 0)
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in (start, span, ext)) or span < 1 or start < 0 or start + span + ext > n:
                out.append(f"gantt: row “{r.get('label') or r.get('sub')}”: start + span + ext must be whole numbers within the {n} ticks")
    elif t == "day":
        events = block.get("events")
        if not isinstance(events, list) or not events:
            return ["day: `events` must be a list with at least one entry"]
        for e in events:
            if not isinstance(e, dict) or e.get("time") in (None, ""):
                out.append("day: every event needs a `time`")
            elif not _num(e.get("pos")) or not 0 <= e["pos"] <= 100:
                out.append(f"day: event “{e.get('time')}”: `pos` is a position on the axis from 0 to 100")
            elif e.get("align") not in (None, "left", "right"):
                out.append(f"day: event “{e.get('time')}”: `align` is left or right")
    elif t == "windows":
        months, wins = block.get("months"), block.get("windows")
        if not isinstance(months, list) or not months:
            out.append("windows: `months` must list the periods of the axis")
        if not isinstance(wins, list) or not wins:
            return out + ["windows: `windows` must be a list with at least one entry"]
        for w in wins:
            if not isinstance(w, dict) or not (_num(w.get("start")) and _num(w.get("width")) and 0 <= w["start"] and w["width"] > 0
                                               and w["start"] + w["width"] <= 100):
                out.append(f"windows: window “{(w or {}).get('label')}”: `start` and `width` are percentages of the axis, together at most 100")
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ fonts: names -> files
def _font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        dirs += [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path.home() / "Library" / "Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts")]
    else:
        dirs += [Path.home() / ".local" / "share" / "fonts", Path.home() / ".fonts", Path("/usr/local/share/fonts"), Path("/usr/share/fonts")]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=None)
def _font_info(path: str) -> tuple[frozenset, int, bool] | None:
    """(names the font answers to, weight, italic) of a font file, or None if it cannot be read."""
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(path, lazy=True, fontNumber=0)
        names = set()
        for rec in f["name"].names:
            if rec.nameID in (1, 4, 6, 16):
                try:
                    names.add(rec.toUnicode().strip().lower())
                except UnicodeDecodeError:
                    continue
        os2 = f["OS/2"] if "OS/2" in f else None
        weight = int(getattr(os2, "usWeightClass", 400) or 400)
        italic = bool(getattr(os2, "fsSelection", 0) & 1)
        f.close()
        return frozenset(names), weight, italic
    except Exception:                                           # a broken or unusual font file: not a candidate
        return None


@lru_cache(maxsize=1)
def _system_fonts() -> tuple[str, ...]:
    out = []
    for d in _font_dirs():
        for f in d.rglob("*"):
            if f.suffix.lower() in (".otf", ".ttf", ".ttc"):
                out.append(str(f))
    return tuple(out)


def design_font_files(design: dict) -> list[Path]:
    """Font files a design brings in its folder: `fonts.files`, `fonts.faces[].file`, `charts.fonts`."""
    folder = Path(design["folder"]) if design.get("folder") else None
    if folder is None:
        return []
    fonts = design.get("fonts") or {}
    names = [*(fonts.get("files") or []), *[f.get("file") for f in fonts.get("faces") or [] if isinstance(f, dict)],
             *((design.get("charts") or {}).get("fonts") or [])]
    return [folder / n for n in names if isinstance(n, str) and n and (folder / n).is_file()]


def font_file(name: str, *, weight: int = 400, design: dict | None = None) -> Path | None:
    """The file of the font a document names (as Office or a browser would ask for it), or None.

    The design's own font files are searched first, then the machine's fonts. A file matches
    when its family, full or PostScript name is `name` (case does not matter, spaces do: "DIN Pro"
    is not "DINPro"); of several, the upright one nearest to `weight` wins.
    """
    want = name.strip().lower()
    for pool in ([str(p) for p in design_font_files(design or {})], _system_fonts()):
        found = []
        for p in pool:
            info = _font_info(p)
            if info and want in info[0]:
                found.append((info[2], abs(info[1] - weight), p))
        if found:
            return Path(min(found)[2])
    return None


# ------------------------------------------------------------------ style
def _hex(c: str) -> str:
    h = str(c).strip().lstrip("#")
    if len(h) == 3:
        h = "".join(x * 2 for x in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"design: {c!r} is not a hex colour like #1f3a5f")
    return "#" + h.lower()


def mix(a: str, b: str, share: float) -> str:
    """`share` of colour a over colour b, as one solid colour."""
    ra, rb = [[int(_hex(x)[i:i + 2], 16) for i in (1, 3, 5)] for x in (a, b)]
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02x}" for x, y in zip(ra, rb))


@dataclass
class Style:
    """Everything the built-in drawing takes from a design. A chart renderer may build its own."""
    regular: object                         # matplotlib FontProperties of the text face
    bold: object                            # ... of the bold face (a real bold file where there is one)
    ink: str                                # category labels
    text: str                               # values, ticks, secondary labels
    strong: str                             # the highlighted series and its value, group labels
    neutral: str                            # the other series
    accent: str                             # the one accent (accented events, extensions)
    axis: str                               # axis lines
    hair: str                               # separators between rows
    paper: str                              # behind labels that must cover a line
    faint: str = ""                         # second lines of labels (else `text`)
    palette: list[str] = field(default_factory=list)
    highlight_one: bool = True
    grid: bool = False                      # gridlines on the value axis, with their values
    grid_color: str = "#d0d0d0"
    zero: str = ""                          # a zero line in this colour (dashed) when values cross zero
    series_fn: Callable | None = None       # n -> n series colours (else the palette, cycled)
    label_color_fn: Callable | None = None  # series colour -> its colour as text (else the same)
    bold_values: bool = True                # the highlighted value in the bold face
    values_in_series_color: bool = False    # every value label in its series' colour (as text) and bold

    def __post_init__(self):
        self.faint = self.faint or self.text

    def value(self, color: str, hi: bool, one: bool) -> tuple[str, bool]:
        """(colour, bold) of the value label of a mark drawn in `color`."""
        if self.values_in_series_color or not one:
            return self.label_color(color), self.bold_values
        return (self.strong if hi else self.text), hi and self.bold_values

    def series(self, n: int) -> list[str]:
        if self.series_fn:
            return list(self.series_fn(n))
        pal = self.palette or [self.strong]
        return [pal[i % len(pal)] for i in range(n)]

    def label_color(self, c: str) -> str:
        return self.label_color_fn(c) if self.label_color_fn else c


def _font_props(design: dict):
    """(regular, bold) FontProperties for the design's body and heading fonts."""
    from matplotlib.font_manager import FontProperties
    fonts = design.get("fonts") or {}
    generic = {"serif", "sans-serif", "monospace", "system-ui", "cursive"}
    body = [n for n in fonts.get("body") or [] if n not in generic]
    head = [n for n in fonts.get("heading") or [] if n not in generic]

    def first(names, weight):
        for n in names:
            f = font_file(n, weight=weight, design=design)
            if f:
                return f
        return None
    reg = first(body, 400)
    bold_named = next((n for n in head if n not in body), None)         # a heading face of its own ("Firm-Bold")
    bold = first([bold_named], 400) if bold_named else None
    bold = bold or first(head or body, 700)
    regular = FontProperties(fname=str(reg)) if reg else FontProperties(family="sans-serif")
    if bold and bold != reg:
        strong = FontProperties(fname=str(bold))
    else:
        strong = FontProperties(fname=str(reg), weight="bold") if reg else FontProperties(family="sans-serif", weight="bold")
    return regular, strong


def style_of(design: dict) -> Style:
    """The built-in renderer's style for a design (BASE_DESIGN keys are always there)."""
    c = design["colors"]
    charts = design.get("charts") or {}
    regular, bold = _font_props(design)
    neutral = _hex(c["neutral"])
    return Style(regular=regular, bold=bold, ink=_hex(c["ink"]), text=_hex(c["ink_soft"]), strong=_hex(c["primary"]),
                 neutral=neutral, accent=_hex(c["accent"]), axis=_hex(c["ink_faint"]), hair=mix(c["ink"], c["paper"], 0.22),
                 paper=_hex(charts.get("panel") or c["surface"]), faint=_hex(c["ink_faint"]),
                 palette=[_hex(p) for p in design.get("palette") or [c["primary"]]],
                 highlight_one=bool(charts.get("highlight_one", True)), grid=bool(charts.get("gridlines", False)),
                 grid_color=_hex(charts.get("grid") or c["neutral"]),
                 zero=_hex((charts.get("zero_line") or {}).get("color") or c["ink_faint"]))


# ------------------------------------------------------------------ choosing the renderer
def renderer(design: dict) -> tuple[str, Callable, tuple, str | None]:
    """(name, function, block types, note) of the renderer that draws this design's charts.

    The note says why the built-in renderer stands in for the one the design names."""
    name = str((design.get("charts") or {}).get("renderer") or "").strip()
    if name and name != BUILTIN:
        from . import plugins
        r = plugins.load().chart_renderers.get(name)
        if r is not None:
            return name, r.fn, tuple(ALIASES.get(t, t) for t in r.types) or CHART_TYPES, None
        return BUILTIN, draw, CHART_TYPES, (f"design {design.get('id')} draws charts with renderer `{name}`, which no installed "
                                            "plugin provides (sb plugin list); the built-in renderer drew them")
    return BUILTIN, draw, CHART_TYPES, None


def supported(design: dict) -> tuple[str, ...]:
    """The block types the design's chart renderer draws."""
    return renderer(design)[2]


def render(block: dict, *, design: dict, width_px: int, height_px: int, out: Path, lang: str,
           text_px: float | None = None, scale: float = 2.0, notes: list | None = None) -> Path:
    """Draw one chart block as an image (`out` ends in .png or .svg) with the design's renderer.

    Raises ValueError (with every problem) for a block that cannot be drawn, Unsupported for a
    type the renderer does not draw. `notes`, when given, receives what the caller should tell."""
    problems = check(block)
    if problems:
        raise ValueError("; ".join(problems))
    name, fn, types, note = renderer(design)
    if note and notes is not None and note not in notes:
        notes.append(note)
    if kind(block) not in types:
        raise Unsupported(f"chart renderer `{name}` does not draw {kind(block)} charts (it draws {', '.join(types)})")
    out = Path(out)
    if out.suffix.lower() not in FORMATS:
        raise ValueError(f"{out.name}: a chart is written as {' or '.join(FORMATS)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    return Path(fn(dict(block, type=kind(block)), design=design, width_px=int(width_px), height_px=int(height_px),
                   out=out, lang=lang, text_px=text_px, scale=scale) or out)


# ------------------------------------------------------------------ the built-in renderer
def natural_height(block: dict, *, width_px: float, text_px: float = 22) -> float:
    """The height (px) a chart wants at this width; a page may give it more (it spreads) or less."""
    k = text_px / 22
    t = kind(block)
    if t == "bars":
        groups = block.get("groups") or [{"rows": block.get("rows") or []}]
        rows = sum(len(g.get("rows") or []) for g in groups)
        labelled = sum(1 for g in groups if g.get("label"))
        return (rows * 72 + labelled * 52 + (len(groups) - 1) * 32) * k
    if t == "columns":
        return float(block.get("height") or 420) * k
    if t == "line":
        return float(block.get("height") or 440) * k
    if t == "gantt":
        rows = block.get("rows") or []
        return (44 + sum(84 if r.get("sub") else 72 for r in rows)) * k
    if t == "day":
        return 420 * k
    if t == "windows":
        return (40 + 88 * len(block.get("windows") or [])) * k
    return 300 * k


def _fmt(v, german: bool) -> str:
    s = f"{v:g}" if _num(v) else str(v)
    return s.replace(".", ",") if german and _num(v) else s


class _Canvas:
    """A figure whose data coordinates are CSS pixels, y downwards."""

    def __init__(self, width: float, height: float, scale: float, style: Style, text_px: float):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        self.w, self.h, self.scale, self.st, self.t = float(width), float(height), float(scale), style, float(text_px)
        self.fig = Figure(figsize=(width / 96, height / 96), dpi=96 * scale)
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, width)
        self.ax.set_ylim(height, 0)
        self.ax.axis("off")
        self._r = self.fig.canvas.get_renderer()

    def _prop(self, size: float, bold: bool):
        p = (self.st.bold if bold else self.st.regular).copy()
        p.set_size(size * 0.75)
        return p

    def width(self, s: str, size: float, bold: bool = False) -> float:
        if not s:
            return 0.0
        w, _h, _d = self._r.get_text_width_height_descent(str(s), self._prop(size, bold), ismath=False)
        return w / self.scale

    def wrap(self, s: str, size: float, maxw: float, bold: bool = False) -> list[str]:
        lines: list[str] = []
        for para in str(s).split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = f"{cur} {word}".strip() if cur else word
                if cur and self.width(trial, size, bold) > maxw:
                    lines.append(cur)
                    cur = word
                else:
                    cur = trial
            lines.append(cur)
        return lines

    def text(self, x, y, s, *, size, bold=False, color=None, ha="left", va="center", z=5, bg=None):
        kw = {}
        if bg:
            kw["bbox"] = {"boxstyle": "square,pad=0.15", "fc": bg, "ec": "none"}
        self.ax.text(x, y, str(s), fontproperties=self._prop(size, bold), color=color or self.st.text, ha=ha, va=va,
                     zorder=z, **kw)

    def lines(self, x, y, lines, *, size, lh=1.3, **kw):
        """Several lines from the top `y`; returns the height used."""
        step = size * lh
        for i, s in enumerate(lines):
            self.text(x, y + step * i + step / 2, s, size=size, va="center", **kw)
        return step * len(lines)

    def rect(self, x, y, w, h, color, z=2):
        from matplotlib.patches import Rectangle
        self.ax.add_patch(Rectangle((x, y), max(w, 0), max(h, 0), facecolor=color, edgecolor="none", linewidth=0, zorder=z))

    def line(self, xs, ys, color, width=1.0, dash=False, z=3, cap="butt"):
        self.ax.plot(xs, ys, color=color, linewidth=width * 0.75, linestyle=(0, (4, 3)) if dash else "-", zorder=z,
                     solid_capstyle=cap, solid_joinstyle="round", dash_capstyle="butt")

    def dot(self, x, y, r, face, edge, width=3.0, z=6):
        from matplotlib.patches import Circle
        self.ax.add_patch(Circle((x, y), r, facecolor=face, edgecolor=edge, linewidth=width * 0.75, zorder=z))

    def save(self, out: Path) -> Path:
        self.fig.savefig(out, dpi=96 * self.scale, transparent=True, metadata={"Software": None} if out.suffix == ".png" else None)
        return out


def _ticks(lo: float, hi: float, n: int = 5, *, room: float | None = None, integer: bool = False) -> list[float]:
    """Round values for gridlines between lo and hi; up to `room` when the axis shows more than hi."""
    from matplotlib.ticker import MaxNLocator
    end = max(hi, room or hi)
    return [float(v) for v in MaxNLocator(n, integer=integer).tick_values(lo, hi) if lo - 1e-9 <= v <= end + 1e-9]


def spread(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Label positions moved apart to at least `gap`, kept between lo and hi, in their order."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = list(ys)
    for a, b in zip(order, order[1:]):
        pos[b] = max(pos[b], pos[a] + gap)
    if order and pos[order[-1]] > hi:
        pos[order[-1]] = hi
        for b, a in zip(reversed(order), list(reversed(order))[1:]):
            pos[a] = min(pos[a], pos[b] - gap)
    if order and pos[order[0]] < lo:
        step = (hi - lo) / max(len(order) - 1, 1)
        for k, i in enumerate(order):
            pos[i] = lo + k * step
    return pos


def _bars(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    groups = b.get("groups") or [{"label": "", "rows": b.get("rows") or []}]
    rows = [r for g in groups for r in g["rows"]]
    top = b.get("max") or max(r["value"] for r in rows) or 1
    one = st.highlight_one and any(r.get("hi") for r in rows)
    colors = st.series(len(rows)) if not one else []
    size_l, size_v, size_g = t * 1.05, t * 1.1, t
    label_w = b.get("label_width") or (max(c.width(r["label"], size_l) for r in rows) + 24 * k)
    label_w = min(label_w, c.w * 0.45)
    tick_h = (t * 1.6) if st.grid else 0
    n_lab = sum(1 for g in groups if g.get("label"))
    head = 52 * k
    gap_g = 32 * k
    fixed = n_lab * head + (len(groups) - 1) * gap_g + tick_h
    row_h = min(max((c.h - fixed) / max(len(rows), 1), 40 * k), 72 * k * 2.2)
    bar_h = min(max(row_h * 0.58, 20 * k), 44 * k * 1.6)
    used = fixed + row_h * len(rows)
    y = max((c.h - used) / 2, 0)
    x0 = label_w
    track = c.w - x0
    span = track * 0.8                                  # a fifth of the track is room for the value label
    grid = _ticks(0, top, room=top / 0.8, integer=all(float(r["value"]).is_integer() for r in rows)) if st.grid else []
    for v in grid:
        x = x0 + v / top * span
        c.text(x, y + used - tick_h / 2, _fmt(v, german), size=t * 0.8, ha="center", color=st.text)
    i = 0
    for g in groups:
        if g.get("label"):
            c.text(0, y + head * 0.4, g["label"], size=size_g, bold=True, color=st.strong)
            c.line([0, c.w], [y + head * 0.82, y + head * 0.82], st.neutral, 1.2)
            y += head
        g_top = y
        for v in grid:                                  # gridlines on the value axis, behind the rows of a group
            x = x0 + v / top * span
            c.line([x, x], [g_top, g_top + row_h * len(g["rows"])], st.grid_color, 1, z=1)
        for r in g["rows"]:
            mid = y + row_h / 2
            hi = bool(r.get("hi"))
            color = (st.strong if hi else st.neutral) if one else colors[i]
            c.text(0, mid, r["label"], size=size_l, color=st.ink)
            length = r["value"] / top * span
            c.rect(x0, mid - bar_h / 2, length, bar_h, color)
            text = str(r.get("text") or _fmt(r["value"], german))
            vcol, bold = st.value(color, hi, one)
            tw = c.width(text, size_v, bold)
            if x0 + length + 16 * k + tw > c.w:          # no room beside the bar: inside, at its end
                c.text(x0 + length - 14 * k, mid, text, size=size_v, bold=bold, ha="right", color=st.paper if hi else st.ink)
            else:
                c.text(x0 + length + 16 * k, mid, text, size=size_v, bold=bold, color=vcol, bg=st.paper if grid else None)
            y += row_h
            i += 1
        c.line([x0, x0], [g_top + (row_h - bar_h) / 2 - 2, y - (row_h - bar_h) / 2 + 2], st.axis, 2)
        y += gap_g


def _columns(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    items = b["items"]
    top = b.get("max") or max(it["value"] for it in items) or 1
    one = st.highlight_one and any(it.get("hi") for it in items)
    colors = st.series(len(items)) if not one else []
    n = len(items)
    left = 0.0
    grid = _ticks(0, top, room=top / 0.84, integer=all(float(it["value"]).is_integer() for it in items)) if st.grid else []
    if grid:
        left = max(c.width(_fmt(v, german), t * 0.8) for v in grid) + 14 * k
    gap = 24 * k
    col_w = (c.w - left - gap * (n - 1)) / n
    size_lab = t * 0.92
    lab_lines = [c.wrap(it.get("label", ""), size_lab, col_w) for it in items]
    lab_h = max(len(x) for x in lab_lines) * size_lab * 1.25 + 12 * k
    base = c.h - lab_h
    plot_h = base - t * 0.5
    span = plot_h * 0.84                                # the rest is room for the value label
    for v in grid:
        yv = base - v / top * span
        c.line([left, c.w], [yv, yv], st.grid_color, 1, z=1)
        c.text(left - 10 * k, yv, _fmt(v, german), size=t * 0.8, ha="right", color=st.text)
    bw = min(col_w, 120 * k)
    for i, it in enumerate(items):
        x = left + i * (col_w + gap)
        cx = x + col_w / 2
        hi = bool(it.get("hi"))
        color = (st.strong if hi else st.neutral) if one else colors[i]
        h = it["value"] / top * span
        c.rect(cx - bw / 2, base - h, bw, h, color)
        text = str(it.get("text") or _fmt(it["value"], german))
        vcol, bold = st.value(color, hi, one)
        c.text(cx, base - h - 10 * k, text, size=t * 1.05, bold=bold, ha="center", va="bottom", color=vcol)
        c.lines(cx, base + 12 * k, lab_lines[i], size=size_lab, lh=1.25, ha="center", color=st.ink)
    c.line([left, c.w], [base, base], st.axis, 2)


def _line(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    x, series = b["x"], b["series"]
    vals = [v for s in series for v in s["values"] if v is not None]
    lo = b["min"] if _num(b.get("min")) else min(vals)
    hi = b["max"] if _num(b.get("max")) else max(vals)
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = (lo if _num(b.get("min")) else lo - pad), (hi if _num(b.get("max")) else hi + pad)
    one = st.highlight_one and any(s.get("hi") for s in series)
    colors = st.series(len(series))
    size_end = t * 0.95
    ends = []
    for i, s in enumerate(series):
        pts = [(j, v) for j, v in enumerate(s["values"]) if v is not None]
        end_text = s.get("end_text")
        if end_text is None:
            end_text = _fmt(pts[-1][1], german) if b.get("end_values", True) else ""
        ends.append((s, pts, str(end_text), (st.strong if s.get("hi") else st.neutral) if one else colors[i]))
    gutter = b.get("gutter") or min(max(c.width(f"{s['label']} {e}".strip(), size_end, True) for s, _p, e, _c in ends) + 20 * k, c.w * 0.4)
    left = 0.0
    yt = _ticks(lo, hi, integer=all(float(v).is_integer() for v in vals)) if st.grid else []
    if st.grid:
        left = max(c.width(_fmt(v, german), t * 0.8) for v in yt) + 14 * k
    bottom = 44 * k
    pw, ph = c.w - gutter - left, c.h - bottom
    n = len(x)
    px = lambda j: left + (j / (n - 1) * pw if n > 1 else pw / 2)
    py = lambda v: (hi - v) / (hi - lo) * ph
    for v in yt:
        c.line([left, left + pw], [py(v), py(v)], st.grid_color, 1, z=1)
        c.text(left - 10 * k, py(v), _fmt(v, german), size=t * 0.8, ha="right")
    if lo < 0 < hi and st.zero:
        c.line([left, left + pw], [py(0), py(0)], st.zero, 1.2, dash=True, z=2)
    for r in b.get("refs") or []:
        if _num(r.get("y")):
            c.line([left, left + pw], [py(r["y"]), py(r["y"])], st.axis, 1, dash=True, z=2)
            c.text(left + 8 * k, py(r["y"]) - 6 * k, r.get("label", _fmt(r["y"], german)), size=t * 0.8, va="bottom")
    c.line([left, left + pw], [ph, ph], st.axis, 2)
    c.line([left, left], [0, ph], st.axis, 1)
    for s, pts, _e, color in sorted(ends, key=lambda e: bool(e[0].get("hi"))):     # the highlighted line on top
        segs, cur = [], []
        for j, v in enumerate(s["values"]):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append((px(j), py(v)))
        if cur:
            segs.append(cur)
        for seg in segs:
            c.line([p[0] for p in seg], [p[1] for p in seg], color, 6 if s.get("hi") else 4, z=4 + bool(s.get("hi")), cap="round")
    gap = size_end * 1.25
    placed = spread([py(pts[-1][1]) for _s, pts, _e, _c in ends], gap, size_end * 0.6, ph - size_end * 0.6)
    for (s, pts, e, color), yy in zip(ends, placed):
        hi_s = bool(s.get("hi"))
        tcol, bold = st.value(color, hi_s, one)
        c.text(left + pw + 16 * k, yy, f"{s['label']} {e}".strip(), size=size_end, bold=bold, color=tcol)
    # x labels: first and last always, the rest where they do not touch
    size_x = t * 0.82
    placed_x: list[tuple[float, float]] = []
    order = [0, n - 1] + list(range(1, n - 1)) if n > 1 else [0]
    for j in order:
        lab = str(x[j])
        if lab == "":
            continue
        w = c.width(lab, size_x)
        xx = px(j)
        a, ha = (xx, "left") if j == 0 else ((xx - w, "right") if j == n - 1 else (xx - w / 2, "center"))
        box = (a - 12 * k, a + w + 12 * k)
        if any(box[0] < q[1] and q[0] < box[1] for q in placed_x):
            continue
        placed_x.append(box)
        c.text(xx, ph + bottom * 0.55, lab, size=size_x, ha=ha)


def _gantt(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    ticks, rows = b["ticks"], b["rows"]
    size_l, size_s = t, t * 0.78
    label_w = b.get("label_width") or (max(max(c.width(r.get("label", ""), size_l), c.width(r.get("sub", ""), size_s)) for r in rows) + 24 * k)
    label_w = min(label_w, c.w * 0.45)
    head = 44 * k
    want = [84 if r.get("sub") else 72 for r in rows]
    row_k = min(max((c.h - head) / (sum(want) * k), 0.6), 2.2)
    cell = (c.w - label_w) / len(ticks)
    c.text(0, head * 0.45, b.get("corner", ""), size=t * 0.86, bold=True, color=st.text)
    for i, tk in enumerate(ticks):
        c.text(label_w + cell * (i + 0.5), head * 0.45, tk, size=t * 0.86, bold=True, ha="center", color=st.text)
    c.line([0, c.w], [head, head], st.axis, 2)
    y = head
    seg_h = min(32 * k * max(row_k, 1) ** 0.5, 44 * k)
    for i, r in enumerate(rows):
        h = want[i] * k * row_k
        mid = y + h / 2
        if r.get("label") and r.get("sub"):
            c.text(0, mid - size_s * 0.62, r["label"], size=size_l, color=st.ink)
            c.text(0, mid + size_l * 0.62, r["sub"], size=size_s, color=st.faint)
        elif r.get("sub"):
            c.text(0, mid, r["sub"], size=size_s, color=st.faint)
        else:
            c.text(0, mid, r.get("label", ""), size=size_l, color=st.ink)
        start = r.get("start", 0)
        c.rect(label_w + cell * start, mid - seg_h / 2, cell * r["span"], seg_h, st.strong if r.get("hi") else st.neutral)
        if r.get("ext"):
            x1 = label_w + cell * (start + r["span"])
            c.line([x1, x1 + cell * r["ext"]], [mid, mid], st.accent, 3, dash=True)
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if not (nxt is not None and not nxt.get("label")):          # a continuation row belongs to this one
            c.line([0, c.w], [y + h, y + h], st.hair, 1)
        y += h


def _day(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    events = b["events"]
    mid = c.h / 2
    pad = 12 * k
    x = lambda p: pad + p / 100 * (c.w - 2 * pad)
    c.line([x(0), x(100)], [mid, mid], st.strong, 3)
    size_time, size_what = t * 1.25, t * 0.92
    lab_w = 236 * k * 1.12
    stem = 44 * k
    gap = 16 * k

    def room(e) -> float:
        """How wide the label of `e` may be: up to the next label on its side (shared when they face each other)."""
        ex, right, below = x(e["pos"]), e.get("align") == "right", bool(e.get("below"))
        free = (ex - 4 * k) if right else (c.w - ex - 4 * k)
        for o in events:
            if o is e or bool(o.get("below")) != below:
                continue
            ox, oright = x(o["pos"]), o.get("align") == "right"
            if not right and ox > ex:                      # a neighbour to the right
                free = min(free, (ox - ex) / 2 - gap / 2 if oright else ox - ex - gap)
            elif right and ox < ex:                        # a neighbour to the left
                free = min(free, (ex - ox) / 2 - gap / 2 if not oright else ex - ox - gap)
        return max(min(lab_w, free), c.width(e["time"], size_time, True))

    for e in events:
        ex = x(e["pos"])
        acc = bool(e.get("accent"))
        c.dot(ex, mid, 8.5 * k, st.accent if acc else st.paper, st.accent if acc else st.strong, 3 * k)
        right = e.get("align") == "right"
        below = bool(e.get("below"))
        lines = c.wrap(e.get("what", ""), size_what, room(e)) if e.get("what") else []
        block_h = size_time * 1.2 + (4 * k + len(lines) * size_what * 1.35 if lines else 0)
        tx = ex - 4 * k if right else ex + 4 * k
        ha = "right" if right else "left"
        if below:
            c.line([ex, ex], [mid + 12 * k, mid + 12 * k + stem], st.neutral, 1)
            top = mid + 12 * k + stem + 8 * k
        else:
            c.line([ex, ex], [mid - 12 * k - stem, mid - 12 * k], st.neutral, 1)
            top = mid - 12 * k - stem - 8 * k - block_h
        c.text(tx, top + size_time * 0.6, e["time"], size=size_time, bold=True, ha=ha, color=st.accent if acc else st.strong)
        if lines:
            c.lines(tx, top + size_time * 1.2 + 4 * k, lines, size=size_what, lh=1.35, ha=ha, color=st.text)


def _windows(c: _Canvas, b: dict, german: bool) -> None:
    st, t, k = c.st, c.t, c.t / 22
    months, wins = b["months"], b["windows"]
    size_l = t
    label_w = b.get("label_width") or (max(c.width(w["label"], size_l) for w in wins) + 24 * k)
    label_w = min(label_w, c.w * 0.4)
    head = 40 * k
    row_h = min(max((c.h - head) / len(wins), 56 * k), 92 * k * 1.8)
    track = c.w - label_w
    step = track / len(months)
    for i, m in enumerate(months):
        c.text(label_w + step * (i + 0.5), head * 0.45, m, size=t * 0.82, bold=True, ha="center", color=st.text)
    c.line([0, c.w], [head, head], st.axis, 2)
    y = head
    size_d = t * 0.86
    for w in wins:
        mid = y + row_h / 2
        c.text(0, mid, w["label"], size=size_l, color=st.ink)
        for i in range(len(months) + 1):
            xx = label_w + step * i
            c.line([xx, xx], [y, y + row_h], st.hair, 1, z=1)
        x0 = label_w + w["start"] / 100 * track
        ww = w["width"] / 100 * track
        c.rect(x0, mid - 16 * k, ww, 32 * k, st.strong, z=3)
        if w.get("dates"):
            tw = c.width(w["dates"], size_d)
            if x0 + ww + 12 * k + tw <= c.w:
                c.text(x0 + ww + 12 * k, mid, w["dates"], size=size_d, color=st.text, bg=st.paper)
            else:
                c.text(x0 - 12 * k, mid, w["dates"], size=size_d, color=st.text, ha="right", bg=st.paper)
        c.line([0, c.w], [y + row_h, y + row_h], st.hair, 1)
        y += row_h


DRAW = {"bars": _bars, "columns": _columns, "line": _line, "gantt": _gantt, "day": _day, "windows": _windows}


def draw(block: dict, *, design: dict, width_px: int, height_px: int, out: Path, lang: str,
         text_px: float | None = None, scale: float = 2.0, style: Style | None = None) -> Path:
    """The built-in renderer. `style` replaces what is read from the design (for a plugin's renderer)."""
    t = kind(block)
    if t not in DRAW:
        raise Unsupported(f"the built-in chart renderer does not draw {t} charts")
    text_px = float(text_px or (design.get("charts") or {}).get("text_px") or 22)
    c = _Canvas(width_px, height_px, scale, style or style_of(design), text_px)
    DRAW[t](c, dict(block, type=t), str(lang).startswith("de"))
    return c.save(Path(out))


def rendered_size(path: Path) -> tuple[int, int] | None:
    """(width, height) in pixels of a PNG, read from its header."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return None


__all__ = ["CHART_TYPES", "Style", "Unsupported", "check", "draw", "font_file", "kind", "mix", "natural_height",
           "render", "renderer", "spread", "style_of", "supported"]
