"""The `slides` renderer: a piece's slides.yaml -> one HTML page, one PNG per slide, one PDF.

The page is laid out in a Chromium, and what was laid out is measured before anything is
photographed: text that overflows, labels that touch, type below the design's minimum, a
colour that is not in the design.  Safe corrections are applied (and listed); anything else
stops the render with the slide, the block and what is wrong.  A deck with a layout problem
never becomes an image.

Files in the output folder:
    <prefix>.html              the deck, self-contained (opens in any browser)
    <prefix>_slide_<n>.png     one image per slide
    <prefix>_carousel.pdf      all slides, one per page (a LinkedIn document post)
    layout.json                what was corrected, what was measured, which fonts were found
    preview.json               the post as it will appear (see post.py)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
from pathlib import Path

from sourcebound import render

from . import browser, deck as decks, post

HERE = Path(__file__).parent / "template"
ALIAS = "SB Design Face"
WEIGHT_WORDS = (("thin", 200), ("light", 300), ("regular", 400), ("book", 400), ("medium", 500), ("semibold", 600),
                ("demi", 600), ("bold", 700), ("black", 900))


# ------------------------------------------------------------------ design -> CSS variables
def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"design: {hex_!r} is not a hex colour like #1f3a5f")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(c):02x}" for c in rgb)


def mix(a: str, b: str, share: float) -> str:
    """`share` of colour a over colour b, as one solid colour (so the colour check can know it)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x * share + y * (1 - share) for x, y in zip(ra, rb)))


def _stack(names: list[str]) -> str:
    generic = {"serif", "sans-serif", "monospace", "system-ui", "cursive"}
    return ", ".join(n if n in generic else '"%s"' % n.replace('"', "") for n in names)


def _data_uri(f: Path) -> str:
    kind = mimetypes.guess_type(f.name)[0] or {".otf": "font/otf", ".ttf": "font/ttf", ".woff2": "font/woff2", ".woff": "font/woff"}.get(f.suffix.lower(), "application/octet-stream")
    return f"data:{kind};base64,{base64.b64encode(f.read_bytes()).decode('ascii')}"


def _faces(design: dict) -> tuple[str, bool, list[str]]:
    """@font-face rules from the design, whether there are any, and files that are missing.

    `fonts.files` lists font files in the design folder (the weight is read from the file name).
    `fonts.faces` says more: {file, weight, style, local: [names the font has when installed]}.
    """
    folder = Path(design["folder"]) if design.get("folder") else None
    rules, missing = [], []
    fonts = design.get("fonts") or {}
    for entry in [*(fonts.get("files") or []), *(fonts.get("faces") or [])]:
        e = {"file": entry} if isinstance(entry, str) else dict(entry)
        name = str(e.get("file") or "")
        weight = e.get("weight") or next((w for word, w in WEIGHT_WORDS if word in name.lower()), 400)
        src = [f'local("{n}")' for n in e.get("local") or []]
        f = folder / name if folder and name else None
        if f and f.is_file():
            src.append(f'url("{_data_uri(f)}")')
        elif name:
            missing.append(name)
        if src:
            rules.append(f'@font-face {{ font-family: "{ALIAS}"; font-weight: {weight}; font-style: {e.get("style", "normal")}; src: {", ".join(src)}; }}')
    return "\n".join(rules), bool(rules), missing


def tokens(design: dict) -> tuple[str, list[str], list[str]]:
    """(CSS with the :root variables, every colour the slides may use, font files named but not found)."""
    c = design["colors"]
    derived = {
        "hair": mix(c["ink"], c["paper"], 0.12),
        "hair-2": mix(c["ink"], c["paper"], 0.22),
        "accent-soft": c.get("accent_soft") or mix(c["accent"], c["paper"], 0.25),
        "on-primary-hair": mix(c["paper"], c["primary"], 0.22),
        "on-primary-soft": mix(c["paper"], c["primary"], 0.6),
    }
    names = {"primary": "primary", "accent": "accent", "ink": "ink", "ink_soft": "ink-soft", "ink_faint": "ink-faint",
             "neutral": "neutral", "surface": "surface", "paper": "paper", "good": "good", "bad": "bad"}
    lines = [f"  --c-{css}: {_hex(_rgb(c[key]))};" for key, css in names.items()]
    lines += [f"  --c-{k}: {v};" for k, v in derived.items()]
    palette = [_hex(_rgb(p)) for p in design.get("palette") or [c["primary"]]]
    palette += [palette[-1]] * (6 - len(palette))
    lines += [f"  --p-{i}: {p};" for i, p in enumerate(palette[:6], 1)]
    fonts = design.get("fonts") or {}
    faces, has_faces, missing = _faces(design)
    first = [ALIAS] if has_faces else []
    weights = {"light": 300, "regular": 400, "medium": 600, **(fonts.get("weights") or {})}
    lines += [f"  --f-body: {_stack(first + list(fonts.get('body') or ['sans-serif']))};",
              f"  --f-heading: {_stack(first + list(fonts.get('heading') or fonts.get('body') or ['sans-serif']))};",
              f"  --f-mono: {_stack(list(fonts.get('mono') or ['monospace']))};",
              *[f"  --w-{k}: {int(v)};" for k, v in weights.items()],
              f"  --logo-h: {int((design.get('logo') or {}).get('height_px') or 72)}px;"]
    allowed = sorted({_hex(_rgb(c[k])) for k in names} | set(derived.values()) | set(palette))
    return faces + ("\n" if faces else "") + ":root {\n" + "\n".join(lines) + "\n}", allowed, missing


