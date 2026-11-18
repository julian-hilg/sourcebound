"""Figures cut out of a registered PDF: `sb figure crop W-0007 --page 4 --box 52,8,98,45`.

A report often holds charts that a piece may show again as they are (the publisher's own, or one's
own report in the house style).  The crop is taken from the archived copy of the source, so it can
always be traced back: the PNG lands in the piece's folder, and an `image` block names it (`src`)
and where it came from (`from: "W-0007, p. 4"`).

`--box` is left, top, right, bottom in percent of the page.  `--grid` writes the whole page with
a 10 % grid instead, to read the box off.  The page is drawn by poppler's `pdftoppm`.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class CropError(RuntimeError):
    pass


def parse_box(text: str) -> tuple[float, float, float, float]:
    try:
        l, t, r, b = (float(v) for v in str(text).replace(";", ",").split(","))
    except ValueError:
        raise CropError("--box is four numbers: left,top,right,bottom in percent of the page (e.g. 52,8,98,45)") from None
    if not (0 <= l < r <= 100 and 0 <= t < b <= 100):
        raise CropError("--box: 0 <= left < right <= 100 and 0 <= top < bottom <= 100 (percent of the page)")
    return l, t, r, b


def _page_png(pdf: bytes, page: int, dpi: int, out_dir: Path) -> Path:
    exe = shutil.which("pdftoppm")
    if exe is None:
        raise CropError("pdftoppm (poppler) is not installed: it draws the PDF page. Install poppler-utils and try again.")
    src = out_dir / "source.pdf"
    src.write_bytes(pdf)
    prefix = out_dir / "page"
    done = subprocess.run([exe, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", str(src), str(prefix)],
                          capture_output=True, text=True)
    png = out_dir / "page.png"
    if done.returncode != 0 or not png.is_file():
        raise CropError(f"pdftoppm could not draw page {page}: {(done.stderr or done.stdout).strip() or 'no output'}")
    return png


def pages(pdf: bytes) -> int:
    import io

    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(pdf)).pages)


def trim_margin(im, *, white: int = 248, keep: int = 0):
    """`im` without the page's white margin around the figure (rows and columns that are all white)."""
    from PIL import ImageChops
    rgb = im.convert("RGB")
    bg = rgb.point(lambda v: 255 if v >= white else 0).convert("L")      # white -> 255, anything else -> 0
    box = ImageChops.invert(bg).getbbox()                                 # the box of everything not white
    if not box:
        return im
    l, t, r, b = box
    return im.crop((max(0, l - keep), max(0, t - keep), min(im.width, r + keep), min(im.height, b + keep)))


def crop(pdf: bytes, page: int, box: tuple[float, float, float, float], out: Path, *, dpi: int = 300, trim: bool = True) -> tuple[int, int]:
    """Cut `box` (percent of the page) out of `page` and write it as PNG, without the white page margin
    around it (`trim`). Returns its size in pixels."""
    from PIL import Image
    n = pages(pdf)
    if not 1 <= page <= n:
        raise CropError(f"--page {page}: the PDF has {n} pages")
    with tempfile.TemporaryDirectory() as tmp:
        with Image.open(_page_png(pdf, page, dpi, Path(tmp))) as im:
            w, h = im.size
            l, t, r, b = box
            part = im.crop((round(w * l / 100), round(h * t / 100), round(w * r / 100), round(h * b / 100)))
            if trim:
                part = trim_margin(part)
            out.parent.mkdir(parents=True, exist_ok=True)
            part.save(out, "PNG", optimize=True)
            return part.size


def grid(pdf: bytes, page: int, out: Path, *, dpi: int = 110) -> tuple[int, int]:
    """The whole page with a 10 % grid and its numbers, to read a `--box` off."""
    from PIL import Image, ImageDraw
    n = pages(pdf)
    if not 1 <= page <= n:
        raise CropError(f"--page {page}: the PDF has {n} pages")
    with tempfile.TemporaryDirectory() as tmp:
        with Image.open(_page_png(pdf, page, dpi, Path(tmp))) as im:
            im = im.convert("RGB")
            w, h = im.size
            d = ImageDraw.Draw(im)
            for k in range(0, 101, 5):
                x, y = round(w * k / 100), round(h * k / 100)
                strong = k % 10 == 0
                colour = (220, 30, 120) if strong else (240, 170, 205)
                d.line([(x, 0), (x, h)], fill=colour, width=2 if strong else 1)
                d.line([(0, y), (w, y)], fill=colour, width=2 if strong else 1)
                if strong:
                    d.text((x + 3, 3), str(k), fill=(220, 30, 120))
                    d.text((3, y + 3), str(k), fill=(220, 30, 120))
            out.parent.mkdir(parents=True, exist_ok=True)
            im.save(out, "PNG")
            return w, h
