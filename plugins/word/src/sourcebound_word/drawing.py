"""A vector figure (a one-page PDF, e.g. a TikZ diagram) as a native Word drawing in the design's look.

The PDF's drawing operations are read (lines, curves, rectangles, fills, text with its position) and
written again as a DrawingML group: one shape per painted path, one text box per line of text.
The geometry stays; colours and fonts become the design's:

    text                 the body font in the ink colour; bold text in the design's bold face
    lines and outlines   the primary colour; thick lines (emphasis) in the accent colour;
                         grey lines (helper and grid lines) in the grid colour
    filled areas         grey levels in the order of the design's series colours (darkest first)
    framed boxes         filled with the design's surface colour (dashed frames stay open)

Not every PDF can be read this way (images, shadings, unusual fonts): `read` returns None then,
and the renderer shows the figure as a picture.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from docx.oxml import parse_xml

EMU_PT = 12700
MAX_ITEMS = 1500                                    # more than this is a plot with data, not a diagram
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


@dataclass
class Path_:
    segs: list                                      # [("m", x, y) | ("l", x, y) | ("c", x1, y1, x2, y2, x, y) | ("h",)]
    stroke: tuple | None                            # rgb 0..1 or None
    fill: tuple | None
    width: float = 0.4
    dash: bool = False

    def bbox(self):
        xs = [v for s in self.segs for v in s[1::2]]
        ys = [v for s in self.segs for v in s[2::2]]
        return min(xs), min(ys), max(xs), max(ys)

    def is_box(self) -> bool:
        """A closed axis-parallel rectangle (a node's frame)."""
        pts = [(s[1], s[2]) for s in self.segs if s[0] in "ml"]
        closed = any(s[0] == "h" for s in self.segs)
        if not closed or len(pts) not in (4, 5) or any(s[0] == "c" for s in self.segs):
            return False
        xs, ys = {round(x, 1) for x, _ in pts}, {round(y, 1) for _, y in pts}
        x0, y0, x1, y1 = self.bbox()
        return len(xs) == 2 and len(ys) == 2 and x1 - x0 > 6 and y1 - y0 > 6


@dataclass
class Glyph:
    x: float
    y: float
    text: str
    adv: float                                      # advance along the baseline
    size: float
    bold: bool
    italic: bool
    rot: int                                        # 0 or 90 (counter-clockwise), 180, 270


@dataclass
class Line:
    runs: list                                      # [(text, bold, italic)]
    x0: float
    x1: float
    y: float                                        # the baseline: y, or x for text that reads upwards (rot 90)
    size: float
    rot: int = 0
    align: str = "c"

    @property
    def text(self) -> str:
        return "".join(t for t, _b, _i in self.runs)


@dataclass
class Figure:
    width: float
    height: float
    paths: list = field(default_factory=list)
    lines: list = field(default_factory=list)


# ------------------------------------------------------------------ reading the PDF
def _mul(a, b):
    """Affine matrices [a b c d e f] as PDF writes them: a·b."""
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2],
            a[2] * b[1] + a[3] * b[3], a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _pt(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _glyph_names() -> dict:
    try:
        from pypdf._codecs import adobe_glyphs      # glyph name -> character
        return adobe_glyphs
    except Exception:                               # pragma: no cover - pypdf moved it
        return {}


class _Font:
    def __init__(self, font):
        font = font.get_object()
        if font.get("/Subtype") not in ("/Type1", "/TrueType", "/MMType1"):
            raise Unsupported(f"font type {font.get('/Subtype')}")   # Type3 and composite fonts: their codes are not characters
        self.name = str(font.get("/BaseFont", ""))
        low = self.name.lower()
        self.bold = bool(re.search(r"bold|medi|black|heavy|semibold|demi|-bx|cmbx", low))
        self.italic = bool(re.search(r"ital|oblique|slant|-ti|cmti|cmsl", low)) or bool(re.search(r"mi\d*$", low))
        self.first = int(font.get("/FirstChar", 0))
        self.widths = [float(w) for w in font.get("/Widths", [])]
        self.map: dict[int, str] = {}
        enc = font.get("/Encoding")
        enc = enc.get_object() if enc is not None else None
        names = _glyph_names()
        if hasattr(enc, "get") and enc.get("/Differences") is not None:
            code = 0
            for d in enc["/Differences"]:
                if isinstance(d, (int, float)):
                    code = int(d)
                else:
                    ch = names.get(str(d))
                    if ch is None and re.fullmatch(r"/uni([0-9A-F]{4})", str(d)):
                        ch = chr(int(str(d)[4:], 16))
                    if ch is not None:
                        self.map[code] = ch
                    code += 1
        tu = font.get("/ToUnicode")
        if tu is not None:
            try:
                self._cmap(tu.get_object().get_data().decode("latin-1"))
            except Exception:
                pass

    def _cmap(self, text: str) -> None:
        hexs = lambda h: "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4)) if len(h) >= 4 else chr(int(h, 16))
        for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
            for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                self.map[int(a, 16)] = hexs(b)
        for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
            for a, b, c in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                for n, code in enumerate(range(int(a, 16), int(b, 16) + 1)):
                    self.map[code] = chr(int(c, 16) + n)

    def char(self, code: int) -> str:
        ch = self.map.get(code)
        if ch is None:
            ch = chr(code) if 32 <= code < 127 or 160 <= code < 256 else ""
        return LIGATURES.get(ch, ch)

    def width(self, code: int) -> float:
        i = code - self.first
        return self.widths[i] / 1000 if 0 <= i < len(self.widths) and self.widths[i] else 0.5


class Unsupported(Exception):
    pass


def _gray(args) -> tuple:
    v = [float(a) for a in args]
    if len(v) == 1:
        return (v[0],) * 3
    if len(v) == 3:
        return tuple(v)
    if len(v) == 4:
        c, m, y, k = v
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    raise Unsupported("colour")


def read(pdf: Path) -> Figure | None:
    """The drawing of the first page of a PDF, or None where it holds something this cannot draw."""
    try:
        from pypdf import PdfReader
        from pypdf.generic import ContentStream
        reader = PdfReader(str(pdf))
        page = reader.pages[0]
        box = [float(v) for v in page.mediabox]
        fig = Figure(box[2] - box[0], box[3] - box[1])
        glyphs: list[Glyph] = []
        _run(ContentStream(page.get_contents(), reader).operations, page.get("/Resources") or {}, reader,
             [1, 0, 0, 1, -box[0], -box[1]], fig, glyphs)
        fig.lines = _lines(glyphs)
    except Exception:                               # Unsupported, or a PDF this reader does not follow
        return None
    if len(fig.paths) + len(glyphs) > MAX_ITEMS or not (fig.paths or glyphs):
        return None
    _align(fig.lines)
    return fig


def _run(ops, resources, reader, ctm, fig: Figure, glyphs: list, depth: int = 0) -> None:
    from pypdf.generic import ContentStream
    st = {"ctm": ctm, "stroke": (0, 0, 0), "fill": (0, 0, 0), "w": 1.0, "dash": False, "font": None, "size": 10,
          "tc": 0.0, "tw": 0.0, "th": 1.0, "tl": 0.0, "rise": 0.0}
    stack, segs, start = [], [], None
    tm = tlm = [1, 0, 0, 1, 0, 0]
    fonts: dict = {}
    font_res = resources.get("/Font") or {}
    xobjects = resources.get("/XObject") or {}

    def paint(stroke: bool, fill: bool, close: bool = False):
        nonlocal segs
        if close and segs:
            segs.append(("h",))
        if segs and (stroke or fill):
            fig.paths.append(Path_(segs, st["stroke"] if stroke else None, st["fill"] if fill else None,
                                   st["w"] * (abs(st["ctm"][0] * st["ctm"][3] - st["ctm"][1] * st["ctm"][2]) ** 0.5), st["dash"]))
        segs = []

    def show(items):
        nonlocal tm
        f = st["font"]
        if f is None:
            raise Unsupported("text without a font")
        for it in items:
            if isinstance(it, (int, float)):
                tm = _mul([1, 0, 0, 1, -float(it) / 1000 * st["size"] * st["th"], 0], tm)
                continue
            raw = bytes(it) if isinstance(it, bytes) else it.get_original_bytes() if hasattr(it, "get_original_bytes") else str(it).encode("latin-1")
            for code in raw:
                trm = _mul(_mul([st["size"] * st["th"], 0, 0, st["size"], 0, st["rise"]], tm), st["ctm"])
                adv = (f.width(code) * st["size"] + st["tc"] + (st["tw"] if code == 32 else 0)) * st["th"]
                x, y = trm[4], trm[5]
                size = (trm[2] ** 2 + trm[3] ** 2) ** 0.5
                vx, vy = trm[0], trm[1]
                rot = round(_angle(vx, vy) / 90) % 4 * 90
                scale = (vx ** 2 + vy ** 2) ** 0.5 / (st["size"] * st["th"]) if st["size"] else 1
                ch = f.char(code)
                if ch:
                    glyphs.append(Glyph(x, y, ch, adv * scale, size, f.bold, f.italic, rot))
                tm = _mul([1, 0, 0, 1, adv, 0], tm)

    for args, op in ops:
        op = op.decode("latin-1") if isinstance(op, bytes) else op
        if op == "q":
            stack.append(dict(st))
        elif op == "Q":
            st = stack.pop() if stack else st
        elif op == "cm":
            st["ctm"] = _mul([float(a) for a in args], st["ctm"])
        elif op == "w":
            st["w"] = float(args[0])
        elif op == "d":
            st["dash"] = bool(args and len(args[0]) > 0)
        elif op in ("G", "RG", "K"):
            st["stroke"] = _gray(args)
        elif op in ("g", "rg", "k"):
            st["fill"] = _gray(args)
        elif op in ("SC", "SCN"):
            if args and isinstance(args[-1], str) and str(args[-1]).startswith("/"):
                raise Unsupported("pattern")
            st["stroke"] = _gray(args)
        elif op in ("sc", "scn"):
            if args and isinstance(args[-1], str) and str(args[-1]).startswith("/"):
                raise Unsupported("pattern")
            st["fill"] = _gray(args)
        elif op == "m":
            x, y = _pt(st["ctm"], float(args[0]), float(args[1]))
            segs.append(("m", x, y))
            start = (x, y)
        elif op == "l":
            segs.append(("l", *_pt(st["ctm"], float(args[0]), float(args[1]))))
        elif op == "c":
            a = [float(v) for v in args]
            segs.append(("c", *_pt(st["ctm"], a[0], a[1]), *_pt(st["ctm"], a[2], a[3]), *_pt(st["ctm"], a[4], a[5])))
        elif op in ("v", "y"):
            a = [float(v) for v in args]
            cur = segs[-1][-2:] if segs else (0, 0)
            if op == "v":
                segs.append(("c", *cur, *_pt(st["ctm"], a[0], a[1]), *_pt(st["ctm"], a[2], a[3])))
            else:
                p2 = _pt(st["ctm"], a[2], a[3])
                segs.append(("c", *_pt(st["ctm"], a[0], a[1]), *p2, *p2))
        elif op == "re":
            x, y, w, h = (float(v) for v in args)
            m = st["ctm"]
            segs += [("m", *_pt(m, x, y)), ("l", *_pt(m, x + w, y)), ("l", *_pt(m, x + w, y + h)), ("l", *_pt(m, x, y + h)), ("h",)]
        elif op == "h":
            segs.append(("h",))
        elif op == "S":
            paint(True, False)
        elif op == "s":
            paint(True, False, True)
        elif op in ("f", "F", "f*"):
            paint(False, True)
        elif op in ("B", "B*"):
            paint(True, True)
        elif op in ("b", "b*"):
            paint(True, True, True)
        elif op == "n":
            segs = []
        elif op in ("W", "W*"):
            pass                                    # clipping: the figure's own paths stay inside it
        elif op == "BT":
            tm = tlm = [1, 0, 0, 1, 0, 0]
        elif op == "ET":
            pass
        elif op == "Tf":
            name = str(args[0])
            if name not in fonts:
                if name not in font_res:
                    raise Unsupported("font")
                fonts[name] = _Font(font_res[name])
            st["font"], st["size"] = fonts[name], float(args[1])
        elif op == "Tc":
            st["tc"] = float(args[0])
        elif op == "Tw":
            st["tw"] = float(args[0])
        elif op == "Tz":
            st["th"] = float(args[0]) / 100
        elif op == "TL":
            st["tl"] = float(args[0])
        elif op == "Ts":
            st["rise"] = float(args[0])
        elif op in ("Td", "TD"):
            if op == "TD":
                st["tl"] = -float(args[1])
            tlm = _mul([1, 0, 0, 1, float(args[0]), float(args[1])], tlm)
            tm = tlm
        elif op == "Tm":
            tlm = tm = [float(a) for a in args]
        elif op == "T*":
            tlm = _mul([1, 0, 0, 1, 0, -st["tl"]], tlm)
            tm = tlm
        elif op == "Tj":
            show([args[0]])
        elif op == "TJ":
            show(list(args[0]))
        elif op in ("'", '"'):
            tlm = _mul([1, 0, 0, 1, 0, -st["tl"]], tlm)
            tm = tlm
            show([args[-1]])
        elif op == "Do":
            xo = xobjects.get(str(args[0]))
            xo = xo.get_object() if xo is not None else None
            if xo is None or xo.get("/Subtype") != "/Form" or depth > 4:
                raise Unsupported("image")
            m = [float(v) for v in xo.get("/Matrix", [1, 0, 0, 1, 0, 0])]
            _run(ContentStream(xo, reader).operations, xo.get("/Resources") or resources, reader,
                 _mul(m, st["ctm"]), fig, glyphs, depth + 1)
        elif op in ("sh", "BI", "ID", "EI"):
            raise Unsupported("shading or inline image")


def _angle(vx: float, vy: float) -> float:
    import math
    return math.degrees(math.atan2(vy, vx)) % 360


def _lines(glyphs: list[Glyph]) -> list[Line]:
    """Glyphs in the order they were set -> lines of text (a word gap becomes a space)."""
    out: list[Line] = []
    cur: Line | None = None
    end = None
    for g in glyphs:
        if g.text.isspace():
            continue
        if g.rot not in (0, 90):
            raise Unsupported("text set upside down or downwards")
        pos, base = (g.x, g.y) if g.rot == 0 else (g.y, g.x)   # along the baseline, and where the baseline is
        if cur is not None and cur.rot == g.rot and abs(cur.y - base) < 0.3 * g.size and -0.3 * g.size < pos - end < 0.9 * g.size:
            gap = pos - end
            text = (" " if gap > 0.12 * g.size else "") + g.text
            if cur.runs[-1][1:] == (g.bold, g.italic):
                cur.runs[-1] = (cur.runs[-1][0] + text, g.bold, g.italic)
            else:
                cur.runs.append((text, g.bold, g.italic))
            cur.x1 = pos + g.adv
            cur.size = max(cur.size, g.size)
        else:
            cur = Line([(g.text, g.bold, g.italic)], pos, pos + g.adv, base, g.size, g.rot)
            out.append(cur)
        end = pos + g.adv
    return out


def _align(lines: list[Line]) -> None:
    """How a line was set: centred, flush left or flush right (from the lines next to it)."""
    tol = 0.6
    for ln in lines:
        others = [o for o in lines if o is not ln and o.rot == ln.rot]
        c = (ln.x0 + ln.x1) / 2
        if any(abs((o.x0 + o.x1) / 2 - c) < tol for o in others):
            ln.align = "c"
        elif any(abs(o.x1 - ln.x1) < tol for o in others):
            ln.align = "r"
        elif any(abs(o.x0 - ln.x0) < tol for o in others):
            ln.align = "l"
        else:
            ln.align = "c"


# ------------------------------------------------------------------ the design's look
def _hex(c: str) -> str:
    return c.lstrip("#").upper()


def _lum(rgb) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def look(design: dict) -> dict:
    """The colours and fonts a drawing takes from a design."""
    colors, charts, fonts = design.get("colors") or {}, design.get("charts") or {}, design.get("fonts") or {}
    series = charts.get("series") or design.get("palette") or [colors.get("primary", "#1f3a5f")]
    return {"line": _hex(colors.get("primary", "#1f3a5f")), "strong": _hex(colors.get("accent", colors.get("primary", "#1f3a5f"))),
            "grid": _hex(charts.get("grid") or colors.get("neutral", "#c9cfd8")), "text": _hex(colors.get("ink", "#111418")),
            "box": _hex(colors.get("surface", "#f4f6f8")), "paper": _hex(colors.get("paper", "#ffffff")),
            "series": [_hex(c) for c in series], "font": (fonts.get("body") or ["Calibri"])[0],
            "bold_font": bold_face(design)}


def bold_face(design: dict) -> str | None:
    """The font a design names for bold text, where bold is a face of its own (e.g. "Example-Bold");
    None where bold is the body font's bold weight."""
    fonts = design.get("fonts") or {}
    body = (fonts.get("body") or [""])[0]
    bold_weight = (fonts.get("weights") or {}).get("bold") or 700
    for face in fonts.get("faces") or []:
        try:
            weight = int(face.get("weight") or 0)
        except (TypeError, ValueError):
            continue
        names = face.get("local") or []
        if weight >= bold_weight and names and names[0] != body:
            return names[0]
    return None


def _colours(fig: Figure, lk: dict) -> list[tuple]:
    """(stroke, fill, width) per path in the design's colours."""
    fills = sorted({round(_lum(p.fill), 2) for p in fig.paths if p.fill is not None and _lum(p.fill) < 0.97 and not _small(p)})
    widths = sorted({round(p.width, 2) for p in fig.paths if p.stroke is not None})
    thin = widths[0] if widths else 0.4
    out, last = [], lk["line"]
    for p in fig.paths:
        stroke = fill = None
        if p.stroke is not None:
            if _lum(p.stroke) > 0.97:
                stroke = lk["paper"]
            elif _lum(p.stroke) > 0.25:
                stroke = lk["grid"]
            elif p.width > max(1.6 * thin, 0.7):
                stroke = lk["strong"]
            else:
                stroke = lk["line"]
            last = stroke
        if p.fill is not None:
            if _lum(p.fill) > 0.97:
                fill = lk["paper"]
            elif _small(p):
                fill = last                         # an arrow tip: the colour of its line
            else:
                fill = lk["series"][min(fills.index(round(_lum(p.fill), 2)), len(lk["series"]) - 1)]
        elif p.stroke is not None and p.is_box() and not p.dash:
            fill = lk["box"]
        out.append((stroke, fill, max(p.width, 0.5)))
    return out


def _small(p: Path_) -> bool:
    x0, y0, x1, y1 = p.bbox()
    return max(x1 - x0, y1 - y0) < 7


# ------------------------------------------------------------------ DrawingML
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def scale_for(fig: Figure, width_pt: float) -> float:
    return min(1.0, width_pt / fig.width) if fig.width else 1.0


def drawing(fig: Figure, design: dict, *, scale: float, shape_id: int, name: str, descr: str = "") -> object:
    """The figure as a <w:drawing> (an inline group of shapes), `scale` times its size in the PDF."""
    lk = look(design)
    k = EMU_PT * scale
    W, H = round(fig.width * k), round(fig.height * k)
    X = lambda x: round(x * k)
    Y = lambda y: round((fig.height - y) * k)
    shapes, n = [], shape_id
    for p, (stroke, fill, width) in zip(fig.paths, _colours(fig, lk)):
        x0, y0, x1, y1 = p.bbox()
        ox, oy = X(x0), Y(y1)
        w, h = max(X(x1) - ox, 1), max(Y(y0) - oy, 1)
        cmds = []
        for s in p.segs:
            if s[0] == "h":
                cmds.append("<a:close/>")
                continue
            pts = "".join(f'<a:pt x="{X(s[i]) - ox}" y="{Y(s[i + 1]) - oy}"/>' for i in range(1, len(s), 2))
            cmds.append({"m": f"<a:moveTo>{pts}</a:moveTo>", "l": f"<a:lnTo>{pts}</a:lnTo>", "c": f"<a:cubicBezTo>{pts}</a:cubicBezTo>"}[s[0]])
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        ln = (f'<a:ln w="{round(width * k)}" cap="flat"><a:solidFill><a:srgbClr val="{stroke}"/></a:solidFill>'
              f'{"<a:prstDash val=\"dash\"/>" if p.dash else ""}<a:miter lim="800000"/></a:ln>' if stroke else "<a:ln><a:noFill/></a:ln>")
        n += 1
        shapes.append(
            f'<wps:wsp><wps:cNvPr id="{n}" name="Path {n}"/><wps:cNvSpPr/><wps:spPr>'
            f'<a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
            f'<a:pathLst><a:path w="{w}" h="{h}"{"" if fill else " fill=\"none\""}>{"".join(cmds)}</a:path></a:pathLst></a:custGeom>'
            f'{fill_xml}{ln}</wps:spPr><wps:bodyPr/></wps:wsp>')
    fit = _fit(fig, lk)
    for ln in fig.lines:
        n += 1
        shapes.append(_textbox(ln, lk, k, fig.height, n, fit.get(round(ln.size, 1), 1.0)))
    xml = (f'<w:drawing {NS}><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{W}" cy="{H}"/>'
           f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{shape_id}" name="{_esc(name)}" descr="{_esc(descr)}"/>'
           f'<wp:cNvGraphicFramePr/><a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
           f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W}" cy="{H}"/>'
           f'<a:chOff x="0" y="0"/><a:chExt cx="{W}" cy="{H}"/></a:xfrm></wpg:grpSpPr>{"".join(shapes)}</wpg:wgp>'
           f'</a:graphicData></a:graphic></wp:inline></w:drawing>')
    return parse_xml(xml), n


