"""The `pptx` renderer: a piece's slides.yaml -> one PowerPoint file in a template's master.

The deck is read, checked and filled exactly as for the slides plugin (numbers, sources,
non-breaking spaces: `sourcebound_linkedin.deck`). Then every slide is laid out here, without a
browser: text is measured with the design's font files, blocks are stacked in the body area of
the master's content layout, and anything that does not fit stops the render before a file is
written. Text (titles, kpis, bullets, tables, comments, sources, source lines) is PowerPoint
text that can be edited; charts are images drawn by `sourcebound.charts` in the design's chart
style.

Files in the output folder:
    <prefix>.pptx                      one slide per deck slide
    charts/<prefix>_s<n>_<k>.png       the chart images placed on the slides
    layout.json                        what was measured, which fonts were found, what was adjusted
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from sourcebound import charts
from sourcebound_linkedin import deck as decks

from . import master as m
from .style import Measure, merged, missing

EXHIBITS = {"kpis", "table", *charts.CHART_TYPES}
TEXT_BLOCKS = {"bullets", "text", "comments", "callout", "quote", "sources"}
A = m.A


# ------------------------------------------------------------------ what the layout produces
@dataclass
class Para:
    runs: list[tuple[str, dict]]               # (text, style)
    style: dict                                # paragraph: size and line height from here
    align: str = "left"
    before: float = 0.0                        # px above
    bullet: dict | None = None                 # {"color": hex, "indent": px}


@dataclass
class Op:
    kind: str                                  # text | rect | line | image | table | placeholder
    box: tuple = ()                            # (x, y, w, h) px
    paras: list = field(default_factory=list)
    anchor: str = "top"
    color: str = ""
    width: float = 1.0
    dash: bool = False
    block: dict | None = None                  # image: the chart block
    alt: str = ""
    role: str = ""                             # placeholder role
    table: dict | None = None
    name: str = ""


@dataclass
class SlidePlan:
    n: int
    layout: str                                # cover | content
    ops: list[Op] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    space: dict = field(default_factory=dict)


# ------------------------------------------------------------------ the template
def master_path(template: dict) -> Path:
    return Path(template["folder"]) / str(template.get("master") or "master.pptx")


def layouts(template: dict) -> dict:
    """{cover: {name, placeholders, stack}, content: {...}} with defaults."""
    lay = template.get("layouts") or {}
    out = {}
    for role, default_name, default_ph in (
            ("cover", "Cover", {"eyebrow": "Eyebrow", "title": "Title", "sub": "Subtitle", "note": "Note"}),
            ("content", "Content", {"tracker": "Tracker", "title": "Title", "body": "Body", "page": "Page"})):
        x = lay.get(role) or {}
        out[role] = {"name": x.get("name") or default_name, "placeholders": {**default_ph, **(x.get("placeholders") or {})},
                     "stack": x.get("stack") or (["title", "sub"] if role == "cover" else [])}
    return out


def _placeholder_boxes(prs, template: dict, emu_px: float) -> tuple[dict, list[str]]:
    """{layout role: {placeholder role: (idx, (x, y, w, h) px)}} and what is missing."""
    boxes, problems = {}, []
    for role, spec in layouts(template).items():
        try:
            lay = m.layout(prs, spec["name"])
        except KeyError as e:
            problems.append(f"template {template['id']}: {e.args[0]} in {master_path(template).name}")
            continue
        found = {}
        for ph in lay.placeholders:
            found[ph.name] = (ph.placeholder_format.idx, tuple(v / emu_px for v in (ph.left, ph.top, ph.width, ph.height)))
        boxes[role] = {}
        for prole, name in spec["placeholders"].items():
            if name in found:
                boxes[role][prole] = found[name]
            elif prole in ("title", "body"):
                problems.append(f"template {template['id']}: layout {spec['name']!r} has no placeholder named {name!r} "
                                f"(the {prole}; it has: {', '.join(found) or 'none'})")
    return boxes, problems


# ------------------------------------------------------------------ colours and styles
def _colors(design: dict) -> dict:
    c = {k: charts._hex(v) for k, v in design["colors"].items() if isinstance(v, str) and v.startswith("#")}
    c.setdefault("hair", charts.mix(c["ink"], c["paper"], 0.22))
    c.setdefault("hair_soft", charts.mix(c["ink"], c["paper"], 0.12))
    return c


class Ctx:
    """Everything a slide's layout needs: measure, styles, spacing, colours, language."""

    def __init__(self, doc, template: dict, design: dict, deck: dict):
        self.styles, self.sp, self.limits = merged(template)
        self.measure = Measure(design)
        self.colors = _colors(design)
        self.design = design
        self.template = template
        self.german = str(deck.get("lang") or "").startswith("de")
        self.lang = "de" if self.german else "en"
        self.panel = bool(template.get("panel", False))
        self.panel_color = charts._hex((design.get("charts") or {}).get("panel") or design["colors"]["surface"])
        num = template.get("numbering") or {}
        cap = (design.get("charts") or {}).get("caption") or {}
        tcap = (design.get("charts") or {}).get("table_caption") or {}
        self.fig_prefix = (num.get("figure") or cap.get("prefix") or {}).get(self.lang) if (num or cap) else None
        self.tab_prefix = (num.get("table") or tcap.get("prefix") or {}).get(self.lang) if (num or tcap) else None
        self.num_sep = num.get("separator") or cap.get("separator") or " – "
        self.source_prefix = ((design.get("text") or {}).get("source_prefix") or {}).get(self.lang, "Source: ")
        self.chart_px = float(self.styles.get("chart", {}).get("size") or 22)

    def st(self, role: str, **over) -> dict:
        s = dict(self.styles[role])
        s.update(over)
        token = s.get("color") or "ink"
        if token not in self.colors:
            raise KeyError(f"style {role}: colour {token!r} is not in the design")
        return s

    def hex(self, token: str) -> str:
        return self.colors[token]

    def h(self, text: str, style: dict, w: float) -> float:
        return self.measure.height(text, style, w)

    def para(self, text: str, role: str, **kw) -> Para:
        st = self.st(role)
        return Para([(text, st)], st, **kw)

    def text_op(self, x, y, w, paras: list[Para], name: str = "") -> tuple[Op, float]:
        h = sum(p.before + self.para_h(p, w) for p in paras)
        return Op("text", (x, y, w, h), paras, name=name), h

    def para_h(self, p: Para, w: float) -> float:
        indent = (p.bullet or {}).get("indent", 0)
        text = "".join(t for t, _ in p.runs)
        return self.measure.height(text, p.style, w - indent)