def _logo(design: dict, key: str) -> str:
    name = (design.get("logo") or {}).get(key)
    f = Path(design["folder"]) / name if name and design.get("folder") else None
    return _data_uri(f) if f and f.is_file() else ""


# ------------------------------------------------------------------ the page
def _file(template: dict, key: str, default: str) -> str:
    f = Path(template["folder"]) / str(template.get(key) or default)
    return (f if f.is_file() else HERE / default).read_text(encoding="utf-8")


def build_html(doc, template: dict, design: dict) -> tuple[str, dict, list[str]]:
    """(the HTML page, the prepared deck, font files the design names but does not hold)."""
    from jinja2 import ChainableUndefined, Environment
    from markupsafe import Markup
    data = doc.data.get("slides")
    if not data:
        raise ValueError(f"pieces/{doc.name}/slides.yaml is missing: a slides template renders the deck written there")
    prepared = decks.prepare(data, doc, template, design)
    d = prepared["deck"]
    css_tokens, allowed, missing = tokens(design)
    css_tokens += f"\n:root {{ --w: {d['width']}px; --h: {d['height']}px; }}"
    charts = design.get("charts") or {}
    config = {"min_gap_px": charts.get("min_gap_px", 8), "min_font_px": charts.get("min_font_px", 16), "colors": allowed,
              "empty_warn_pct": template.get("empty_warn_pct") or charts.get("empty_warn_pct") or 25}
    lang = "de" if str(d["lang"]).startswith("de") else "en"
    prefix = ((design.get("text") or {}).get("source_prefix") or {}).get(lang, "Source: ")
    logo, inverse = _logo(design, "file"), _logo(design, "file_inverse")
    env = Environment(autoescape=True, undefined=ChainableUndefined)      # a missing optional field is empty, not an error
    css = _file(template, "css", "slides.css")
    own = (template.get("piece_style") or {}).get("css")
    if own:                     # the piece's own adjustments (pieces/<id>/style/style.css), after the template's rules
        css += f"\n\n/* ---- pieces/{doc.name}/style/style.css ---- */\n" + own.replace("</", "<\\/")
    html = env.from_string(_file(template, "html", "slides.html.j2")).render(
        deck=d, slides=prepared["slides"], tokens_css=Markup(css_tokens), css=Markup(css),
        layout_js=Markup(_file(template, "layout", "layout.js")),
        config_json=Markup(json.dumps(config).replace("</", "<\\/")), source_prefix=prefix,
        logo=Markup(logo), logo_inverse=Markup(inverse or logo), logo_needs_invert=bool(logo and not inverse),
        design_name="" if d.get("logo") is False else design.get("name", ""))
    return html, prepared, missing


def _report(dom: str) -> dict:
    m = re.search(r'<script type="application/json" id="sb-report">(.*?)</script>', dom, re.S)
    if not m or not m.group(1).strip():
        raise RuntimeError("the layout script did not finish (no report in the page); open the .html in a browser and look at its console")
    import html as htmlmod
    return json.loads(htmlmod.unescape(m.group(1)))


def _freeze(dom: str) -> str:
    """The laid-out page as a static document: label positions fixed, layout script removed."""
    dom = re.sub(r"<script>.*?</script>", "", dom, flags=re.S)                       # the layout script (the JSON blocks have a type)
    return dom if dom.lstrip().lower().startswith("<!doctype") else "<!doctype html>\n" + dom