_FONTS: dict = {}


def _font_file(name: str):
    """(width(text, size) in points, ascent, descent as parts of the size) of an installed font; None where
    it is not found (then the text keeps its size and the line sits by a common font's proportions)."""
    if name not in _FONTS:
        _FONTS[name] = None
        try:
            from fontTools.ttLib import TTFont
            from matplotlib import font_manager
            hits = [f.fname for f in font_manager.fontManager.ttflist if f.name == name]
            if hits:
                t = TTFont(hits[0], lazy=True, fontNumber=0)
                cmap, hmtx, upm = t.getBestCmap(), t["hmtx"].metrics, t["head"].unitsPerEm
                width = lambda text, size: sum(hmtx.get(cmap.get(ord(c), ""), (upm / 2, 0))[0] for c in text) / upm * size
                os2 = t["OS/2"]                     # Word lays a line out by the font's Windows ascent and descent
                _FONTS[name] = (width, os2.usWinAscent / upm, os2.usWinDescent / upm)
        except Exception:
            pass
    return _FONTS[name]


def _metrics(name: str):
    f = _font_file(name)
    return f[0] if f else None


def _font_of(bold: bool, lk: dict) -> str:
    return lk["bold_font"] if bold and lk["bold_font"] else lk["font"]


def _fit(fig: Figure, lk: dict) -> dict:
    """Per text size, the factor that keeps every line of that size in the room it had in the PDF
    (the design's font may run wider); one factor per size, so that the drawing stays even."""
    out: dict = {}
    for ln in fig.lines:
        widths = [_metrics(_font_of(b, lk)) for _t, b, _i in ln.runs]
        if not all(widths):
            continue
        new = sum(m(t, ln.size) for m, (t, _b, _i) in zip(widths, ln.runs))
        room = ln.x1 - ln.x0
        key = round(ln.size, 1)
        out[key] = min(out.get(key, 1.0), max(room / new, 0.8) if new > room else 1.0)
    return out