# ------------------------------------------------------------------ blocks
def _caption(ctx: Ctx, b: dict, number: int | None) -> list[Para]:
    out = []
    if b.get("name"):
        st = ctx.st("caption")
        runs = []
        if number and (ctx.tab_prefix if b["type"] == "table" else ctx.fig_prefix):
            runs.append(((ctx.tab_prefix if b["type"] == "table" else ctx.fig_prefix) + str(number) + ctx.num_sep, st))
        runs.append((b["name"], st))
        out.append(Para(runs, st))
    if b.get("unit"):
        out.append(ctx.para(b["unit"], "unit", before=ctx.sp["caption_gap"] if out else 0))
    return out


def _source_paras(ctx: Ctx, source: str, note: str) -> list[Para]:
    out = []
    if note:
        out.append(ctx.para(note, "source"))
    if source:
        out.append(ctx.para(ctx.source_prefix + source, "source"))
    return out


def _kpis(ctx: Ctx, b: dict, x, y, w, wide: bool) -> tuple[list[Op], float, list[str]]:
    items = b["items"]
    n = len(items)
    cols = n if n <= 3 or (wide and n <= 4) else (2 if n == 4 else 3)
    gap = ctx.sp["kpi_gap"]
    cw = (w - gap * 2 * (cols - 1)) / cols
    sn, stt = ctx.st("kpi_n"), ctx.st("kpi_t")
    ops, probs = [], []
    size = float(sn["size"])
    widest = max(ctx.measure.width(str(k["n"]), sn) for k in items)
    if widest > cw:                                     # the numbers get smaller together, to 60 % at most
        size = max(size * cw / widest * 0.98, size * 0.6)
        if ctx.measure.width(max((str(k["n"]) for k in items), key=lambda s: ctx.measure.width(s, sn)), sn, size) > cw + 2:
            probs.append(f"kpis: “{max(items, key=lambda k: len(str(k['n'])))['n']}” is too wide for its column even at 60 % size")
    sn = dict(sn, size=size)
    row_h_list = []
    rows = [items[i:i + cols] for i in range(0, n, cols)]
    for row in rows:
        row_h_list.append(max(size * float(sn["line"]) + 12 + ctx.h(str(k["t"]), stt, cw) for k in row))
    yy = y
    for r, row in enumerate(rows):
        for c, k in enumerate(row):
            xx = x + c * (cw + gap * 2)
            if c > 0:
                ops.append(Op("line", (xx - gap, yy, 0, row_h_list[r]), color=ctx.hex("hair"), width=1))
            ops.append(Op("text", (xx, yy, cw, size * float(sn["line"])), [Para([(str(k["n"]), sn)], sn)], name="Kennzahl" if ctx.german else "Figure"))
            t_op, _ = ctx.text_op(xx, yy + size * float(sn["line"]) + 12, cw, [Para([(str(k["t"]), stt)], stt)])
            ops.append(t_op)
        yy += row_h_list[r] + (32 if r < len(rows) - 1 else 0)
    return ops, yy - y, probs


def _table(ctx: Ctx, b: dict, x, y, w) -> tuple[list[Op], float, list[str]]:
    sh, sc, sk = ctx.st("table_head"), ctx.st("table"), ctx.st("table_key")
    cols = b.get("columns") or []
    rows = [[str(c) for c in r] for r in b["rows"]]
    ncol = max([len(cols)] + [len(r) for r in rows])
    numeric = set(b.get("numeric") or [])
    key = b.get("key", True)
    pad = 20.0

    def cell_style(i):
        return sk if (i == 0 and key) else sc
    natural = []
    for i in range(ncol):
        ws = [ctx.measure.width(r[i], cell_style(i)) for r in rows if i < len(r)]
        if cols and i < len(cols):
            ws.append(ctx.measure.width(str(cols[i]), sh))
        natural.append(max(ws or [0]) + (pad if i < ncol - 1 else 0))
    total = sum(natural)
    if total <= w:
        widths = [nw + (w - total) * nw / total for nw in natural] if total else [w / ncol] * ncol
    else:                                               # numbers keep their width, text columns wrap
        fixed = sum(natural[i] for i in numeric)
        flex = [i for i in range(ncol) if i not in numeric]
        rest = max(w - fixed, w * 0.3)
        flex_total = sum(natural[i] for i in flex) or 1
        widths = [natural[i] if i in numeric else rest * natural[i] / flex_total for i in range(ncol)]
    probs = []
    for i in numeric:
        if natural[i] > widths[i] + 0.5:
            probs.append("table: a column of numbers is wider than the table allows")
            break
    heights, cells = [], []
    if cols:
        hh = max(ctx.h(str(c), sh, widths[i] - (pad if i < ncol - 1 else 0)) for i, c in enumerate(cols)) + 12
        heights.append(hh)
        cells.append([(str(c), sh, "right" if i in numeric else "left") for i, c in enumerate(cols)])
    for r in rows:
        hh = max(ctx.h(r[i], cell_style(i), widths[i] - (pad if i < ncol - 1 else 0)) for i in range(len(r))) + 32
        heights.append(hh)
        cells.append([(r[i] if i < len(r) else "", cell_style(i), "right" if i in numeric else "left") for i in range(ncol)])
    spec = {"widths": widths, "heights": heights, "cells": cells, "head": bool(cols), "pad": pad,
            "head_rule": ctx.hex(sh["color"]), "rule": ctx.hex("hair"), "highlight": set(b.get("highlight") or [])}
    return [Op("table", (x, y, w, sum(heights)), table=spec)], sum(heights), probs


