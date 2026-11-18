"""Sourcebound plugin: slides and infoposts from a piece, and what a LinkedIn post needs.

    sb render PIECE --template <a template of kind slides>     HTML, PNG per slide, carousel PDF
    sb template new ID --kind slides [--design ID]             the standard slides template, to adapt
    sb linkedin check PIECE                                    text limits, hashtags, slides, sources
    sb linkedin bundle PIECE [--template ID] [--out FOLDER]    a folder to post by hand
"""
from __future__ import annotations

import sys

__version__ = "0.1.0"


def _setup(parser) -> None:
    parser.add_argument("what", choices=["check", "bundle"])
    parser.add_argument("piece")
    parser.add_argument("--template", help="bundle: which slides render to take (default: the newest)")
    parser.add_argument("--out", help="bundle: where to write it (default: inside the render folder)")


def _run(a) -> None:
    from . import post
    piece = a.piece.replace("\\", "/").replace("pieces/", "").strip("/")
    try:
        if a.what == "check":
            errs, warns = post.check(piece)
            for w in warns:
                print("warning:", w)
            for e in errs:
                print("ERROR:  ", e)
            print(f"{len(errs)} errors, {len(warns)} warnings")
            sys.exit(1 if errs else 0)
        dest = post.bundle(piece, template=a.template, out=a.out)
        print(f"wrote {dest}")
        for f in sorted(dest.iterdir()):
            print("  ", f.name)
        print("posting is yours to do: the steps are in README.txt")
    except (KeyError, ValueError, FileNotFoundError) as e:
        sys.exit(str(e).strip("'\""))


def guide() -> str:
    """The format of `slides.yaml` (Markdown), as `sb template guide` and the web view's agents read it."""
    from pathlib import Path
    return (Path(__file__).parent / "guide.md").read_text(encoding="utf-8")


def register(api) -> None:
    from . import slides
    api.renderer("slides", slides.render_slides, title="Slides and infoposts: PNG per slide and a carousel PDF, layout checked",
                 outputs=(".html", ".png", ".pdf"), data=("slides",), guide=guide())
    api.check("slides", slides.check)
    api.scaffold("slides", slides.scaffold)
    api.command("linkedin", _setup, _run, help="what a LinkedIn post needs: checks, and a bundle to post by hand")