def render_slides(doc, template: dict, design: dict, out: Path) -> tuple[list[Path], list[str]]:
    html, prepared, missing_fonts = build_html(doc, template, design)
    d = prepared["deck"]
    prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", str(d.get("prefix") or doc.name)).strip("-") or "deck"
    for old in [*out.glob("*_slide_*.png"), *out.glob("*_carousel.pdf"), *out.glob("*.html")]:
        old.unlink()
    page = out / f"{prefix}.html"
    page.write_text(html, encoding="utf-8")
    files = [page]
    layout: dict = {"browser": None, "width": d["width"], "height": d["height"], "remedies": [], "problems": [], "warnings": [],
                    "fonts": {}, "faces": [], "font_files_missing": missing_fonts}
    exe = browser.find()
    slides = prepared["slides"]
    if exe is None:
        layout["note"] = "Only the HTML was written: the layout was not checked and no image was made. " + browser.HOW
    else:
        dom = browser.dom(exe, page, width=d["width"], height=d["height"])
        report = _report(dom)
        layout.update(browser=exe.name, remedies=report["remedies"], problems=report["problems"], fonts=report["fonts"],
                      warnings=report.get("warnings") or [], faces=report.get("faces") or [], space=report.get("space") or [])
        # The page that was measured becomes the page that is photographed: the corrections are
        # written into it and the script is taken out, so no image can differ from the measurement.
        page.write_text(_freeze(dom), encoding="utf-8")
    missing = missing_typefaces(layout["faces"], layout["fonts"], design)
    if missing:
        used = next((name for name, ok in layout["fonts"].items() if ok and name != ALIAS), "the browser's default")
        layout["font_note"] = (f"missing fonts: {', '.join(missing)}; {used} was used instead. Install them on this machine, "
                               "or put the font files into the design folder (fonts.files in design.yaml).")
    (out / "layout.json").write_text(json.dumps(layout, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    files.append(out / "layout.json")
    if layout["problems"]:
        raise ValueError("the slides do not fit (nothing was photographed; the page is " + page.as_posix() + "):\n  "
                         + "\n  ".join(f"slide {p['slide']}, {p['block']}: {p['what']}" for p in layout["problems"]))
    images: list[Path] = []
    doc_pdf = None
    if exe is not None:
        scale = float(d.get("scale") or template.get("scale") or 2)
        for n in range(1, len(slides) + 1):
            f = out / f"{prefix}_slide_{n}.png"
            browser.screenshot(exe, page, f"s{n}", f, width=d["width"], height=d["height"], scale=scale)
            images.append(f)
        files += images
        if len(slides) > 1:              # one slide is posted as an image: there is nothing to swipe through
            doc_pdf = out / f"{prefix}_carousel.pdf"
            browser.pdf(exe, page, doc_pdf)
            files.append(doc_pdf)
    preview = post.preview(doc, slides, images, doc_pdf, d, layout)
    (out / "preview.json").write_text(json.dumps(preview, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # What was adjusted, what looks thin and what could not be done goes into render.json with the
    # files; `sb render` prints these notes (once).
    notes = [f"slide {r['slide']}, {r['block']}: {r['what']}" for r in layout["remedies"]]
    notes += [f"slide {w['slide']}: {w['what']}" for w in layout["warnings"]]
    notes += [layout[k] for k in ("font_note", "note") if layout.get(k)]
    return files + [out / "preview.json"], notes


def missing_typefaces(faces: list[dict], fonts: dict, design: dict) -> list[str]:
    """The typefaces the page asked for and the machine did not have, as a person would install them.

    A face is named by the name it asks the machine for (`local(...)`), with its weight when the
    face has one weight: "Inter 400, Inter-Bold 700, Source Serif 4".  A family of the design that no
    face describes counts when the browser drew it with the fallback.
    """
    names: dict[str, set] = {}
    for f in faces:
        if f.get("ok"):
            continue
        name = (f.get("local") or [None])[0] or ("the design's font file" if f.get("family") == ALIAS else f.get("family"))
        if not name:
            continue
        w = str(f.get("weight") or "")
        names.setdefault(name, set()).update({w} if re.fullmatch(r"\d+", w) else set())
    described = {f.get("family") for f in faces} | {n for f in faces for n in f.get("local") or []}
    generic = {"serif", "sans-serif", "monospace", "system-ui", "cursive"}
    fams = design.get("fonts") or {}
    for key in ("body", "heading", "serif"):
        first = next((n for n in fams.get(key) or [] if n not in generic), None)
        if first and fonts.get(first) is False and first not in described:
            names.setdefault(first, set())
    return [n + (" " + "/".join(sorted(ws, key=int)) if ws else "") for n, ws in names.items()]


def check(doc, template: dict, design: dict) -> list[str]:
    """Before any browser starts: is the deck there, well formed, and does everything it names exist?"""
    data = doc.data.get("slides")
    if not data:
        return [f"pieces/{doc.name}/slides.yaml is missing: a slides template renders the deck written there"]
    try:
        tokens(design)
    except (ValueError, KeyError) as e:
        return [f"design {design.get('id')}: {e}"]
    return decks.problems(data, doc, design)


def scaffold(folder: Path, design: dict) -> None:
    """The standard slides template, to be changed: layout in slides.css, blocks in slides.html.j2."""
    for f in HERE.iterdir():
        if f.is_file():
            shutil.copy2(f, folder / f.name)
    (folder / "README.md").write_text(
        "# Slides template\n\n"
        "- `template.yaml`: size of a slide and which files are used.\n"
        "- `slides.css`: layout. Colours and fonts are variables that come from the design; a colour value\n"
        "  written here is refused by the layout check.\n"
        "- `slides.html.j2`: one Jinja macro per block type.\n"
        "- `layout.js`: places labels and measures the result. Keep it.\n\n"
        "Render a piece with it: `sb render <piece> --template <this folder's name>`.\n", encoding="utf-8")