def _exhibit_inner_natural(ctx: Ctx, b: dict, w: float, wide: bool) -> float:
    if b["type"] == "kpis":
        return _kpis(ctx, b, 0, 0, w, wide)[1]
    if b["type"] == "table":
        return _table(ctx, b, 0, 0, w)[1]
    return charts.natural_height(b, width_px=w, text_px=ctx.chart_px)


@dataclass
class Placed:
    natural: float
    minimum: float
    grow: bool
    push: bool
    draw: object                                # (x, y, w, h) -> (ops, problems)


def _plan_block(ctx: Ctx, b: dict, w: float, *, number, source: str, note: str, wide: bool, chart_block: dict | None,
                slide_n: int, k: int) -> Placed:
    t = b["type"]
    sp = ctx.sp
    if t in EXHIBITS:
        cap = _caption(ctx, b, number)
        cap_h = sum(p.before + ctx.para_h(p, w) for p in cap)
        head = cap_h + (sp["exhibit_gap"] if cap else 0)
        padx = (sp["panel_left"] + sp["panel_right"]) if ctx.panel else 0
        pady = (sp["panel_top"] + sp["panel_bottom"]) if ctx.panel else 0
        inner_w = w - padx
        src = _source_paras(ctx, source, note)
        src_h = (sp["source_gap"] + sum(ctx.para_h(p, w) for p in src)) if src else 0
        inner = _exhibit_inner_natural(ctx, b, inner_w, wide)
        is_chart = t in charts.CHART_TYPES
        natural = head + pady + inner + src_h
        minimum = head + pady + (inner * 0.7 if is_chart else inner) + src_h

        def draw(x, y, ww, hh):
            ops, probs = [], []
            if cap:
                op, _ = ctx.text_op(x, y, ww, cap, name="Abbildung" if ctx.german else "Caption")
                ops.append(op)
            py = y + head
            ph = hh - head - src_h
            if ctx.panel:
                ops.append(Op("rect", (x, py, ww, ph), color=ctx.panel_color, name="Panel"))
            ix, iy = x + (sp["panel_left"] if ctx.panel else 0), py + (sp["panel_top"] if ctx.panel else 0)
            ih = ph - pady
            if is_chart:
                ops.append(Op("image", (ix, iy, inner_w, ih), block=chart_block, alt=_alt(b), name=f"chart_{slide_n}_{k}"))
            else:
                sub, used, p2 = (_kpis(ctx, b, ix, 0, inner_w, wide) if t == "kpis" else _table(ctx, b, ix, 0, inner_w))
                off = iy + max((ih - used) / 2, 0) if (b.get("grow") and ctx.panel) else iy
                for o in sub:
                    o.box = (o.box[0], o.box[1] + off, *o.box[2:])
                ops += sub
                probs += p2
            if src:
                op, _ = ctx.text_op(x, py + ph + sp["source_gap"], ww, src, name="Quelle" if ctx.german else "Source")
                ops.append(op)
            return ops, probs
        return Placed(natural, minimum, bool(b.get("grow")), bool(b.get("push")), draw)

    # text blocks
    head_paras = _caption(ctx, b, None)
    head_h = sum(p.before + ctx.para_h(p, w) for p in head_paras) + (sp["exhibit_gap"] if head_paras else 0)

    def with_head(body_draw, body_h):
        def draw(x, y, ww, hh):
            ops = []
            if head_paras:
                op, _ = ctx.text_op(x, y, ww, head_paras)
                ops.append(op)
            sub, probs = body_draw(x, y + head_h, ww)
            return ops + sub, probs
        return Placed(head_h + body_h, head_h + body_h, bool(b.get("grow")), bool(b.get("push")), draw)

    if t == "bullets":
        st = ctx.st("body")
        indent = 32.0
        paras = [Para([(str(i), st)], st, before=sp["bullet_gap"] if j else 0,
                      bullet={"color": ctx.hex("accent"), "indent": indent}) for j, i in enumerate(b["items"])]
        bh = sum(p.before + ctx.para_h(p, w) for p in paras)
        return with_head(lambda x, y, ww: ([ctx.text_op(x, y, ww, paras, name="Liste" if ctx.german else "List")[0]], []), bh)
    if t == "text":
        st = ctx.st("body")
        paras = [Para([(str(p), st)], st, before=sp["paragraph_gap"] if j else 0) for j, p in enumerate(b["paragraphs"])]
        bh = sum(p.before + ctx.para_h(p, w) for p in paras)
        return with_head(lambda x, y, ww: ([ctx.text_op(x, y, ww, paras, name="Text")[0]], []), bh)
    if t == "comments":
        items = b["items"]
        gap = sp["comments_gap"]
        cw = (w - gap * (len(items) - 1)) / len(items)
        sh, stt = ctx.st("comment_head"), ctx.st("comment")
        cols = []
        for c in items:
            ps = ([Para([(str(c["head"]), sh)], sh)] if c.get("head") else []) + [Para([(str(c["text"]), stt)], stt, before=6 if c.get("head") else 0)]
            cols.append(ps)
        bh = 3 + 16 + max(sum(p.before + ctx.para_h(p, cw) for p in ps) for ps in cols)

        def draw_c(x, y, ww):
            ops = []
            for i, ps in enumerate(cols):
                xx = x + i * (cw + gap)
                ops.append(Op("rect", (xx, y, cw, 3), color=ctx.hex("accent"), name="Linie"))
                ops.append(ctx.text_op(xx, y + 19, cw, ps, name="Kommentar" if ctx.german else "Comment")[0])
            return ops, []
        return with_head(draw_c, bh)
    if t == "callout":
        sn, stt = ctx.st("callout_n"), ctx.st("callout")
        ps = [Para([(str(b["n"]), sn)], sn), Para([(str(b["text"]), stt)], stt, before=6)]
        inner = sum(p.before + ctx.para_h(p, w - 23) for p in ps) + 8

        def draw_k(x, y, ww):
            return [Op("rect", (x, y, 3, inner), color=ctx.hex("accent"), name="Linie"),
                    ctx.text_op(x + 23, y + 4, ww - 23, ps, name="Hinweis" if ctx.german else "Callout")[0]], []
        return with_head(draw_k, inner)
    if t == "quote":
        sq, sb = ctx.st("quote"), ctx.st("quote_by")
        ps = [Para([(str(b["text"]), sq)], sq)] + ([Para([(str(b["by"]), sb)], sb, before=20)] if b.get("by") else [])
        inner = sum(p.before + ctx.para_h(p, w - 36) for p in ps) + 16

        def draw_q(x, y, ww):
            return [Op("rect", (x, y, 4, inner), color=ctx.hex("accent"), name="Linie"),
                    ctx.text_op(x + 36, y + 8, ww - 36, ps, name="Zitat" if ctx.german else "Quote")[0]], []
        return with_head(draw_q, inner)
    if t == "sources":
        sno, sit, swh = ctx.st("source_no"), ctx.st("source_item"), ctx.st("source_where")
        rows = []
        for i, s in enumerate(b["items"]):
            ps = [Para([(str(s.get("text", "")), sit)], sit)] + ([Para([(str(s["where"]), swh)], swh, before=2)] if s.get("where") else [])
            rows.append((f"{i + 1:02d}", ps, sum(p.before + ctx.para_h(p, w - 48) for p in ps)))
        bh = sum(rh + (16 if i else 0) + 16 + 1 for i, (_n, _p, rh) in enumerate(rows))

        def draw_s(x, y, ww):
            ops, yy = [], y
            for i, (num, ps, rh) in enumerate(rows):
                yy += 16 if i else 0
                ops.append(Op("text", (x, yy, 48, float(sno["size"]) * float(sno["line"])), [Para([(num, sno)], sno)], name="Nummer"))
                ops.append(ctx.text_op(x + 48, yy, ww - 48, ps, name="Quelle" if ctx.german else "Source")[0])
                yy += rh + 16
                ops.append(Op("line", (x, yy, ww, 0), color=ctx.hex("hair"), width=1))
                yy += 1
            return ops, []
        return with_head(draw_s, bh)
    raise ValueError(f"block type {t} has no pptx layout")


