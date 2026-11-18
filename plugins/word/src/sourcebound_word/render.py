"""A `Document` into a Word file, through a template.

What makes the result more than a printout:

- every recorded number and every citation is a content control whose tag names the result key
  or the source, so the file can be checked and refreshed after a person edited it;
- the source list is generated inside a tagged block, so it can be regenerated;
- the file carries its own manifest (a custom XML part): what was rendered from which results,
  and a fingerprint and the Markdown of every block.  It stays readable after the file is
  renamed, mailed or moved.

A file a person edited is never overwritten: the next render goes next to it as
`<name>.rendered.docx` and says so.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Emu, Pt, RGBColor

from sourcebound import render as core

from . import drawing, markdown, ooxml, sources as wsources, template as tpl

FORMAT = {"format": "sourcebound-word", "version": 1}
BOX = ooxml.BOX
NUMERIC = re.compile(r"^(?:[\s+\-−–]?[\d.,\s]+(?:[%‰]|\s?[a-zA-Zµ€$]{1,4})?|[–—-])$")
WORDS = {"en": {"table": "Table", "figure": "Figure", "section": "Section", "sources": "Sources"},
         "de": {"table": "Tabelle", "figure": "Abbildung", "section": "Abschnitt", "sources": "Quellen"}}


def _plain(spans: list[dict]) -> str:
    return "".join(s.get("s", "") if s["t"] in ("text", "math") else "" for s in spans)


def column_shares(rows: list[list[str]], capacity: float = 100) -> list[float]:
    """Parts of the table width per column. Each column first gets room for its longest word (a word broken
    over lines reads badly; a compound breaks at its hyphen), the rest of the line goes to the columns
    with more text. `capacity`: about how many characters of table text fit in one line of the table."""
    width = max(len(r) for r in rows)
    plain = lambda s: re.sub(r"[*`]", "", re.sub(r"\{\{[^}]*\}\}|\[@[^\]]*\]", "[00]", s or ""))   # a number or citation: a few characters
    least, want = [], []
    for c in range(width):
        cells = [plain(r[c] if c < len(r) else "") for r in rows]
        words = [w for x in cells for w in re.split(r"\s+|(?<=-)", x) if w]
        least.append(max((len(w) for w in words), default=1) + 2)
        want.append(min(sum(len(x) for x in cells) / max(len(cells), 1) + 2, 45))
    rest = capacity - sum(least)
    more = [max(w - m, 0) for w, m in zip(want, least)]
    if rest > 0 and sum(more):
        least = [m + rest * x / sum(more) for m, x in zip(least, more)]
    return [m / sum(least) for m in least]


def cite_text(doc: core.Document, style: str, order: list[str], keys: list[str], locator: str, textual: bool) -> str:
    """What a citation control shows: "[2]" or "(Author 2024)", by the template's source style."""
    loc = f", {locator}" if locator else ""
    if style == "numbered":
        nums = ", ".join(str(order.index(k) + 1) if k in order else "?" for k in keys)
        if textual:
            who = core.cite_label(keys[0], doc)
            return f"{who[0] if who else keys[0]} [{nums}{loc}]"
        return f"[{nums}{loc}]"
    labels = [core.cite_label(k, doc) or (k, "") for k in keys]
    if textual:
        return f"{labels[0][0]} ({labels[0][1]}{loc})"
    return "(" + "; ".join(f"{w} {y}".strip() for w, y in labels) + loc + ")"


def source_lines(doc: core.Document, style: str, order: list[str]) -> list[str]:
    """The source list: numbered in order of first use, or by author and year."""
    if style == "numbered":
        return [f"[{n}]\t{core.source_line(k, doc, accessed=True)}" for n, k in enumerate(order, 1)]
    label = lambda k: " ".join(core.cite_label(k, doc) or (k, "")).lower()
    return [core.source_line(k, doc, accessed=True) for k in sorted(order, key=label)]


