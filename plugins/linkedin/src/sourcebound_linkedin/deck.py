"""A deck: what `slides.yaml` of a piece says, checked and made ready for the template.

    deck:    title, lang, tracker, width, height, prefix
    slides:  - {title, blocks: [...], source, note}        a content slide
             - {layout: cover, eyebrow, title, sub, note}   a cover

Text anywhere may hold `{{result:key}}` (a recorded number) and `[@W-0001]` (a registered
source).  A numeric field (`value`, `max`, `pos`, ...) may be one `{{result:key}}`: then the
recorded value is used, not its display text.  `prepare` returns the deck with all of that
resolved and the chart geometry computed; `problems` lists what is wrong without a browser.
"""
from __future__ import annotations

import copy
import re

from sourcebound import render

RESULT = re.compile(r"\{\{result:([^}]+)\}\}")
CITE_GROUP = re.compile(r"\[([^\[\]]*@[A-Za-z][^\[\]]*)\]")
CITE_KEY = re.compile(r"@([A-Za-z][\w:.-]*\w)")
NUMERIC = {"value", "max", "min", "pos", "start", "width", "span", "ext", "height", "label_width", "gutter", "y"}

# type -> (required fields, the field that holds a list of dicts and what each needs)
BLOCKS: dict[str, tuple[tuple, str | None, tuple]] = {
    "kpis": ((), "items", ("n", "t")),
    "bars": ((), None, ()),
    "columns": ((), "items", ("label", "value")),
    "line": (("x", "series"), "series", ("label", "values")),
    "gantt": (("ticks",), "rows", ("span",)),
    "day": ((), "events", ("pos", "time")),
    "timeline": ((), "events", ("pos", "time")),
    "windows": (("months",), "windows", ("label", "start", "width")),
    "table": (("rows",), None, ()),
    "bullets": (("items",), None, ()),
    "text": ((), None, ()),
    "comments": ((), "items", ("text",)),
    "callout": (("n", "text"), None, ()),
    "quote": (("text",), None, ()),
    "sources": ((), None, ()),
}


def _walk(node, fn, key=None):
    if isinstance(node, dict):
        return {k: _walk(v, fn, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, fn, key) for v in node]
    return fn(node, key)


def strings(node) -> list[str]:
    out: list[str] = []
    _walk(node, lambda v, k: out.append(v) or v if isinstance(v, str) else v)
    return out


def used_results(data: dict) -> list[str]:
    return sorted({k.strip() for s in strings(data) for k in RESULT.findall(s)})


def used_sources(data: dict) -> list[str]:
    seen: list[str] = []
    for s in strings(data):
        for k in CITE_KEY.findall(s):
            if k not in seen:
                seen.append(k)
    return seen


def _source_text(key: str, doc, *, long: bool) -> str:
    """A source in a source line: "Publisher" or "Publisher, Title"."""
    label = render.cite_label(key, doc)
    if label is None:
        return key
    title = (doc.web_sources.get(key) or doc.references.get(key) or {}).get("title")
    return f"{label[0]}, {title}" if long and title and title != label[0] else label[0]