def _alt(b: dict) -> str:
    return decks.alt_text({"title": "", "blocks": [b]}).strip(". ") or str(b.get("name") or b["type"])


# ------------------------------------------------------------------ slides
def _content(ctx: Ctx, s: dict, n: int, total: int, deck: dict, boxes: dict, counters: dict, resolved_blocks: list) -> SlidePlan:
    plan = SlidePlan(n, "content")
    sp = ctx.sp
    W = float(ctx.template.get("width") or 1080)
    wide = W > float(ctx.template.get("height") or 1350)
    tx, ty, tw, _th = boxes["title"][1]
    st_title = ctx.st("title")
    lines = ctx.measure.lines(str(s["title"]), st_title, tw)
    title_h = len(lines) * float(st_title["size"]) * float(st_title["line"])
    if len(lines) > ctx.limits["title_lines"]:
        plan.problems.append(f"slide {n}, title: runs to {len(lines)} lines (at most {ctx.limits['title_lines']}); shorten it")
    if ctx.measure.too_wide(str(s["title"]), st_title, tw):
        plan.problems.append(f"slide {n}, title: a word is wider than the title")
    plan.ops.append(Op("placeholder", (tx, ty, tw, title_h), [Para([(str(s["title"]), st_title)], st_title)], role="title"))
    if "tracker" in boxes:
        tr = ctx.template.get("tracker") or {}
        st_tr = ctx.st("tracker")
        runs = []
        if tr.get("prefix"):
            runs.append((str(tr["prefix"]), dict(st_tr, font=tr.get("prefix_font") or st_tr["font"], color=tr.get("prefix_color") or st_tr["color"])))
            runs.append((" " * int(tr.get("prefix_spaces", 2)), st_tr))
        runs.append((str(deck.get("tracker") or ""), st_tr))
        bx = boxes["tracker"][1]
        plan.ops.append(Op("placeholder", bx, [Para(runs, st_tr)], role="tracker"))
    if "page" in boxes and total > 1:
        pg = ctx.template.get("page") or {}
        st_pg = ctx.st("page", align=pg.get("align") or "right")
        d = int(pg.get("digits") or 2)
        sep = str(pg.get("separator") if pg.get("separator") is not None else " / ")
        runs = [(f"{n:0{d}d}", st_pg), (sep, dict(st_pg, color=pg.get("separator_color") or st_pg["color"])), (f"{total:0{d}d}", st_pg)]
        plan.ops.append(Op("placeholder", boxes["page"][1], [Para(runs, st_pg, align=st_pg["align"])], role="page", anchor="bottom"))

    bx, by, bw, bh = boxes["body"][1]
    top = ty + title_h + sp["after_title"]            # the body follows the title; the placeholder gives width and bottom
    bottom = by + bh
    avail = bottom - top
    blocks = s.get("blocks") or []
    last = max((i for i, b in enumerate(blocks) if b["type"] in EXHIBITS), default=-1)
    placed = []
    for i, b in enumerate(blocks):
        number = None
        if b.get("name") and b["type"] in EXHIBITS:
            key = "tab" if b["type"] == "table" else "fig"
            counters[key] += 1
            number = counters[key]
        placed.append(_plan_block(ctx, b, bw, number=number, source=s.get("source") if i == last else "",
                                  note=s.get("note") if i == last else "", wide=wide,
                                  chart_block=resolved_blocks[i] if i < len(resolved_blocks) else b, slide_n=n, k=i + 1))
    # the source line of a slide without an exhibit: in the footer placeholder, or below the last block
    meta = _source_paras(ctx, s.get("source") or "", s.get("note") or "") if last < 0 else []
    meta_h = 0.0
    if meta and "meta" not in boxes:
        meta_h = sp["block_gap"] + sum(ctx.para_h(p, bw) for p in meta)
    gaps = sp["block_gap"] * max(len(placed) - 1, 0)
    natural = sum(p.natural for p in placed) + gaps + meta_h
    heights = [p.natural for p in placed]
    if natural > avail:                                # charts give up height first, down to 70 %
        short = natural - avail
        room = sum(p.natural - p.minimum for p in placed)
        if room >= short - 0.5:
            heights = [p.natural - (p.natural - p.minimum) * short / room for p in placed]
            plan.warnings.append(f"slide {n}: charts made {short / max(room, 1) * 30:.0f} % lower to fit")
        else:
            over = natural - room - avail
            plan.problems.append(f"slide {n}: the content is {over:.0f} px taller than the body area ({avail:.0f} px); "
                                 "shorten the text, or move a block to another slide")
            heights = [p.minimum for p in placed]
    free = max(avail - (sum(heights) + gaps + meta_h), 0)
    grow = [i for i, p in enumerate(placed) if p.grow]
    if grow and free > 0:
        for i in grow:
            heights[i] += free / len(grow)
        free_left = 0.0
    else:
        free_left = free
    pushed = next((i for i, p in enumerate(placed) if p.push), None)
    plan.space = {"area_px": round(avail), "empty_px": round(free_left),
                  "empty_pct": round(free_left / avail * 100) if avail > 0 else 0}
    if free_left / max(avail, 1) * 100 >= ctx.limits["empty_warn_pct"] and pushed is None:
        plan.warnings.append(f"slide {n}: about {free_left / avail * 100:.0f} % of the body area is empty")
    y = top
    for i, (p, hh) in enumerate(zip(placed, heights)):
        if i == pushed:
            y += free_left
        ops, probs = p.draw(bx, y, bw, hh)
        plan.ops += ops
        plan.problems += [f"slide {n}, {x}" for x in probs]
        y += hh + sp["block_gap"]
    if meta:
        if "meta" in boxes:
            mb = boxes["meta"][1]
            plan.ops.append(Op("placeholder", mb, meta, role="meta", anchor="bottom"))
        else:
            op, _ = ctx.text_op(bx, bottom - (meta_h - sp["block_gap"]), bw, meta, name="Quelle" if ctx.german else "Source")
            plan.ops.append(op)
    return plan


