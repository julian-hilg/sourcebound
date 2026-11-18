"""What a pptx template says about type and space, merged with the defaults, and text measured.

Every size is in the template's pixels (`width` x `height` of template.yaml, the slide size of
its master): 1 px is 1/96 inch when the master is 1080 px = 28.575 cm wide, so 1 px = 0.75 pt.

A **style** names a text role (title, caption, kpi number, ...):

    {font: body|bold|serif, size: 24, color: ink, line: 1.45, caps: false, spacing: 0.0}

`font` is a role of the design's fonts: `body` is the first of `fonts.body`, `bold` the first of
`fonts.heading` when that is a face of its own ("Firm-Bold"), else `body` set bold, `serif` the
first of `fonts.serif` (else `body`). `color` is a key of the design's `colors`. `line` is the line
height as a multiple of the size, `spacing` the letter spacing in em.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sourcebound import charts

GENERIC = {"serif", "sans-serif", "monospace", "system-ui", "cursive"}

STYLES: dict[str, dict] = {
    "tracker": {"font": "body", "size": 20, "color": "ink_faint", "line": 1.2, "spacing": 0.02},
    "title": {"font": "bold", "size": 46, "color": "primary", "line": 1.16},
    "eyebrow": {"font": "bold", "size": 20, "color": "accent", "line": 1.3, "caps": True, "spacing": 0.14},
    "cover_title": {"font": "bold", "size": 76, "color": "paper", "line": 1.06, "caps": True, "spacing": 0.01},
    "cover_sub": {"font": "serif", "size": 38, "color": "accent_soft", "line": 1.3},
    "cover_note": {"font": "body", "size": 18, "color": "ink_faint", "line": 1.5},
    "caption": {"font": "bold", "size": 26, "color": "primary", "line": 1.25},
    "unit": {"font": "body", "size": 20, "color": "ink_faint", "line": 1.3},
    "source": {"font": "body", "size": 17, "color": "ink_faint", "line": 1.4},
    "body": {"font": "body", "size": 24, "color": "ink", "line": 1.45},
    "kpi_n": {"font": "bold", "size": 56, "color": "primary", "line": 1.1},
    "kpi_t": {"font": "body", "size": 20, "color": "ink_soft", "line": 1.4},
    "comment_head": {"font": "bold", "size": 22, "color": "primary", "line": 1.3},
    "comment": {"font": "body", "size": 21, "color": "ink_soft", "line": 1.42},
    "callout_n": {"font": "bold", "size": 44, "color": "primary", "line": 1.1},
    "callout": {"font": "body", "size": 21, "color": "ink_soft", "line": 1.45},
    "quote": {"font": "serif", "size": 38, "color": "primary", "line": 1.3},
    "quote_by": {"font": "body", "size": 20, "color": "ink_soft", "line": 1.4},
    "table_head": {"font": "bold", "size": 18, "color": "primary", "line": 1.3},
    "table": {"font": "body", "size": 22, "color": "ink", "line": 1.4},
    "table_key": {"font": "bold", "size": 22, "color": "primary", "line": 1.4},
    "source_no": {"font": "bold", "size": 18, "color": "accent", "line": 1.6},
    "source_item": {"font": "body", "size": 21, "color": "ink", "line": 1.4},
    "source_where": {"font": "body", "size": 17, "color": "ink_faint", "line": 1.4},
    "page": {"font": "body", "size": 18, "color": "ink_faint", "line": 1.2, "spacing": 0.04},
    "chart": {"size": 22},                    # the label size of chart images
}

SPACING: dict[str, float] = {
    "after_title": 40,       # title -> first block
    "block_gap": 40,         # between blocks
    "caption_gap": 6,        # caption -> unit line
    "exhibit_gap": 20,       # caption block -> panel
    "source_gap": 12,        # panel -> source line
    "panel_top": 40, "panel_right": 36, "panel_bottom": 36, "panel_left": 36,
    "kpi_gap": 24, "comments_gap": 40, "bullet_gap": 20, "paragraph_gap": 16,
    "cover_gap": 32,         # cover title -> subtitle
}

LIMITS = {"title_lines": 3, "cover_title_lines": 4, "empty_warn_pct": 25}


def merged(template: dict) -> tuple[dict, dict, dict]:
    """(styles, spacing, limits) of a template: the defaults with template.yaml on top."""
    styles = copy.deepcopy(STYLES)
    for role, s in (template.get("styles") or {}).items():
        styles[role] = {**styles.get(role, {}), **(s or {})}
    return styles, {**SPACING, **(template.get("spacing") or {})}, {**LIMITS, **(template.get("limits") or {})}


# ------------------------------------------------------------------ fonts of the design
@dataclass
class Face:
    name: str                 # what the slide asks for (a:latin typeface)
    bold: bool                # set bold on top of it (only when the design has no bold face of its own)
    file: Path | None         # the file used to measure; None: measured with a stand-in


def _first(names) -> str | None:
    return next((n for n in names or [] if n not in GENERIC), None)


def faces(design: dict) -> dict[str, Face]:
    fonts = design.get("fonts") or {}
    body = _first(fonts.get("body")) or "Arial"
    head = _first(fonts.get("heading")) or body
    serif = _first(fonts.get("serif")) or body
    out = {"body": Face(body, False, charts.font_file(body, design=design))}
    if head != body:
        out["bold"] = Face(head, False, charts.font_file(head, design=design))
    else:
        out["bold"] = Face(body, True, charts.font_file(body, weight=700, design=design))
    out["serif"] = Face(serif, False, charts.font_file(serif, design=design))
    return out


def missing(fs: dict[str, Face]) -> list[str]:
    return sorted({f.name for f in fs.values() if f.file is None})


@lru_cache(maxsize=None)
def _stand_in() -> str:
    import matplotlib
    return str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf")


@lru_cache(maxsize=256)
def _pil(path: str, size10: int):
    from PIL import ImageFont
    return ImageFont.truetype(path, size10 / 10)


class Measure:
    """Text widths and line breaks as the slide will set them (within a few per cent)."""

    SAFETY = 1.03            # PowerPoint sets text a little wider than the font's advance widths

    def __init__(self, design: dict):
        self.faces = faces(design)

    def face(self, style: dict) -> Face:
        return self.faces.get(style.get("font") or "body") or self.faces["body"]

    def width(self, text: str, style: dict, size: float | None = None) -> float:
        if not text:
            return 0.0
        size = float(size or style["size"])
        f = self.face(style)
        s = text.upper() if style.get("caps") else text
        w = _pil(str(f.file or _stand_in()), round(size * 10)).getlength(s.replace(" ", " "))
        if f.bold and f.file is not None and f.file.name.lower().find("bold") < 0:
            w *= 1.05                                           # bold set on a regular file
        w += float(style.get("spacing") or 0) * size * max(len(s) - 1, 0)
        return w * self.SAFETY

    def lines(self, text: str, style: dict, maxw: float, size: float | None = None) -> list[str]:
        """Greedy line breaks as PowerPoint sets them: at spaces and after a hyphen inside a word, never
        at a non-breaking space; a piece longer than the line stays whole."""
        out: list[str] = []
        for para in str(text or "").split("\n"):
            cur = ""
            for word in para.split(" "):
                for i, piece in enumerate(re.findall(r"[^-]+-*|-+", word) or [""]):
                    glue = " " if i == 0 else ""
                    trial = f"{cur}{glue}{piece}" if cur else piece
                    if cur and self.width(trial, style, size) > maxw:
                        out.append(cur)
                        cur = piece
                    else:
                        cur = trial
            out.append(cur)
        return out

    def height(self, text: str, style: dict, maxw: float, size: float | None = None) -> float:
        size = float(size or style["size"])
        return len(self.lines(text, style, maxw, size)) * size * float(style.get("line") or 1.2)

    def too_wide(self, text: str, style: dict, maxw: float, size: float | None = None) -> bool:
        words = str(text or "").replace("\n", " ").split(" ")
        return any(self.width(p, style, size) > maxw + 0.5 for w in words for p in re.findall(r"[^-]+-*|-+", w))
