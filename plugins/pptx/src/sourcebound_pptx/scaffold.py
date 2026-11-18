"""A starting pptx template from a design: master.pptx (built here, from python-pptx's blank
presentation) and template.yaml. `sb template new ID --kind pptx --design ID` writes it.

The master has two layouts, `Cover` and `Content`, with placeholders named by role. Colours and
fonts come from the design: its theme carries the design's colours and fonts, and every
placeholder is formatted like the text the renderer writes into it, so a slide added by hand in
PowerPoint looks the same.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import master as m
from .style import faces, merged

WIDTH, HEIGHT = 1080, 1350
PAD_X, PAD_TOP, PAD_BOTTOM = 80, 72, 56


def template_yaml(design_id: str, *, width: int = WIDTH, height: int = HEIGHT) -> dict:
    return {
        "kind": "pptx",
        "title": "Slides as PowerPoint (portrait 1080 x 1350)",
        "design": design_id,
        "for": ["piece"],
        "master": "master.pptx",
        "width": width,
        "height": height,
        "scale": 3,
        "layouts": {
            "cover": {"name": "Cover", "placeholders": {"eyebrow": "Eyebrow", "title": "Title", "sub": "Subtitle", "note": "Note"},
                      "stack": ["title", "sub"]},
            "content": {"name": "Content", "placeholders": {"tracker": "Tracker", "title": "Title", "body": "Body", "page": "Page"}},
        },
        "panel": True,
        "page": {"separator": " / ", "separator_color": "accent", "digits": 2},
        "tracker": {"prefix": "/", "prefix_color": "accent", "prefix_font": "bold"},
    }


def _theme_colors(design: dict) -> dict:
    c = design["colors"]
    pal = list(design.get("palette") or [c["primary"]]) + [c["primary"]] * 6
    return {"dk1": c["ink"], "lt1": c["paper"], "dk2": c["primary"], "lt2": c["surface"],
            "accent1": pal[0], "accent2": pal[1], "accent3": pal[2], "accent4": pal[3], "accent5": pal[4], "accent6": pal[5],
            "hlink": c["accent"], "folHlink": c.get("accent_dark") or c["accent"]}


def build_master(design: dict, template: dict, path: Path) -> Path:
    """master.pptx for `template` (its styles and layout names) in `design`."""
    from pptx import Presentation
    prs = Presentation()
    m.remove_slides(prs)
    w, h = int(template["width"]), int(template["height"])
    prs.slide_width, prs.slide_height = w * m.EMU_PER_PX_96, h * m.EMU_PER_PX_96
    px, ptpx = m.emu_per_px(prs, w), m.pt_per_px(prs, w)
    fs = faces(design)
    styles = merged(template)[0]
    st = lambda role, **kw: {**m.resolved(styles[role], design, fs), **kw}
    m.set_theme(prs, colors=_theme_colors(design), major=fs["bold"].name, minor=fs["body"].name, name=design.get("name"))
    m.replace_fonts(prs, {}, default=fs["body"].name)
    lay = template["layouts"]
    m.keep_layouts(prs, {"Title Slide": lay["cover"]["name"], "Title Only": lay["content"]["name"]})
    c = design["colors"]
    inner = w - 2 * PAD_X

    cover = m.layout(prs, lay["cover"]["name"])
    m.clear(cover)
    m.background(cover, c["primary"])
    ph = lay["cover"]["placeholders"]
    m.placeholder(cover, ph["eyebrow"], "body", box=(PAD_X, 80, inner * 0.7, 30), px=px, ptpx=ptpx, text=st("eyebrow"), prompt="Eyebrow")
    m.placeholder(cover, ph["title"], "title", box=(PAD_X, h * 0.42, inner, h * 0.3), px=px, ptpx=ptpx,
                  text=st("cover_title", anchor="bottom"), prompt="Title")
    m.placeholder(cover, ph["sub"], "body", box=(PAD_X, h * 0.72 + 32, inner, 150), px=px, ptpx=ptpx, text=st("cover_sub"), prompt="Subtitle")
    m.line(cover, "Rule", start=(PAD_X, h - 72 - 60), end=(w - PAD_X, h - 72 - 60), px=px, color=c["ink_faint"])
    m.placeholder(cover, ph["note"], "body", box=(PAD_X, h - 72 - 40, inner, 30), px=px, ptpx=ptpx, text=st("cover_note"), prompt="Note")
    logo = _logo(design, "file_inverse") or None
    if logo:
        m.picture(cover, "Logo", logo, box=(w - PAD_X - 200, 72, 200, 200 * _ratio(logo)), px=px)

    content = m.layout(prs, lay["content"]["name"])
    m.clear(content)
    m.background(content, c["paper"])
    ph = lay["content"]["placeholders"]
    m.placeholder(content, ph["tracker"], "body", box=(PAD_X, PAD_TOP, inner, 24), px=px, ptpx=ptpx, text=st("tracker"), prompt="Tracker")
    m.placeholder(content, ph["title"], "title", box=(PAD_X, PAD_TOP + 24 + 28, inner, 3 * 46 * 1.16), px=px, ptpx=ptpx,
                  text=st("title"), prompt="Title")
    foot = h - PAD_BOTTOM - 34 - 20
    m.placeholder(content, ph["body"], "obj", box=(PAD_X, PAD_TOP + 24 + 28 + 2 * 46 * 1.16 + 40, inner, foot - 36 - (PAD_TOP + 24 + 28 + 2 * 46 * 1.16 + 40)),
                  px=px, ptpx=ptpx, text=st("body"), prompt="Body")
    m.line(content, "Footer rule", start=(PAD_X, foot), end=(w - PAD_X, foot), px=px, color=m.resolved(styles["source"], design, fs)["color"])
    logo = _logo(design, "file")
    page_right = w - PAD_X
    if logo:
        lw = 34 / _ratio(logo)
        m.picture(content, "Logo", logo, box=(w - PAD_X - lw, h - PAD_BOTTOM - 34, lw, 34), px=px)
        page_right -= lw + 28
    m.placeholder(content, ph["page"], "body", box=(page_right - 200, h - PAD_BOTTOM - 26, 200, 24), px=px, ptpx=ptpx,
                  text=st("page", align="right", anchor="bottom"), prompt="01 / 08")
    return m.save(prs, path)


def _logo(design: dict, key: str) -> Path | None:
    name = (design.get("logo") or {}).get(key)
    f = Path(design["folder"]) / name if name and design.get("folder") else None
    return f if f and f.is_file() else None


def _ratio(image: Path) -> float:
    from PIL import Image
    with Image.open(image) as im:
        return im.height / im.width


def scaffold(folder: Path, design: dict) -> None:
    """The standard pptx template in `folder`: template.yaml and master.pptx built from the design."""
    folder = Path(folder)
    doc = template_yaml(design["id"])
    (folder / "template.yaml").write_text(
        "# A pptx template: the master holds the look (layouts Cover and Content, placeholders by role);\n"
        "# styles and spacing below say how the renderer sets text into it (sizes in px of the slide).\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    build_master(design, doc, folder / "master.pptx")
    (folder / "README.md").write_text(
        "# PowerPoint template\n\n"
        "- `master.pptx`: layouts `Cover` and `Content`; placeholders named by role (Title, Tracker, Body, Page;\n"
        "  Eyebrow, Title, Subtitle, Note). Change it in PowerPoint (View > Slide Master) or replace it with\n"
        "  your own; keep the layout and placeholder names, or map other names in `template.yaml`.\n"
        "- `template.yaml`: slide size in px, layout and placeholder names, `styles` and `spacing`.\n\n"
        "Render a piece with it: `sb render <piece> --template <this folder's name>`.\n", encoding="utf-8")