def _cover(ctx: Ctx, s: dict, n: int, boxes: dict, spec: dict) -> SlidePlan:
    plan = SlidePlan(n, "cover")
    fields = {"eyebrow": ("eyebrow", s.get("eyebrow")), "title": ("cover_title", s.get("title")),
              "sub": ("cover_sub", s.get("sub")), "note": ("cover_note", s.get("note"))}
    heights = {}
    for role, (style_role, value) in fields.items():
        if not value or role not in boxes:
            continue
        st = ctx.st(style_role)
        x, y, w, h = boxes[role][1]
        lines = ctx.measure.lines(str(value), st, w)
        heights[role] = len(lines) * float(st["size"]) * float(st["line"])
        if role == "title" and len(lines) > ctx.limits["cover_title_lines"]:
            plan.problems.append(f"slide {n}, cover title: runs to {len(lines)} lines (at most {ctx.limits['cover_title_lines']})")
        if ctx.measure.too_wide(str(value), st, w):
            plan.problems.append(f"slide {n}, cover {role}: a word is wider than its box")
    stack = [r for r in spec.get("stack") or [] if r in heights]
    placed = {}
    if stack:
        bottom = max(boxes[r][1][1] + boxes[r][1][3] for r in stack)
        limit = min(boxes[r][1][1] for r in stack)
        y = bottom
        for r in reversed(stack):
            y -= heights[r]
            placed[r] = y
            y -= ctx.sp["cover_gap"]
        if placed[stack[0]] < limit - 0.5:
            plan.problems.append(f"slide {n}, cover: title and subtitle are {limit - placed[stack[0]]:.0f} px too tall for their space")
    for role, (style_role, value) in fields.items():
        if not value or role not in boxes:
            continue
        st = ctx.st(style_role)
        x, y, w, h = boxes[role][1]
        if role in placed:
            y, h = placed[role], heights[role]
        elif heights[role] > h + 0.5:
            plan.problems.append(f"slide {n}, cover {role}: {heights[role] - h:.0f} px taller than its box")
        plan.ops.append(Op("placeholder", (x, y, w, max(h, heights[role])), [Para([(str(value), st)], st)], role=role))
    return plan