def resolve(data: dict, doc) -> dict:
    """Numbers and sources filled in. Unknown keys stay visible as `?key`; `problems` reports them."""
    def text(value, key):
        if not isinstance(value, str):
            return value
        whole = RESULT.fullmatch(value.strip())
        if whole and key in NUMERIC:
            r = doc.results.get(whole.group(1).strip())
            return r["value"] if r and isinstance(r.get("value"), (int, float)) else value
        s = RESULT.sub(lambda m: str(doc.results[m.group(1).strip()]["display"]) if m.group(1).strip() in doc.results
                       else f"?{m.group(1).strip()}", value)
        if key in {"source", "where"}:                  # a source line names its sources in words
            s = CITE_GROUP.sub(lambda m: "; ".join(_source_text(k, doc, long=True) for k in CITE_KEY.findall(m.group(1))), s)
            return CITE_KEY.sub(lambda m: _source_text(m.group(1), doc, long=False), s)

        def cite(m):
            labels = [render.cite_label(k, doc) or (k, "") for k in CITE_KEY.findall(m.group(1))]
            return "(" + "; ".join(f"{w} {y}".strip() for w, y in labels) + ")"
        return CITE_GROUP.sub(cite, s)
    return _walk(copy.deepcopy(data), text)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def problems(data: dict, doc, design: dict) -> list[str]:
    """What stops a render, found without a browser: structure, values, results, sources, design rules."""
    out: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list) or not data["slides"]:
        return ["slides.yaml needs `slides:` with at least one slide (and `deck:` with a title)"]
    for k in used_results(data):
        if k not in doc.results:
            out.append(f"result {k} is used but not recorded")
    for k in used_sources(data):
        if render.cite_label(k, doc) is None:
            out.append(f"source {k} is cited but not registered (sb snap URL, or sb doc FILE)")
    deck = data.get("deck") or {}
    for dim, low, high in (("width", 400, 4000), ("height", 400, 4000)):
        if dim in deck and not (_num(deck[dim]) and low <= deck[dim] <= high):
            out.append(f"deck.{dim} must be a number of pixels between {low} and {high}")
    solved = resolve(data, doc)
    for n, s in enumerate(solved["slides"], 1):
        where = f"slide {n}"
        if not isinstance(s, dict):
            out.append(f"{where}: must be a mapping with `title` and `blocks`")
            continue
        if not str(s.get("title") or "").strip():
            out.append(f"{where}: needs a title (the one statement the slide makes)")
        if s.get("layout") == "cover":
            continue
        blocks = s.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            out.append(f"{where}: needs `blocks`")
            continue
        charts = [b for b in blocks if isinstance(b, dict) and b.get("type") not in {"comments", "sources", "bullets", "text", "quote", "callout"}]
        only_sources = all(isinstance(b, dict) and b.get("type") == "sources" for b in blocks)
        if charts and not only_sources and "source" not in s:
            out.append(f"{where}: an exhibit needs a source line (`source: ...`, or `source: false` for the slide's own material)")
        for i, b in enumerate(blocks, 1):
            at = f"{where}, block {i}"
            if not isinstance(b, dict) or b.get("type") not in BLOCKS:
                out.append(f"{at}: `type` must be one of {', '.join(sorted(BLOCKS))}")
                continue
            kind = b["type"]
            at = f"{where}, {kind}"
            required, listed, each = BLOCKS[kind]
            for f in required:
                if b.get(f) in (None, "", []):
                    out.append(f"{at}: `{f}` is missing")
            if listed:
                rows = b.get(listed)
                if not isinstance(rows, list) or not rows:
                    out.append(f"{at}: `{listed}` must be a list with at least one entry")
                    continue
                for r in rows:
                    for f in each:
                        if not isinstance(r, dict) or r.get(f) in (None, ""):
                            out.append(f"{at}: every entry of `{listed}` needs `{f}`")
                            break
            out += [f"{at}: {x}" for x in _values(kind, b, design)]
    return list(dict.fromkeys(out))


def _values(kind: str, b: dict, design: dict) -> list[str]:
    out: list[str] = []
    one = bool((design.get("charts") or {}).get("highlight_one", True))
    if kind == "bars":
        groups = b.get("groups") or ([{"rows": b["rows"]}] if b.get("rows") else [])
        if not groups:
            return ["`groups` (each with `rows`) or `rows` is missing"]
        rows = [r for g in groups for r in (g.get("rows") or []) if isinstance(r, dict)]
        if any(not _num(r.get("value")) or r["value"] < 0 for r in rows):
            out.append("every row needs a `value` that is a number of 0 or more")
        elif "max" in b and (not _num(b["max"]) or b["max"] <= 0 or any(r["value"] > b["max"] for r in rows)):
            out.append("`max` must be a number at least as large as the largest value")
        if one and any(sum(1 for r in (g.get("rows") or []) if isinstance(r, dict) and r.get("hi")) > 1 for g in groups):
            out.append("more than one highlighted row in a group; the design highlights one (`hi: true` once)")
    elif kind == "columns":
        items = [c for c in b.get("items") or [] if isinstance(c, dict)]
        if any(not _num(c.get("value")) or c["value"] < 0 for c in items):
            out.append("every column needs a `value` that is a number of 0 or more")
        elif "max" in b and (not _num(b["max"]) or any(c["value"] > b["max"] for c in items)):
            out.append("`max` must be a number at least as large as the largest value")
        if one and sum(1 for c in items if c.get("hi")) > 1:
            out.append("more than one highlighted column; the design highlights one")
        if len(items) > 12:
            out.append("more than 12 columns do not fit a slide: aggregate, or use a line")
    elif kind == "line":
        x, series = b.get("x") or [], [s for s in b.get("series") or [] if isinstance(s, dict)]
        for s in series:
            vals = s.get("values") or []
            if len(vals) != len(x):
                out.append(f"series “{s.get('label')}” has {len(vals)} values for {len(x)} x positions")
            elif any(v is not None and not _num(v) for v in vals) or sum(1 for v in vals if v is not None) < 2:
                out.append(f"series “{s.get('label')}” needs at least two numbers (null marks a gap)")
        if one and sum(1 for s in series if s.get("hi")) > 1:
            out.append("more than one highlighted series; the design highlights one")
        if len(series) > 6:
            out.append("more than 6 series cannot be labelled at their ends: show fewer")
    elif kind == "gantt":
        n = len(b.get("ticks") or [])
        for r in b.get("rows") or []:
            if not isinstance(r, dict) or not _num(r.get("span")):
                continue
            start, ext = r.get("start", 0), r.get("ext", 0)
            if not all(isinstance(v, int) for v in (r["span"], start, ext)) or r["span"] < 1 or start < 0 or start + r["span"] + ext > n:
                out.append(f"row “{r.get('label') or r.get('sub')}”: start + span + ext must be whole numbers within the {n} ticks")
    elif kind in {"day", "timeline"}:
        for e in b.get("events") or []:
            if isinstance(e, dict) and (not _num(e.get("pos")) or not 0 <= e["pos"] <= 100):
                out.append(f"event “{e.get('time')}”: `pos` is a position on the axis from 0 to 100")
            if isinstance(e, dict) and e.get("align") not in (None, "left", "right"):
                out.append(f"event “{e.get('time')}”: `align` is left or right")
    elif kind == "windows":
        for w in b.get("windows") or []:
            if isinstance(w, dict) and not (_num(w.get("start")) and _num(w.get("width")) and 0 <= w["start"] and w["width"] > 0 and w["start"] + w["width"] <= 100):
                out.append(f"window “{w.get('label')}”: `start` and `width` are percentages of the axis, together at most 100")
    elif kind == "table":
        rows = b.get("rows") or []
        if not all(isinstance(r, list) for r in rows) or len({len(r) for r in rows if isinstance(r, list)} | ({len(b["columns"])} if b.get("columns") else set())) > 1:
            out.append("every row needs as many cells as there are columns")
    elif kind == "text":
        if not (b.get("paragraphs") or b.get("text")):
            out.append("`text` or `paragraphs` is missing")
    elif kind == "sources":
        if b.get("items") not in (None, "auto") and not isinstance(b.get("items"), list):
            out.append("`items` is a list of {text, where}, or `auto` for every source the piece cites")
    return out