class Writer:
    def __init__(self, doc: core.Document, template: dict, design: dict, out: Path):
        self.doc, self.template, self.design, self.out = doc, template, design, out
        self.d, self.info = ooxml.open_document(tpl.template_file(template))
        self.body = self.d.element.body
        self.mapping = dict(template.get("styles") or {})
        self.added_styles = tpl.add_missing_styles(self.d, design, self.mapping)
        names = {s.name: s for s in self.d.styles}
        self.styles = {role: names.get(self.mapping.get(role) or "") for role in [*tpl.ROLES, *tpl.OPTIONAL]}
        for role, fallback in tpl.OPTIONAL.items():
            if self.styles[role] is None and fallback:
                self.styles[role] = self.styles.get(fallback)
        self.char_link = names.get("Hyperlink") if names.get("Hyperlink") is not None and names["Hyperlink"].type == WD_STYLE_TYPE.CHARACTER else None
        self.words = WORDS["de" if doc.german else "en"]
        self.sources_style = (template.get("sources") or {}).get("style") or "numbered"
        self.controls: dict[str, dict] = {}
        self.groups: list[dict] = []
        self.owner: dict[int, int] = {}             # id(body element) -> group index
        self._keep: list = []
        self.sdt_id = 9000
        self.order: list[str] = []                  # cited keys, in order of first use
        self.word_sources = wsources.mode(template)  # fields | store | off: Word's own source store and citation fields
        self.word_tags: dict[str, str] = {}         # source key -> its tag in Word's store
        self.lcid = 1031 if doc.german else 1033
        self.targets: dict[str, str] = {}           # label -> "Table 2"
        self.counts = {"math": 0, "footnotes": 0, "figures_missing": []}
        self.marker = self._marker()
        sec = self.d.sections[-1]
        self.text_width = Emu(sec.page_width - sec.left_margin - sec.right_margin)
        self.title_md = ""
        self.heading_shift = 0
        self.bold_font = drawing.bold_face(design)  # bold as a face of its own: never a synthetic bold
        self.styles_fixed = self._real_bold_in_styles()
        self.shape_id = 7000
        self._sink: list | None = None              # body elements being collected for a box
        self._list = (None, 0)                      # (numbering instance, next number) of the last numbered list

    # ---- where the text goes ----------------------------------------------------
    def _marker(self):
        want = self.template.get("content_marker")
        if not want:
            return None
        for p in self.body.iter(qn("w:p")):
            if want in ooxml.plain(p):
                return p
        return None

    def _place(self, el, group: int | None):
        if self.marker is not None:
            self.marker.addprevious(el)
        if self._sink is not None:
            self._sink.append(el)
        if group is not None:
            self.owner[id(el)] = group
            self._keep.append(el)                   # lxml hands out a new proxy (and a reused id) once nothing refers to one
        return el

    def para(self, role: str, group: int | None):
        style = self.styles.get(role)
        p = self.d.add_paragraph()
        if style is not None:
            p.style = style
        self._place(p._p, group)
        return p

    # ---- inline -----------------------------------------------------------------
    def _next_id(self) -> int:
        self.sdt_id += 1
        return self.sdt_id

    def _real_bold_in_styles(self) -> list[str]:
        """Where the design has a bold face of its own (e.g. "Example-Bold"), a template style must
        not switch on Word's bold: on that face it thickens a face that is bold already, on the body
        font it draws a synthetic bold. A style with bold on in the body font (or naming no font)
        gets the bold face instead; a style in the bold face loses the switch. Styles in other
        typefaces are left as they are. Returns the ids of the styles changed."""
        if not self.bold_font:
            return []
        body = (self.design.get("fonts", {}).get("body") or [""])[0]
        theme = self._theme_fonts()
        changed = []
        for style in self.d.styles.element.iter(qn("w:style")):
            rpr = style.find(qn("w:rPr"))
            if rpr is None:
                continue
            on = [b for b in (rpr.find(qn("w:b")), rpr.find(qn("w:bCs")))
                  if b is not None and b.get(qn("w:val"), "true").lower() in {"1", "true", "on"}]
            if not on:
                continue
            fonts = rpr.find(qn("w:rFonts"))
            face = None
            if fonts is not None:                    # a theme font wins over a named one
                slot = fonts.get(qn("w:asciiTheme"))
                face = theme.get(slot[:5], slot) if slot else fonts.get(qn("w:ascii"))
            if face not in (None, body, self.bold_font):
                continue
            if face != self.bold_font:
                fonts = fonts if fonts is not None else rpr.get_or_add_rFonts()
                for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                    fonts.set(qn(a), self.bold_font)
                for a in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
                    fonts.attrib.pop(qn(a), None)    # a theme font would win over the named face
            for b in on:
                rpr.remove(b)
            changed.append(style.get(qn("w:styleId")))
        return changed

    def _theme_fonts(self) -> dict[str, str]:
        """{"major": typeface, "minor": typeface} of the template's theme (Latin script), where it has one."""
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        try:
            theme = self.d.part.part_related_by(RT.THEME)
        except KeyError:
            return {}
        from lxml import etree
        root = etree.fromstring(theme.blob)
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        out = {}
        for key in ("major", "minor"):
            hit = root.find(f".//a:{key}Font/a:latin", ns)
            if hit is not None and hit.get("typeface"):
                out[key] = hit.get("typeface")
        return out

    def bold(self, run) -> None:
        """Bold: the design's bold face where it names one, Word's bold otherwise."""
        if self.bold_font:
            run.font.name = self.bold_font
            fonts = run._r.get_or_add_rPr().get_or_add_rFonts()
            for a in ("w:cs", "w:eastAsia"):
                fonts.set(qn(a), self.bold_font)
            run.bold = None
        else:
            run.bold = True

    def cite_text(self, keys: list[str], locator: str, textual: bool) -> str:
        return cite_text(self.doc, self.sources_style, self.order, keys, locator, textual)

    def spans(self, p, spans: list[dict], *, bold: bool = False) -> None:
        mono = self.design["fonts"]["mono"][0]
        if self.doc.german:
            spans = markdown.german_quotes(spans)
        for s in spans:
            t = s["t"]
            if t == "text":
                run = p.add_run(s["s"])
                if s["b"] or bold:
                    self.bold(run)
                if s["i"]:
                    run.italic = True
                if s["code"]:
                    run.font.name = mono
                    run.font.size = Pt(max((p.style.font.size.pt if p.style is not None and p.style.font.size else 10.5) - 1, 7))
                if s["href"] and re.match(r"https?://|mailto:", s["href"]):
                    h = OxmlElement("w:hyperlink")
                    h.set(qn("r:id"), self.d.part.relate_to(s["href"], RT.HYPERLINK, is_external=True))
                    run._r.addprevious(h)
                    h.append(run._r)
                    if self.char_link is not None:
                        run.style = self.char_link
                    else:
                        run.font.color.rgb = RGBColor.from_string(self.design["colors"]["accent"].lstrip("#").upper())
            elif t == "result":
                key = s["key"]
                shown = str(self.doc.results[key]["display"]) if key in self.doc.results else f"?{key}"
                run = p.add_run(shown)
                if bold:
                    self.bold(run)
                tag = ooxml.tag_for("result", key, self.controls)
                ooxml.sdt_run(p, run, tag, f"Result {key}", self._next_id())
                self.controls[tag] = {"type": "result", "key": key, "shown": shown}
            elif t == "cite":
                shown = self.cite_text(s["keys"], s["locator"], s["textual"])
                run = p.add_run(shown)
                tag = ooxml.tag_for("citet" if s["textual"] else "cite", ";".join(s["keys"]) + (f"|{s['locator']}" if s["locator"] else ""), self.controls)
                sdt = ooxml.sdt_run(p, run, tag, f"Source {', '.join(s['keys'])}", self._next_id())
                if self.word_sources == "fields":
                    # in the text ("Author [3]", "Author (2024)") the name stays text and the field holds the rest
                    cut = shown.rfind(" [" if self.sources_style == "numbered" else " (") + 1 if s["textual"] else 0
                    instr = wsources.instruction(s["keys"], self.word_tags, s["locator"], self.lcid, no_author=bool(cut))
                    if instr:
                        wsources.wrap_field(sdt, shown, instr, shown[:cut])
                self.controls[tag] = {"type": "cite", "keys": s["keys"], "locator": s["locator"], "textual": s["textual"], "shown": shown}
            elif t == "ref":
                p.add_run(self.targets.get(s["label"], s["label"]))
            elif t == "math":
                run = p.add_run(s["s"])
                run.italic = True
                run.font.name = "Cambria Math"
                self.counts["math"] += 1
            elif t == "br":
                p.add_run().add_break()

    # ---- blocks -----------------------------------------------------------------
    def _seq(self, p, name: str, number: int) -> None:
        """A caption number as a SEQ field, so Word renumbers when a table is added by hand."""
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), f" SEQ {name} \\* ARABIC ")
        run = p.add_run(str(number))
        self.bold(run)
        run._r.addprevious(fld)
        fld.append(run._r)

    def caption_form(self, kind: str) -> tuple[str, str, str]:
        """(position, label, separator) of a caption: the design's (`charts.caption`, `charts.table_caption`:
        position above|below, prefix per language, separator) or "Figure 1. ..." below and "Table 1. ..." above."""
        conf = (self.design.get("charts") or {}).get("caption" if kind == "figure" else "table_caption") or {}
        prefix = conf.get("prefix") or {}
        prefix = prefix.get(self.doc.lang[:2]) or prefix.get("en") if isinstance(prefix, dict) else prefix
        return (conf.get("position") or ("below" if kind == "figure" else "above"),
                prefix or f"{self.words[kind]} ", conf.get("separator") or ". ")

    def caption(self, kind: str, number: int, spans: list[dict], group: int):
        _pos, label, sep = self.caption_form(kind)
        p = self.para(f"{kind}_caption", group)
        self.bold(p.add_run(label))
        self._seq(p, self.words[kind], number)
        run = p.add_run(sep if spans else ".")
        if not spans or sep.strip() in ("", ".", ":"):
            self.bold(run)                          # "Table 1." is one bold label; a dash between label and text is not
        self.spans(p, spans)
        return p

    def heading(self, b: dict, group: int) -> None:
        role = f"heading{b['level']}"
        p = self.para(role if self.styles.get(role) is not None else "body", group)
        self.spans(p, b["spans"], bold=self.styles.get(role) is None)

    def list(self, b: dict, group: int) -> None:
        ordered = b["ordered"]
        style = self.styles.get("numbered" if ordered else "bullet")
        start = b.get("start") or 1
        num_id = None
        if ordered and style is not None:
            # a loose list (items apart by blank lines) comes as one list per item: "2." goes on with the list before
            last, nxt = self._list
            num_id = last if start > 1 and last is not None and start == nxt else self._restart(style, start)
        n = start - 1
        for depth, spans in b["items"]:
            live = style is not None and (not ordered or num_id is not None)
            p = self.para(("numbered" if ordered else "bullet") if live else "body", group)
            if depth or not live:
                p.paragraph_format.left_indent = Cm(0.63 * (depth + 1))
            if live and ordered:
                self._numpr(p, num_id, depth)
            elif not live:
                # no list style in the template (or none that can restart): type the marker
                if not depth:
                    n += 1
                p.add_run(f"{n}.\t" if ordered and not depth else "•\t" if not ordered else "–\t")
                p.paragraph_format.first_line_indent = Cm(-0.63)
            self.spans(p, spans)
        if ordered:
            self._list = (num_id, start + sum(1 for depth, _ in b["items"] if not depth))

    def _restart(self, style, start: int = 1) -> int | None:
        """A numbering instance of the list style that starts at `start` (Word would continue the last list)."""
        try:
            num_pr = style.element.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}")
            numbering = self.d.part.numbering_part.element
            base = next(n for n in numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == num_pr.get(qn("w:val")))
            abstract = base.find(qn("w:abstractNumId")).get(qn("w:val"))
        except (AttributeError, StopIteration, KeyError, NotImplementedError):
            return None
        new_id = max(int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))) + 1
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(new_id))
        a = OxmlElement("w:abstractNumId")
        a.set(qn("w:val"), abstract)
        num.append(a)
        over = OxmlElement("w:lvlOverride")
        over.set(qn("w:ilvl"), "0")
        first = OxmlElement("w:startOverride")
        first.set(qn("w:val"), str(start))
        over.append(first)
        num.append(over)
        numbering.append(num)
        return new_id

    @staticmethod
    def _numpr(p, num_id: int, depth: int) -> None:
        ppr = p._p.get_or_add_pPr()
        num_pr = OxmlElement("w:numPr")
        for name, val in (("w:ilvl", str(min(depth, 8))), ("w:numId", str(num_id))):
            e = OxmlElement(name)
            e.set(qn("w:val"), val)
            num_pr.append(e)
        ppr.append(num_pr)

    def code(self, b: dict, group: int) -> None:
        p = self.para("code", group)
        lines = b["text"].split("\n")
        for i, line in enumerate(lines):
            run = p.add_run(line)
            if i < len(lines) - 1:
                run.add_break()

    def table(self, b: dict, number: int | None, group: int) -> None:
        if number is not None:                      # a table without caption and label has no number to show
            cap = self.caption("table", number, b["caption"], group)
            cap.paragraph_format.keep_with_next = True
        data = self.doc.tables.get(b["name"]) if b["name"] else None
        if data is not None:
            rows = [data["columns"], *data["rows"]]
        elif b["rows"]:
            rows = b["rows"]
        else:
            p = self.para("body", group)
            p.add_run(f"[tables/{b['name']}.csv is not in the project]" if b["name"] else "[this table has no body]").italic = True
            return
        width = max(len(r) for r in rows)
        t = self.d.add_table(rows=len(rows), cols=width)
        if self.styles.get("table") is not None:
            t.style = self.styles["table"]
        self._place(t._tbl, group)
        # the full text width, as a table in a report is expected to be (python-docx sizes to content otherwise)
        pr = t._tbl.tblPr
        for old in pr.findall(qn("w:tblW")):
            pr.remove(old)
        w = OxmlElement("w:tblW")
        w.set(qn("w:w"), "5000")
        w.set(qn("w:type"), "pct")
        pr.append(w)
        right = [len(rows) > 1 and all((not (r[c] if c < len(r) else "").strip()) or NUMERIC.match(r[c]) for r in rows[1:]) for c in range(width)]
        known = lambda k: core.cite_label(k, self.doc) is not None
        for r, row in zip(t.rows, rows):
            for c, cell in enumerate(r.cells):
                p = cell.paragraphs[0]
                if self.styles.get("table_text") is not None:
                    p.style = self.styles["table_text"]
                if right[c]:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                self.spans(p, markdown.spans(row[c] if c < len(row) else "", known=known))
        for col, share in zip(t.columns, column_shares(rows, capacity=self.text_width.pt / 4.6)):
            w = Emu(int(self.text_width * share))
            col.width = w                           # the grid, and each cell's preferred width (what Word lays out by)
            for cell in col.cells:
                cell.width = w
        if b["note"]:
            p = self.para("table_note", group)
            self.spans(p, b["note"])
        else:
            self.para("body", None)                 # Word joins two tables that touch; an empty line keeps them apart

    def _image(self, name: str) -> Path | None:
        f = self.doc.figures.get(name)
        if f is None:
            return None
        f = Path(f)
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}:
            return f
        if f.suffix.lower() == ".pdf" and shutil.which("pdftoppm"):
            cache = self.out / "_figures"
            cache.mkdir(parents=True, exist_ok=True)
            png = cache / f"{f.stem}.png"
            if not png.exists() or png.stat().st_mtime < f.stat().st_mtime:
                try:
                    subprocess.run(["pdftoppm", "-png", "-r", "220", "-singlefile", str(f), str(png.with_suffix(""))],
                                   capture_output=True, timeout=60, check=True)
                except (subprocess.SubprocessError, OSError):
                    return None
            return png if png.exists() else None
        return None

    def _native(self, name: str):
        """A vector figure (PDF) as a drawing of Word's own, in the design's colours and fonts; None where it
        cannot be read or the template asks for pictures (`figures: image`)."""
        f = self.doc.figures.get(name)
        if f is None or Path(f).suffix.lower() != ".pdf" or self.template.get("figures") == "image":
            return None
        return drawing.read(Path(f))

    def figure(self, b: dict, number: int | None, group: int) -> None:
        position, _label, _sep = self.caption_form("figure")
        if number is not None and position == "above":
            self.caption("figure", number, b["caption"], group).paragraph_format.keep_with_next = True
        p = self.para("body", group)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = number is not None and position != "above"
        fig = self._native(b["file"])
        if fig is not None:
            p.paragraph_format.space_before = Pt(6)
            el, self.shape_id = drawing.drawing(fig, self.design, scale=drawing.scale_for(fig, self.text_width.pt),
                                                shape_id=self.shape_id + 1, name=f"Figure {number or ''}".strip(),
                                                descr=_plain(b["caption"]))
            p.add_run()._r.append(el)
            self.counts["figures_native"] = self.counts.get("figures_native", 0) + 1
        else:
            img = self._image(b["file"])
            if img is None:
                self.counts["figures_missing"].append(b["file"])
                why = ("is not among the project's figures" if b["file"] not in self.doc.figures
                       else "is a PDF, and pdftoppm (poppler) is not installed to convert it" if b["file"].lower().endswith(".pdf")
                       else "is in a format Word cannot show")
                p.add_run(f"[{b['file']} {why}]").italic = True
            else:
                width = (self.template.get("figure_width_cm") and Cm(float(self.template["figure_width_cm"]))) or self.text_width
                p.add_run().add_picture(str(img), width=min(width, self.text_width))
        if number is not None and position != "above":
            self.caption("figure", number, b["caption"], group)

    def block(self, b: dict, g: int) -> None:
        kind = b["type"]
        if kind == "heading":
            self.heading(b, g)
        elif kind == "para":
            self.spans(self.para("body", g), b["spans"])
        elif kind == "list":
            self.list(b, g)
        elif kind == "quote":
            inner = b.get("blocks") or []
            if len(inner) > 1 or any(x["type"] != "para" for x in inner):
                self.box(inner, g)
                return
            p = self.para("quote" if self.styles.get("quote") is not None else "body", g)
            if self.styles.get("quote") is None:
                p.paragraph_format.left_indent = Cm(0.8)
            self.spans(p, b["spans"])
        elif kind == "code":
            self.code(b, g)
        elif kind == "math":
            p = self.para("body", g)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self.spans(p, [{"t": "math", "s": b["text"]}])
        elif kind == "table":
            self.table(b, b.get("number"), g)
        elif kind == "figure":
            self.figure(b, b.get("number"), g)

    def box(self, blocks: list[dict], g: int) -> None:
        """A quote of more than one paragraph (a note box: title, text, a list) as a framed box in the
        text's own styles: one table cell in the design's surface colour with a rule in its accent colour.
        A quote style would set all of it as one paragraph, often in italics."""
        t = self.d.add_table(rows=1, cols=1)
        self._place(t._tbl, g)
        pr = t._tbl.tblPr
        colors = self.design["colors"]
        accent, surface = colors["accent"].lstrip("#"), colors["surface"].lstrip("#")
        for child in list(pr):                      # python-docx's defaults; the schema wants its own order below
            if child.tag != qn("w:tblStyle"):
                pr.remove(child)
        pr.append(parse_xml(f'<w:tblW {nsdecls("w")} w:w="5000" w:type="pct"/>'))
        pr.append(parse_xml(f'<w:tblBorders {nsdecls("w")}><w:top w:val="nil"/><w:left w:val="single" w:sz="18" w:space="0" w:color="{accent}"/>'
                            f'<w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'))
        pr.append(parse_xml(f'<w:tblCellMar {nsdecls("w")}><w:top w:w="113" w:type="dxa"/><w:left w:w="170" w:type="dxa"/>'
                            f'<w:bottom w:w="57" w:type="dxa"/><w:right w:w="170" w:type="dxa"/></w:tblCellMar>'))
        pr.append(parse_xml(f'<w:tblDescription {nsdecls("w")} w:val="{BOX}"/>'))
        tc = t.rows[0].cells[0]._tc
        tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{surface}"/>'))
        outer, self._sink = self._sink, []
        try:
            for inner in blocks:
                self.block(inner, g)
            made = self._sink
        finally:
            self._sink = outer
        for el in made:
            if el.getparent() is not None and el.getparent().tag != qn("w:tc"):
                tc.append(el)
        for p in tc.findall(qn("w:p"))[:1]:
            if not ooxml.plain(p).strip() and len(tc.findall(qn("w:p"))) > 1 and p not in made:
                tc.remove(p)                        # the cell's own empty paragraph
        self.para("body", None)                     # a table that touches the next one is joined to it by Word

    # ---- the whole document ------------------------------------------------------
    def _blocks(self) -> list[tuple[str, dict]]:
        known = lambda k: core.cite_label(k, self.doc) is not None
        out: list[tuple[str, dict]] = []
        for s in self.doc.sections:
            out += [(s.source or s.name, b) for b in markdown.blocks(s.markdown, known=known)]
        # a first heading that repeats the title is the title: it goes to the template's title, not into the text
        if out and self.template.get("title_from_text", True) and out[0][1]["type"] == "heading" and out[0][1]["level"] == 1 \
                and _plain(out[0][1]["spans"]).strip().lower() == self.doc.title.strip().lower():
            self.title_md = out[0][1]["md"]
            out = out[1:]
            if not any(b["type"] == "heading" and b["level"] == 1 for _, b in out):
                self.heading_shift = 1
                for _, b in out:                    # the text's own sections start one level down: lift them
                    if b["type"] == "heading":
                        b["level"] -= 1
        return out

    def _walk_spans(self, b: dict):
        for key in ("spans", "caption", "note"):
            yield from b.get(key) or []
        for _depth, spans in b.get("items") or []:
            yield from spans
        if b["type"] == "table":
            data = self.doc.tables.get(b["name"]) if b.get("name") else None
            rows = [data["columns"], *data["rows"]] if data else b.get("rows") or []
            known = lambda k: core.cite_label(k, self.doc) is not None
            for row in rows:
                for cell in row:
                    yield from markdown.spans(cell, known=known)

    def _placeholders(self) -> None:
        meta = self.doc.meta
        values = {"title": self.doc.title, "subtitle": str(meta.get("subtitle") or ""), "author": str(meta.get("author") or ""),
                  "date": str(meta.get("date") or date.today().isoformat()), "keywords": str(meta.get("keywords") or "")}
        parts = [self.body]
        for sec in self.d.sections:
            for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer, sec.even_page_header, sec.even_page_footer):
                try:
                    if not part.is_linked_to_previous:
                        parts.append(part._element)
                except Exception:
                    continue
        for root in parts:
            for p in list(root.iter(qn("w:p"))):
                if p.find(f".//{qn('w:p')}") is not None:
                    continue                        # it holds a text box: the box's own paragraphs are filled in one by one
                text = ooxml.plain(p)
                if id(p) in self.owner or "{{" not in text or not any("{{%s}}" % k in text for k in values):
                    continue
                new = text
                for k, v in values.items():
                    new = new.replace("{{%s}}" % k, v)
                if not new.strip() and p.getparent() is not None and p.getparent().tag == qn("w:body"):
                    p.getparent().remove(p)         # a subtitle line of a document without subtitle
                    continue
                ts = [t for t in p.iter(qn("w:t"))]
                ts[0].text = re.sub(r"\s{2,}", " ", new).strip()
                ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for t in ts[1:]:
                    t.text = ""
        try:
            self.d.core_properties.title = self.doc.title
            if values["author"]:
                self.d.core_properties.author = values["author"]
        except Exception:
            pass

    def write(self) -> dict:
        blocks = self._blocks()
        # pass 1: numbers of tables and figures, where a reference points, the order of the sources
        nt = nf = 0
        for _src, b in blocks:
            if b["type"] in ("table", "figure") and not b["caption"] and not b["label"]:
                b["number"] = None                  # nothing to say and nothing points to it: no "Table 3." label
            elif b["type"] == "table":
                nt += 1
                b["number"] = nt
                if b["label"]:
                    self.targets[b["label"]] = f"{self.words['table']} {nt}"
            elif b["type"] == "figure":
                nf += 1
                b["number"] = nf
                if b["label"]:
                    self.targets[b["label"]] = f"{self.words['figure']} {nf}"
            elif b["type"] == "heading" and b.get("label"):
                q = ("„", "“") if self.doc.german else ("“", "”")
                self.targets[b["label"]] = f"{self.words['section']} {q[0]}{_plain(b['spans']).strip()}{q[1]}"
            for s in self._walk_spans(b):
                if s["t"] == "cite":
                    self.order += [k for k in s["keys"] if k not in self.order]
        if self.word_sources != "off" and self.order:
            blob, self.word_tags = wsources.store_xml(self.doc, self.order, self.sources_style, self.lcid)
            if self.word_tags:
                wsources.write_store(self.d, blob)
        has_title_slot = any("{{title}}" in ooxml.plain(p) for p in self.body.iter(qn("w:p")))
        if not has_title_slot and self.styles.get("title") is not None:
            self.spans(self.para("title", None), [{"t": "text", "s": self.doc.title, "b": False, "i": False, "code": False, "href": None}])
        # pass 2: the text
        sources_at = next((i for i, s in enumerate(self.doc.sections) if s.appendix), None)
        first_appendix = self.doc.sections[sources_at].source or self.doc.sections[sources_at].name if sources_at is not None else None
        done_sources = False
        for src, b in blocks:
            if first_appendix is not None and src == first_appendix and not done_sources:
                self._sources()
                done_sources = True
            self.groups.append({"md": b["md"], "section": src, "type": b["type"]})
            self.block(b, len(self.groups) - 1)
        if not done_sources:
            self._sources()
        if self.marker is not None:
            self.marker.getparent().remove(self.marker)
        self._placeholders()
        return self._manifest()

    def source_lines(self, order: list[str]) -> list[str]:
        return source_lines(self.doc, self.sources_style, order)

    def _sources(self) -> None:
        if not self.order:
            return
        heading = (self.template.get("sources") or {}).get("heading") or self.words["sources"]
        role = "heading1" if self.styles.get("heading1") is not None else "body"
        self.groups.append({"md": "", "section": "", "type": "sources-heading"})
        p = self.para(role, len(self.groups) - 1)
        p.add_run(heading).bold = True if role == "body" else None
        sdt, content = ooxml.sdt_block("sb:sources", "Sources (generated)", self._next_id())
        for line in self.source_lines(self.order):
            sp = self.d.add_paragraph(line)
            if self.styles.get("source") is not None:
                sp.style = self.styles["source"]
            content.append(sp._p)
        self._place(sdt, None)
        if self.marker is None:
            self.body.insert(len(self.body) - (1 if self.body[-1].tag == qn("w:sectPr") else 0), sdt)

    def _manifest(self) -> dict:
        blocks = []
        for b in ooxml.body_blocks(self.body):
            blocks.append({"k": b["kind"], "h": ooxml.fingerprint(b["text"]), "t": b["text"], "g": self.owner.get(id(b["el"]))})
        used = sorted({c["key"] for c in self.controls.values() if c["type"] == "result"})
        by_id = {s.style_id: role for role, s in self.styles.items() if s is not None}
        return {**FORMAT, "project": self.doc.project.slug,
                "target": f"{'pieces' if self.doc.kind == 'piece' else 'deliverables'}/{self.doc.name}",
                "template": self.template["id"], "design": self.design["id"], "lang": self.doc.lang,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "results": {k: str(self.doc.results[k]["display"]) for k in used if k in self.doc.results},
                "missing_results": [k for k in used if k not in self.doc.results],
                "sources": {"style": self.sources_style, "order": self.order, "text": "\n".join(self.source_lines(self.order))},
                "title_md": self.title_md, "heading_shift": self.heading_shift,
                "controls": self.controls, "styles": by_id, "bold_font": self.bold_font, "groups": self.groups, "blocks": blocks,
                "notes": {"mathematics_as_text": self.counts["math"], "figures_not_shown": self.counts["figures_missing"],
                          "figures_drawn": self.counts.get("figures_native", 0),
                          "template_was_dotx_or_dotm": self.info["was_template"], "macros_left_out": self.info["macros_dropped"],
                          "styles_added": self.added_styles,
                          "word_sources": {"mode": self.word_sources, "in_store": len(self.word_tags)}}}