def plan_deck(doc, template: dict, design: dict) -> tuple[dict, list[SlidePlan], Ctx]:
    """The prepared deck and every slide laid out (nothing written)."""
    from pptx import Presentation
    data = doc.data.get("slides")
    prepared = decks.prepare(data, doc, template, design)
    resolved = decks._walk(decks.resolve(data, doc),
                           lambda v, k: decks.keep_together(v) if isinstance(v, str) and k not in decks._NOT_TEXT else v)
    deck = prepared["deck"]
    ctx = Ctx(doc, template, design, deck)
    prs = Presentation(str(master_path(template)))
    emu_px = prs.slide_width / float(template.get("width") or 1080)
    boxes, _ = _placeholder_boxes(prs, template, emu_px)
    specs = layouts(template)
    plans, counters = [], {"fig": 0, "tab": 0}
    total = len(prepared["slides"])
    for n, (s, raw) in enumerate(zip(prepared["slides"], resolved["slides"]), 1):
        if s.get("layout") == "cover":
            plans.append(_cover(ctx, s, n, boxes.get("cover", {}), specs["cover"]))
        else:
            plans.append(_content(ctx, s, n, total, deck, boxes.get("content", {}), counters, raw.get("blocks") or []))
    return prepared, plans, ctx


# ------------------------------------------------------------------ writing the file
def _rpr(parent, style: dict, ctx: Ctx, ptpx: float, lang: str, tag: str = "rPr"):
    face = ctx.measure.face(style)
    st = {**style, "font": face.name, "bold": face.bold, "color": ctx.hex(style.get("color") or "ink")}
    xml = m.text_props(st, ptpx=ptpx, tag=tag)
    el = etree.fromstring(xml.replace(f"<a:{tag} ", f'<a:{tag} xmlns:a="{m.NS["a"]}" lang="{lang}" ', 1))
    parent.append(el)
    return el


def _fill_text(txBody, paras: list[Para], ctx: Ctx, ptpx: float, *, anchor: str = "top") -> None:
    """Replace the paragraphs of a text body with `paras`; insets 0, no autofit, fixed line height."""
    lang = "de-DE" if ctx.german else "en-GB"
    body_pr = txBody.find(A + "bodyPr")
    new_pr = etree.fromstring(m.body_pr(anchor).replace("<a:bodyPr ", f'<a:bodyPr xmlns:a="{m.NS["a"]}" ', 1))
    if body_pr is not None:
        txBody.replace(body_pr, new_pr)
    else:
        txBody.insert(0, new_pr)
    for p in txBody.findall(A + "p"):
        txBody.remove(p)
    for para in paras:
        p = etree.SubElement(txBody, A + "p")
        st = para.style
        size = float(st["size"])
        ppr = etree.SubElement(p, A + "pPr")
        ppr.set("algn", {"left": "l", "right": "r", "center": "ctr"}.get(para.align or st.get("align") or "left", "l"))
        if para.bullet:
            ppr.set("marL", str(round(para.bullet["indent"] * ptpx * m.PT_EMU)))
            ppr.set("indent", str(-round(para.bullet["indent"] * ptpx * m.PT_EMU)))
        else:
            ppr.set("marL", "0")
            ppr.set("indent", "0")
        ln = etree.SubElement(etree.SubElement(ppr, A + "lnSpc"), A + "spcPts")
        ln.set("val", str(round(size * float(st.get("line") or 1.2) * ptpx * 100)))
        etree.SubElement(etree.SubElement(ppr, A + "spcBef"), A + "spcPts").set("val", str(round(para.before * ptpx * 100)))
        etree.SubElement(etree.SubElement(ppr, A + "spcAft"), A + "spcPts").set("val", "0")
        if para.bullet:
            clr = etree.SubElement(ppr, A + "buClr")
            etree.SubElement(clr, A + "srgbClr").set("val", para.bullet["color"].lstrip("#").upper())
            etree.SubElement(ppr, A + "buSzPct").set("val", "45000")
            etree.SubElement(ppr, A + "buFontTx")
            etree.SubElement(ppr, A + "buChar").set("char", "■")
        else:
            etree.SubElement(ppr, A + "buNone")
        for text, rst in para.runs:
            r = etree.SubElement(p, A + "r")
            _rpr(r, rst, ctx, ptpx, lang)
            etree.SubElement(r, A + "t").text = text
        _rpr(p, st, ctx, ptpx, lang, tag="endParaRPr")