def _textbox(ln: Line, lk: dict, k: float, height: float, n: int, fit: float = 1.0) -> str:
    size = ln.size * fit * k / EMU_PT               # in points, at the drawing's scale
    half = max(int(size * 2 + 1e-6) if fit < 1 else round(size * 2), 8)   # Word counts half points; a fitted line rounds down
    size = half / 2
    ascent, descent = (_font_file(lk["font"]) or (None, 0.9, 0.25))[1:]
    lead = round(size * (ascent + descent) * 20)    # the font's own line height, in twips
    width = (ln.x1 - ln.x0) * 1.6 + 2 * ln.size     # room for a wider font: the text keeps its anchor
    if ln.align == "c":
        a = (ln.x0 + ln.x1) / 2 - width / 2
    elif ln.align == "r":
        a = ln.x1 - width
    else:
        a = ln.x0
    box_h = size * (ascent + descent) / (k / EMU_PT)   # in PDF points
    asc = size * ascent / (k / EMU_PT)              # the baseline, below the top of the box
    jc = {"c": "center", "r": "right", "l": "left"}[ln.align]
    runs = []
    for text, bold, italic in ln.runs:
        font = _font_of(bold, lk)
        color = lk["line"] if bold else lk["text"]
        b = "<w:b/>" if bold and not lk["bold_font"] else ""
        i = "<w:i/>" if italic and re.search(r"[^\W\d_]", text) else ""
        runs.append(f'<w:r><w:rPr><w:rFonts w:ascii="{_esc(font)}" w:hAnsi="{_esc(font)}" w:cs="{_esc(font)}"/>{b}{i}'
                    f'<w:color w:val="{color}"/><w:sz w:val="{half}"/><w:szCs w:val="{half}"/></w:rPr>'
                    f'<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>')
    if ln.rot == 0:
        x, y, w, h, vert = a, height - ln.y - asc, width, box_h, "horz"
    else:
        # reads upwards: x0..x1 run along y, the baseline is the vertical line x = ln.y with the glyphs left of it;
        # a tall, narrow box whose text Word turns (vert270)
        x, y, w, h, vert = ln.y - asc, height - (a + width), box_h, width, "vert270"
    return (f'<wps:wsp><wps:cNvPr id="{n}" name="Text {n}"/><wps:cNvSpPr txBox="1"/><wps:spPr>'
            f'<a:xfrm><a:off x="{round(x * k)}" y="{round(y * k)}"/><a:ext cx="{round(w * k)}" cy="{round(h * k)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>'
            f'<wps:txbx><w:txbxContent><w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{lead}" w:lineRule="atLeast"/>'
            f'<w:ind w:left="0" w:right="0" w:firstLine="0"/><w:jc w:val="{jc}"/></w:pPr>{"".join(runs)}</w:p></w:txbxContent></wps:txbx>'
            f'<wps:bodyPr rot="0" vert="{vert}" wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0" upright="1">'
            f'<a:noAutofit/></wps:bodyPr></wps:wsp>')