def check(doc: core.Document, template: dict, design: dict) -> list[str]:
    """Problems that must stop a render: no template file, or a mapped style the file does not have."""
    f = tpl.template_file(template)
    if not f.is_file():
        return [f"template {template['id']}: {f.name} is not in {template['folder']}"]
    try:
        d, _ = ooxml.open_document(f)
    except Exception as e:
        return [f"template {template['id']}: {f.name} cannot be read as a Word file ({type(e).__name__}: {e})"]
    have = {s.name for s in d.styles}
    return [f"template {template['id']}: style `{name}` (role {role}) is not in {f.name}; see `sb word inspect`"
            for role, name in (template.get("styles") or {}).items() if name and name not in have]


def render(doc: core.Document, template: dict, design: dict, out: Path) -> list[Path]:
    from . import roundtrip
    w = Writer(doc, template, design, out)
    manifest = w.write()
    ooxml.write_manifest(w.d, manifest)
    target = out / f"{doc.name}.docx"
    note = ""
    if target.exists():
        try:
            if roundtrip.edited(target):
                note = f"{target.name} was edited by a person and is kept as it is"
        except Exception:
            note = f"{target.name} is not a file this plugin rendered and is kept as it is"
    if note:
        target = out / f"{doc.name}.rendered.docx"
    try:
        w.d.save(str(target))
    except PermissionError:                         # open in Word (Windows locks the file)
        note = f"{target.name} is open in another program"
        target = out / f"{doc.name}.rendered.docx"
        w.d.save(str(target))
    if note:
        print(f"note: {note}; the new render is {target.name}. `sb word refresh` updates the numbers of the edited file, "
              "`sb word pull` brings its text back.", file=sys.stderr)
    return [target]