def _shape_xml_clean(shape) -> None:
    """Drop the theme style of an added shape (it would add an outline, a shadow or a text colour)."""
    el = shape._element
    style = el.find("{%s}style" % m.NS["p"])
    if style is not None:
        el.remove(style)


def _emu(v: float, emu_px: float) -> int:
    return int(round(v * emu_px))


def write(prs, plans: list[SlidePlan], ctx: Ctx, template: dict, images: dict, out: Path) -> None:
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu
    emu_px = prs.slide_width / float(template.get("width") or 1080)
    ptpx = emu_px / m.PT_EMU
    specs = layouts(template)
    for plan in plans:
        spec = specs[plan.layout]
        lay = m.layout(prs, spec["name"])
        slide = prs.slides.add_slide(lay)
        by_name = {ph.name: ph.placeholder_format.idx for ph in lay.placeholders}
        on_slide = {ph.placeholder_format.idx: ph for ph in slide.placeholders}
        used = set()
        for op in plan.ops:
            E = lambda v: Emu(_emu(v, emu_px))
            if op.kind == "placeholder":
                idx = by_name.get(spec["placeholders"].get(op.role))
                ph = on_slide.get(idx)
                if ph is None:
                    continue
                used.add(idx)
                ph.name = spec["placeholders"][op.role]           # the layout's name, not "Text Placeholder 3"
                x, y, w, h = op.box
                ph.left, ph.top, ph.width, ph.height = E(x), E(y), E(w), E(max(h, 1))
                _fill_text(ph.text_frame._txBody, op.paras, ctx, ptpx, anchor=op.anchor)
            elif op.kind == "text":
                x, y, w, h = op.box
                tb = slide.shapes.add_textbox(E(x), E(y), E(w), E(max(h, 1)))
                if op.name:
                    tb.name = op.name
                _fill_text(tb.text_frame._txBody, op.paras, ctx, ptpx)
            elif op.kind == "rect":
                x, y, w, h = op.box
                r = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(x), E(y), E(w), E(h))
                _shape_xml_clean(r)
                r.fill.solid()
                r.fill.fore_color.rgb = RGBColor.from_string(op.color.lstrip("#").upper())
                r.line.fill.background()
                if op.name:
                    r.name = op.name
            elif op.kind == "line":
                x, y, w, h = op.box
                c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, E(x), E(y), E(x + w), E(y + h))
                _shape_xml_clean(c)
                c.line.color.rgb = RGBColor.from_string(op.color.lstrip("#").upper())
                c.line.width = Emu(_emu(op.width, emu_px))
            elif op.kind == "image":
                x, y, w, h = op.box
                pic = slide.shapes.add_picture(str(images[op.name]), E(x), E(y), E(w), E(h))
                pic.name = op.name
                pic._element.nvPicPr.cNvPr.set("descr", op.alt)
            elif op.kind == "table":
                _write_table(slide, op, ctx, ptpx, emu_px)
        # placeholders the slide does not use would show their prompt in PowerPoint
        for idx, ph in on_slide.items():
            if idx not in used:
                ph._element.getparent().remove(ph._element)


def _write_table(slide, op: Op, ctx: Ctx, ptpx: float, emu_px: float) -> None:
    from pptx.util import Emu
    t = op.table
    x, y, w, h = op.box
    rows, cols = len(t["heights"]), len(t["widths"])
    gf = slide.shapes.add_table(rows, cols, Emu(_emu(x, emu_px)), Emu(_emu(y, emu_px)), Emu(_emu(w, emu_px)), Emu(_emu(h, emu_px)))
    gf.name = "Tabelle" if ctx.german else "Table"
    tbl = gf._element.graphic.graphicData.tbl
    tblPr = tbl.tblPr
    for k in ("firstRow", "bandRow", "firstCol", "lastRow", "lastCol", "bandCol"):
        tblPr.attrib.pop(k, None)
    sid = tblPr.find(A + "tableStyleId")
    if sid is None:
        sid = etree.SubElement(tblPr, A + "tableStyleId")
    sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"          # No Style, No Grid
    table = gf.table
    for i, cw in enumerate(t["widths"]):
        table.columns[i].width = Emu(_emu(cw, emu_px))
    for r, rh in enumerate(t["heights"]):
        table.rows[r].height = Emu(_emu(rh, emu_px))
        head = t["head"] and r == 0
        for c in range(cols):
            text, st, align = t["cells"][r][c]
            cell = table.cell(r, c)
            pad_r = t["pad"] if c < cols - 1 else 0
            cell.margin_left, cell.margin_right = Emu(0), Emu(_emu(pad_r, emu_px))
            cell.margin_top = Emu(0 if head else _emu(16, emu_px))
            cell.margin_bottom = Emu(_emu(12 if head else 16, emu_px))
            _fill_text(cell.text_frame._txBody, [Para([(text, st)], st, align=align)], ctx, ptpx)
            bp = cell.text_frame._txBody.find(A + "bodyPr")
            for k in ("lIns", "tIns", "rIns", "bIns", "anchor", "anchorCtr", "wrap", "rtlCol"):
                bp.attrib.pop(k, None)
            for child in list(bp):
                bp.remove(child)
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.set("anchor", "b" if head else "t")
            for child in list(tcPr):
                tcPr.remove(child)
            for side in ("lnL", "lnR", "lnT", "lnB"):
                ln = etree.SubElement(tcPr, A + side)
                if side == "lnB":
                    ln.set("w", str(_emu(2 if head else 1, emu_px)))
                    sf = etree.SubElement(ln, A + "solidFill")
                    etree.SubElement(sf, A + "srgbClr").set("val", (t["head_rule"] if head else t["rule"]).lstrip("#").upper())
                else:
                    ln.set("w", "0")
                    etree.SubElement(ln, A + "noFill")
            etree.SubElement(tcPr, A + "noFill")