# ------------------------------------------------------------------ geometry for the template
def _fmt(v, german: bool) -> str:
    s = f"{v:g}" if _num(v) else str(v)
    return s.replace(".", ",") if german and _num(v) else s


def _pct(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 3)


def prepare(data: dict, doc, template: dict, design: dict | None = None) -> dict:
    """The deck as the template takes it: resolved, with defaults and chart geometry."""
    solved = resolve(data, doc)
    deck = {"title": doc.title, "lang": doc.lang, **(solved.get("deck") or {})}
    deck.setdefault("tracker", deck["title"])
    deck["width"] = int(deck.get("width") or template.get("width") or 1080)
    deck["height"] = int(deck.get("height") or template.get("height") or 1350)
    german = str(deck["lang"]).startswith("de")
    slides = []
    for s in solved["slides"]:
        s = dict(s)
        if s.get("source") in (False, None, "none"):
            s["source"] = ""
        s["blocks"] = [_block(dict(b), doc, deck, german, design or {}) for b in s.get("blocks") or []]
        slides.append(s)
    return {"deck": deck, "slides": slides}


def _block(b: dict, doc, deck: dict, german: bool, design: dict) -> dict:
    kind = b["type"] = "day" if b["type"] == "timeline" else b["type"]
    if kind == "bars":
        groups = b.get("groups") or [{"label": "", "rows": b.pop("rows")}]
        top = b.get("max") or max(r["value"] for g in groups for r in g["rows"]) or 1
        for g in groups:
            for r in g["rows"]:
                r["pct"] = _pct(r["value"] / top * 80)        # a fifth of the track is room for the value label
                r.setdefault("text", _fmt(r["value"], german))
        b["groups"] = groups
    elif kind == "columns":
        top = b.get("max") or max(c["value"] for c in b["items"]) or 1
        b.setdefault("height", 420)
        for c in b["items"]:
            c["pct"] = _pct(c["value"] / top * 82)        # the rest of the height is room for the value label
            c.setdefault("text", _fmt(c["value"], german))
    elif kind == "line":
        vals = [v for s in b["series"] for v in s["values"] if v is not None]
        lo = b["min"] if _num(b.get("min")) else min(vals)
        hi = b["max"] if _num(b.get("max")) else max(vals)
        pad = (hi - lo) * 0.06 or 1.0
        lo, hi = (lo if _num(b.get("min")) else lo - pad), (hi if _num(b.get("max")) else hi + pad)
        n = len(b["x"])
        y = lambda v: round(100 - (v - lo) / (hi - lo) * 100, 3)
        x = lambda i: round(i / (n - 1) * 100, 3) if n > 1 else 50.0
        b.setdefault("height", 460)
        b.setdefault("gutter", 220)
        # a design that highlights one series draws the others in the neutral colour; otherwise the palette is used
        mono = bool((design.get("charts") or {}).get("highlight_one", True)) and any(s.get("hi") for s in b["series"])
        for k, s in enumerate(sorted(b["series"], key=lambda s: bool(s.get("hi"))), 1):   # the highlighted line is drawn last, on top
            pts = [(i, v) for i, v in enumerate(s["values"]) if v is not None]
            s["points"] = " ".join(f"{x(i)},{y(v)}" for i, v in pts)
            s["end_y"] = y(pts[-1][1])
            s["n"] = 0 if mono else min(k + 1, 6)
            if "end_text" not in s:
                s["end_text"] = _fmt(pts[-1][1], german) if b.get("end_values", True) else ""
        b["series"] = sorted(b["series"], key=lambda s: bool(s.get("hi")))
        b["refs"] = [{"y": y(r["y"]), "label": r.get("label", _fmt(r["y"], german))} for r in b.get("refs") or [] if _num(r.get("y"))]
        b["xticks"] = [{"x": x(i), "label": str(t), "first": i == 0, "last": i == n - 1} for i, t in enumerate(b["x"]) if str(t) != ""]
    elif kind == "gantt":
        b.setdefault("label_width", 290)
        b.setdefault("corner", "")
        for r in b["rows"]:
            r.setdefault("start", 0)
            r.setdefault("label", "")
    elif kind == "day":
        for e in b["events"]:
            e.setdefault("below", None)
            e.setdefault("align", None)
            e.setdefault("what", "")
    elif kind == "windows":
        b["step"] = round(100 / len(b["months"]), 4)
    elif kind == "table":
        cols = len(b["rows"][0]) if b["rows"] else 0
        cell = re.compile(r"[\s+\-−–]?[\d.,\s]+(?:\s?[%‰])?|[–—-]")
        b["numeric"] = [i for i in range(cols) if all(cell.fullmatch(str(r[i]).strip() or "-") for r in b["rows"])]
        b.setdefault("highlight", [])
        b.setdefault("key", True)
        b.setdefault("columns", [])
    elif kind == "text":
        b["paragraphs"] = b.get("paragraphs") or [p for p in str(b.get("text", "")).split("\n\n") if p.strip()]
    elif kind == "sources":
        if b.get("items") in (None, "auto"):
            keys = list(dict.fromkeys(render.cited(doc.text) + used_sources(doc.data.get("slides") or {})))
            b["items"] = [{"text": _source_item(k, doc), "where": _where(k, doc)} for k in keys]
    return b


