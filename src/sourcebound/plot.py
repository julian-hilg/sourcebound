"""Minimal matplotlib setup whose figures match an `sbpaper` document.

    from sourcebound import plot as jp
    jp.setup()                                   # 11pt Times-like serif, black
    fig, ax = jp.subplots(width=0.8, aspect=0.5) # width as a share of \\textwidth
    jp.save(fig, "fig_name", outdir="figures")   # vector PDF, include at natural size

Figures are typeset with LaTeX through the PGF backend when a TeX installation is
found, so fonts and sizes are identical to the document; otherwise matplotlib's own
serif font is used.
"""
from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

TEXTWIDTH_PT = 455.24          # sbpaper: A4, 25 mm margins
PT_PER_IN = 72.27
_FONT_SIZE = 9.0


def _document_layout() -> dict:
    """Layout a document class exported on its last run (text width and sizes in pt), if any.

    Classes that write `jhlayout.json` or `layout.json` next to the document (keys `textwidth`,
    `footnotesize`) are honoured, so figures fit whichever template the deliverable uses.
    """
    import json

    from . import config
    p = config.project(required=False)
    for f in sorted(p.root.glob("deliverables/*/*layout.json")) if p else []:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return {}


def setup(*, textwidth_pt: float | None = None, fontsize: float | None = None, **_ignored) -> None:
    """Global style: serif text, black only, thin axes, no grid, no top/right spines."""
    global TEXTWIDTH_PT, _FONT_SIZE
    layout = _document_layout()
    textwidth_pt = textwidth_pt or float(layout.get("textwidth", TEXTWIDTH_PT))
    fontsize = fontsize or float(layout.get("footnotesize", 9.0))
    TEXTWIDTH_PT, _FONT_SIZE = textwidth_pt, fontsize
    tex = shutil.which("pdflatex") is not None
    mpl.rcParams.update({
        "font.family": "serif", "font.size": fontsize, "axes.labelsize": fontsize,
        "axes.titlesize": fontsize, "legend.fontsize": fontsize - 1,
        "xtick.labelsize": fontsize - 1, "ytick.labelsize": fontsize - 1,
        "axes.linewidth": 0.5, "lines.linewidth": 1.0, "xtick.major.width": 0.5,
        "ytick.major.width": 0.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "black", "axes.labelcolor": "black", "text.color": "black",
        "xtick.color": "black", "ytick.color": "black", "axes.grid": False,
        "legend.frameon": False,
        "figure.dpi": 150, "savefig.bbox": "standard",
        "pgf.texsystem": "pdflatex", "pgf.rcfonts": False,
        "pgf.preamble": "\n".join([r"\usepackage[T1]{fontenc}", r"\usepackage{newtxtext,newtxmath}"]),
        "text.usetex": False,
    })
    if not tex:
        warnings.warn("sourcebound.plot: pdflatex not found -- figures use matplotlib fonts")


def figsize(width: float = 1.0, aspect: float = 0.6) -> tuple[float, float]:
    w = width * TEXTWIDTH_PT / PT_PER_IN
    return w, w * aspect


def subplots(nrows: int = 1, ncols: int = 1, *, width: float = 1.0, aspect: float = 0.6, **kw):
    fig, ax = plt.subplots(nrows, ncols, figsize=figsize(width, aspect), **kw)
    fig.set_layout_engine("constrained")
    return fig, ax


def save(fig, name: str, *, outdir: str | Path = "figures", png: bool = False) -> Path:
    d = Path(outdir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.pdf"
    meta = {"Creator": None, "Producer": None, "Title": name}
    if shutil.which("pdflatex"):
        fig.savefig(path, backend="pgf", metadata=meta)
    else:
        fig.savefig(path, metadata=meta)
    if png:
        fig.savefig(d / f"{name}.png", dpi=300)
    plt.close(fig)
    return path
