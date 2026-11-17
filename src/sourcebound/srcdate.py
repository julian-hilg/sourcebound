"""When a source was published: read from the archived copy, never guessed.

A source list needs the date of the document, not the day it was archived.  `sb snap` and `sb doc`
take `--date`; without it the date is read from what the publisher wrote into the file:

    HTML    <meta> for the publication date (Open Graph, Dublin Core, Highwire, schema.org),
            `datePublished` in JSON-LD, a <time> element marked as the publication date
    PDF     the creation date in the document information

When the file says nothing, or names another year than the title, a date written in the source's
title is taken ("... of 24 September 2026", "(2026-10-02)", "December 2024"): the person or agent
who registered the source put it there.  Nothing else counts: no date stays no date, and a
citation then says "n.d.".  A date read this way is a proposal the person can correct
(`sb source set W-xxxx --date ...`).

`find(...)` returns (date, where from) with the date as YYYY-MM-DD, YYYY-MM or YYYY.
"""
from __future__ import annotations

import io
import re

META = ("article:published_time", "og:article:published_time", "datepublished", "date", "pubdate", "publishdate",
        "publish_date", "publication_date", "dc.date", "dc.date.issued", "dcterms.date", "dcterms.issued", "dcterms.created",
        "citation_publication_date", "citation_online_date", "citation_date", "sailthru.date", "parsely-pub-date")
MONTHS = {m: n for n, names in enumerate((("january", "jan", "januar"), ("february", "feb", "februar"), ("march", "mar", "märz", "maerz"),
                                         ("april", "apr"), ("may", "mai"), ("june", "jun", "juni"), ("july", "jul", "juli"),
                                         ("august", "aug"), ("september", "sep", "sept"), ("october", "oct", "oktober", "okt"),
                                         ("november", "nov"), ("december", "dec", "dezember", "dez")), 1) for m in names}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
YEARS = range(1900, 2101)


def _valid(y: int, m: int = 1, d: int = 1) -> bool:
    return y in YEARS and 1 <= m <= 12 and 1 <= d <= 31


def normal(value: str) -> str | None:
    """A date as a publisher wrote it, as YYYY-MM-DD (or YYYY-MM, YYYY); None when it is not one."""
    v = str(value or "").strip()
    if m := re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", v):                    # 2026-10-02, 2026/10/02T08:00
        y, mo, d = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None
    if m := re.match(r"(\d{4})(\d{2})(\d{2})(?!\d)", v):                                # 20261002
        y, mo, d = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None
    if m := re.match(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)", v):                   # 02.10.2026
        d, mo, y = (int(x) for x in m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None
    if m := re.match(rf"(\d{{1,2}})\.?\s+({_MONTH})\.?,?\s+(\d{{4}})(?!\d)", v, re.I):    # 24 September 2026, 24. Sept. 2026
        y, mo, d = int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))
        return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None
    if m := re.match(rf"({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", v, re.I):   # September 24, 2026
        y, mo, d = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
        return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None
    if m := re.match(r"(\d{4})[-/](\d{1,2})(?!\d)", v):                                 # 2026-10
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{y:04d}-{mo:02d}" if _valid(y, mo) else None
    if m := re.fullmatch(r"(\d{4})", v):
        return v if _valid(int(v)) else None
    return None


def from_html(text: str) -> str | None:
    """The publication date a page declares in its markup."""
    head = text[:400_000]
    found: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", head, re.I):
        attrs = {k.lower(): v for k, _q, v in re.findall(r"""([\w:.-]+)\s*=\s*(["'])(.*?)\2""", tag, re.S)}
        name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if name in META and attrs.get("content") and name not in found:
            found[name] = attrs["content"]
    for name in META:                                # in the order of trust above
        if name in found and (d := normal(found[name])):
            return d
    for m in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"', head):
        if d := normal(m.group(1)):
            return d
    for tag in re.findall(r"<time\b[^>]*>", head, re.I):
        if re.search(r"""(itemprop\s*=\s*["']datePublished|pubdate|class\s*=\s*["'][^"']*(?:publish|entry-date|post-date))""", tag, re.I):
            if (m := re.search(r"""datetime\s*=\s*["']([^"']+)""", tag, re.I)) and (d := normal(m.group(1))):
                return d
    return None


def from_pdf(data: bytes) -> str | None:
    """The creation date in a PDF's document information."""
    try:
        from pypdf import PdfReader
        info = PdfReader(io.BytesIO(data)).metadata or {}
    except Exception:
        return None
    raw = str(info.get("/CreationDate") or "")
    m = re.match(r"(?:D:)?(\d{4})(\d{2})(\d{2})", raw)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}" if _valid(y, mo, d) else None


def from_title(title: str) -> str | None:
    """A date written in a title: a full date first, else a month and a year. A year alone is too weak:
    "Trading calendar 2026" names a subject, not a day of publication."""
    t = str(title or "")
    for m in re.finditer(rf"\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\.\s?\d{{1,2}}\.\s?\d{{4}}|\d{{1,2}}\.?\s+(?:{_MONTH})\.?,?\s+\d{{4}}"
                         rf"|(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}", t, re.I):
        if (d := normal(m.group(0))) and len(d) == 10:
            return d
    for m in re.finditer(rf"\b({_MONTH})\.?\s+(\d{{4}})\b|\b(\d{{4}})-(\d{{2}})\b(?!-)", t, re.I):
        y, mo = (int(m.group(2)), MONTHS[m.group(1).lower()]) if m.group(1) else (int(m.group(3)), int(m.group(4)))
        if _valid(y, mo):
            return f"{y:04d}-{mo:02d}"
    return None


def find(data: bytes | None, *, name: str = "", title: str = "") -> tuple[str, str] | None:
    """(date, where it was read) for an archived source; None when neither the file nor the title says.

    The file's own date is the first choice.  When the title names a date in another year, the
    title wins: a file is often created or put online long after the document it holds.
    """
    named, inside = from_title(title), None
    if data:
        if data[:5] == b"%PDF-" or name.lower().endswith(".pdf"):
            if d := from_pdf(data):
                inside = d, "the PDF's creation date"
        elif b"<" in data[:2000]:
            if d := from_html(data[:400_000].decode("utf-8", errors="replace")):
                inside = d, "the page's own date"
    if inside and not (named and named[:4] != inside[0][:4]):
        return inside
    return (named, "the date in its title") if named else None