def _source_item(key: str, doc) -> str:
    web = doc.web_sources.get(key)
    if web:
        who = render.cite_label(key, doc)[0]
        return f"{who}: {web.get('title')}" if web.get("title") and web.get("title") != who else who
    return render.source_line(key, doc)


def _where(key: str, doc) -> str:
    url = str((doc.web_sources.get(key) or {}).get("url") or (doc.references.get(key) or {}).get("url") or "")
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else ""


def alt_text(slide: dict) -> str:
    """What a slide shows, in words (for the image's alternative text)."""
    parts = [str(slide.get("title") or "")]
    for b in slide.get("blocks") or []:
        name = ", ".join(x for x in (b.get("name"), b.get("unit")) if x)
        if b["type"] == "bars":
            rows = "; ".join((f"{g['label']}: " if g.get("label") else "") + ", ".join(f"{r['label']} {r['text']}" for r in g["rows"]) for g in b["groups"])
            parts.append(f"{name}: {rows}" if name else rows)
        elif b["type"] == "columns":
            parts.append((name + ": " if name else "") + "; ".join(f"{c['label']} {c['text']}" for c in b["items"]))
        elif b["type"] == "line":
            parts.append((name + ": " if name else "") + "; ".join(f"{s['label']} {s.get('end_text', '')}".strip() for s in b["series"]))
        elif b["type"] == "kpis":
            parts.append("; ".join(f"{k['n']} {k['t']}" for k in b["items"]))
        elif b["type"] == "day":
            parts.append((name + ": " if name else "") + "; ".join(f"{e['time']} {e['what']}".strip() for e in b["events"]))
        elif b["type"] == "windows":
            parts.append((name + ": " if name else "") + "; ".join(f"{w['label']} {w.get('dates', '')}".strip() for w in b["windows"]))
        elif b["type"] == "gantt":
            parts.append((name + ": " if name else "") + "; ".join(" ".join(x for x in (r.get("label"), r.get("sub")) if x) for r in b["rows"]))
        elif b["type"] == "comments":
            parts.append(" ".join(f"{c.get('head', '')}: {c['text']}".lstrip(": ") for c in b["items"]))
        elif name:
            parts.append(name)
    if slide.get("layout") == "cover" and slide.get("sub"):
        parts.append(str(slide["sub"]))
    return re.sub(r"\s+", " ", ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())).strip() + "."