# ------------------------------------------------------------------ renderer and check
def _prefix(deck: dict, doc) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(deck.get("prefix") or doc.name)).strip("-") or "deck"


def render_pptx(doc, template: dict, design: dict, out: Path) -> tuple[list[Path], list[str]]:
    from pptx import Presentation
    prepared, plans, ctx = plan_deck(doc, template, design)
    problems = [p for pl in plans for p in pl.problems]
    if problems:
        raise ValueError("the slides do not fit (no file was written):\n  " + "\n  ".join(problems))
    prefix = _prefix(prepared["deck"], doc)
    chart_dir = out / "charts"
    if chart_dir.is_dir():
        shutil.rmtree(chart_dir)
    for old in out.glob("*.pptx"):
        old.unlink()
    notes: list[str] = []
    images: dict[str, Path] = {}
    for pl in plans:
        for op in pl.ops:
            if op.kind == "image":
                x, y, w, h = op.box
                f = chart_dir / f"{prefix}_s{pl.n}_{op.name.rsplit('_', 1)[-1]}.png"
                charts.render(op.block, design=design, width_px=round(w), height_px=round(h), out=f, lang=ctx.lang,
                              text_px=ctx.chart_px, scale=float(template.get("scale") or 3), notes=notes)
                images[op.name] = f
    prs = Presentation(str(master_path(template)))
    m.remove_slides(prs)
    write(prs, plans, ctx, template, images, out)
    prs.core_properties.title = str(prepared["deck"].get("title") or doc.title)
    prs.core_properties.language = "de-DE" if ctx.german else "en-GB"
    target = out / f"{prefix}.pptx"
    prs.save(str(target))
    fonts_missing = missing(ctx.measure.faces)
    master_fonts = sorted(f for f in m.fonts_in(prs) if charts.font_file(f, design=design) is None)
    layout = {"slides": [{"slide": pl.n, "layout": pl.layout, "space": pl.space, "warnings": pl.warnings} for pl in plans],
              "fonts": {k: {"name": f.name, "file": str(f.file) if f.file else None, "bold_set": f.bold} for k, f in ctx.measure.faces.items()},
              "fonts_missing": fonts_missing, "master_fonts_missing": master_fonts,
              "chart_renderer": charts.renderer(design)[0]}
    (out / "layout.json").write_text(json.dumps(layout, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notes += [w for pl in plans for w in pl.warnings]
    if fonts_missing:
        notes.append(f"missing fonts: {', '.join(fonts_missing)}; text was measured with a stand-in, and PowerPoint will "
                     "substitute them on this machine. Install them, or put the files into the design folder.")
    if master_fonts:
        notes.append(f"the master names fonts this machine does not have: {', '.join(master_fonts)}")
    return [target, out / "layout.json", *sorted(images.values())], notes


def check(doc, template: dict, design: dict) -> list[str]:
    """Before anything is laid out: the deck, the template's master, and what the chart renderer draws."""
    data = doc.data.get("slides")
    if not data:
        return [f"pieces/{doc.name}/slides.yaml is missing: a pptx template renders the deck written there"]
    out = list(decks.problems(data, doc, design))
    f = master_path(template)
    if not f.is_file():
        return out + [f"template {template['id']}: the master {f.name} is missing in {template['folder']}"]
    from pptx import Presentation
    try:
        prs = Presentation(str(f))
    except Exception as e:                              # not a presentation
        return out + [f"template {template['id']}: {f.name} cannot be read ({type(e).__name__}: {e})"]
    w, h = float(template.get("width") or 0), float(template.get("height") or 0)
    if not (w and h):
        out.append(f"template {template['id']}: template.yaml needs `width` and `height` in px (the slide size)")
    elif abs(prs.slide_width / prs.slide_height - w / h) > 0.005:
        out.append(f"template {template['id']}: the master's slide size ({prs.slide_width / 360000:.2f} x "
                   f"{prs.slide_height / 360000:.2f} cm) is not {w:g} x {h:g}")
    deck = (data or {}).get("deck") or {}
    if w and h and (deck.get("width") or deck.get("height")) and (deck.get("width", w), deck.get("height", h)) != (w, h):
        out.append(f"the deck asks for {deck.get('width', w)} x {deck.get('height', h)} px; template {template['id']} is "
                   f"{w:g} x {h:g} (choose a template of that size)")
    _, probs = _placeholder_boxes(prs, template, prs.slide_width / (w or 1080))
    out += probs
    try:
        merged_styles = merged(template)[0]
        colors = _colors(design)
        for role, s in merged_styles.items():
            if s.get("color") and s["color"] not in colors:
                out.append(f"template {template['id']}: style {role} uses colour {s['color']!r}, which design {design.get('id')} does not have")
    except ValueError as e:
        out.append(f"design {design.get('id')}: {e}")
    name, _fn, types, _note = charts.renderer(design)
    for n, s in enumerate(data.get("slides") or [], 1):
        for b in (s.get("blocks") or []) if isinstance(s, dict) else []:
            t = charts.kind(b) if isinstance(b, dict) else ""
            if t in charts.CHART_TYPES and t not in types:
                out.append(f"slide {n}: {t} charts are not supported in pptx yet by chart renderer `{name}`")
    return list(dict.fromkeys(out))
