"""Sourcebound plugin: a piece's slides as a PowerPoint file, in a template's master.

    sb render PIECE --template <a template of kind pptx>      <prefix>.pptx, chart images, layout.json
    sb template new ID --kind pptx [--design ID]               a starting template (master.pptx, template.yaml)
"""
from __future__ import annotations

__version__ = "0.1.0"


def register(api) -> None:
    from . import scaffold, slides
    api.renderer("pptx", slides.render_pptx, title="PowerPoint: one slide per deck slide in a master, editable text, charts as images",
                 outputs=(".pptx", ".png"))
    api.check("pptx", slides.check)
    api.scaffold("pptx", scaffold.scaffold)
