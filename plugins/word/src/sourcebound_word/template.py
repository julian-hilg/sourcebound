"""Word templates: the standard one built from a design, and a corporate one taken as it is.

A template folder holds

    template.yaml     kind: docx, the file name, which style plays which role, where the text goes
    template.docx     (or .dotx / .dotm) the document the text is rendered into

The roles a renderer needs, each mapped to a style of the template:

    title subtitle heading1 heading2 heading3 body bullet numbered quote code caption table source

A role may be left empty.  Then the renderer falls back: an empty `bullet` types a bullet and a
tab, an empty `table` leaves the template's default table look, an empty heading uses bold body text.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

from . import ooxml

ROLES = ["title", "subtitle", "heading1", "heading2", "heading3", "body", "bullet", "numbered", "quote", "code", "caption", "table", "source"]
# Finer roles a corporate template may have a style for; each falls back to the role named.
OPTIONAL = {"figure_caption": "caption", "table_caption": "caption", "table_note": "caption", "table_text": ""}
PLACEHOLDERS = ["title", "subtitle", "author", "date", "keywords"]
MARKER = "{{content}}"
SUFFIXES = (".docx", ".dotx", ".dotm", ".docm")

# Names a role's style goes by, most specific first.  Word stores built-in styles under their
# English names whatever the language of its interface, so these match a German installation too;
# the German names are for templates whose authors created their own styles.
CANDIDATES = {
    "title": ["Title", "Titel", "Document Title", "Dokumenttitel"],
    "subtitle": ["Subtitle", "Untertitel"],
    "heading1": ["Heading 1", "Überschrift 1"],
    "heading2": ["Heading 2", "Überschrift 2"],
    "heading3": ["Heading 3", "Überschrift 3"],
    "body": ["Body Text", "Textkörper", "Fließtext", "Fliesstext", "Normal", "Standard"],
    "bullet": ["List Bullet", "Aufzählungszeichen", "Aufzählung", "Bullet"],
    "numbered": ["List Number", "Listennummer", "Nummerierung"],
    "quote": ["Quote", "Zitat"],
    "code": ["SB Code", "Code", "HTML Preformatted", "Plain Text", "Nur Text"],
    "caption": ["Caption", "Beschriftung"],
    "table": ["SB Table", "Table Grid", "Tabellenraster", "Grid Table 1 Light", "Plain Table 2"],
    "source": ["SB Source", "Bibliography", "Literaturverzeichnis", "Quellen"],
}

# Words in the names of a template's own styles that point to a role, most telling first; and words that rule a style out.
# A style the organisation made for the purpose is preferred over Word's built-in one.
OWN = {
    "title": ([("cover", "title"), ("document", "title"), ("title",), ("titel",)], ("sub", "table", "tabell", "figure", "abbildung", "toc")),
    "subtitle": ([("cover", "subtitle"), ("subtitle",), ("untertitel",)], ()),
    "body": ([("main", "copy"), ("body",), ("fließtext",), ("fliesstext",), ("copy",)], ("table", "figure", "cover", "2", "3")),
    "bullet": ([("bullet",), ("bullit",), ("aufzähl",)], ("2", "3", "number")),
    "numbered": ([("numbered",), ("numbering",), ("nummer",)], ("2", "3", "heading")),
    "quote": ([("quote",), ("zitat",)], ("intense",)),
    "code": ([("monospace",), ("code",)], ()),
    "caption": ([("figure", "caption"), ("caption",), ("beschriftung",)], ()),
    "figure_caption": ([("figure", "caption"), ("abbildungstitel",), ("figure", "title")], ()),
    "table_caption": ([("table", "title"), ("tabellentitel",), ("table", "caption")], ()),
    "table_text": ([("table", "text"), ("tabellentext",)], ()),
    "table_note": ([("table", "note"),], ()),
    "table": ([("standard",), ("table",), ("tabelle",)], ()),
    "source": ([("reference",), ("source",), ("quelle",), ("bibliograph",), ("literatur",)], ("footnote", "endnote")),
}


def propose(styles: dict[str, dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(mapping, other candidates per role) for the styles of a file."""
    mapping, others = {}, {}
    for role in [*ROLES, *OPTIONAL]:
        want = "table" if role == "table" else "paragraph"
        own = [n for n, v in styles.items() if not v["builtin"] and v["type"] == want]
        words, bad = OWN.get(role, ([], ()))
        hits: list[str] = []
        for group in words:
            hits += [n for n in sorted(own, key=len) if all(w in n.lower() for w in group) and not any(b in n.lower() for b in bad) and n not in hits]
        builtin = [c for c in CANDIDATES.get(role, []) if c in styles and styles[c]["type"] == want]
        ranked = hits + [b for b in builtin if b not in hits]
        mapping[role] = ranked[0] if ranked else ""
        others[role] = ranked[1:5]
    return mapping, others


HEADER = """# A Word template for Sourcebound (`sb render ... --template {id}`).
# styles: which style of the file plays which role. Run `sb word inspect <file>` to see the styles it has.
# An empty role falls back to something plain (see the plugin's README).
"""


def _hex(color: str) -> RGBColor:
    return RGBColor.from_string(color.lstrip("#").upper())


def _font(style, name: str | None = None, size: float | None = None, color: str | None = None, bold: bool | None = None,
          italic: bool | None = None) -> None:
    f = style.font
    if name:
        f.name = name
        rpr = style.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None:
            # theme attributes win over the names next to them: drop them, or the design's font is ignored
            for a in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
                fonts.attrib.pop(qn(f"w:{a}"), None)
            for a in ("eastAsia", "cs"):
                fonts.set(qn(f"w:{a}"), name)
    if size:
        f.size = Pt(size)
    if color:
        f.color.rgb = _hex(color)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic


def _style(doc, name: str, kind=WD_STYLE_TYPE.PARAGRAPH, base: str | None = "Normal"):
    try:
        return doc.styles[name]
    except KeyError:
        s = doc.styles.add_style(name, kind)
        if base:
            s.base_style = doc.styles[base]
        return s


def add_table_style(doc, name: str = "SB Table", color: str = "111418") -> None:
    """A table style in the booktabs manner: a rule above, below and under the header, nothing else."""
    if any(s.name == name for s in doc.styles):
        return
    c = color.lstrip("#")
    sid = name.replace(" ", "")
    doc.styles.element.append(parse_xml(
        f'<w:style {nsdecls("w")} w:type="table" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/>'
        f'<w:basedOn w:val="TableNormal"/><w:uiPriority w:val="59"/><w:qFormat/>'
        f'<w:pPr><w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/></w:pPr>'
        f'<w:tblPr><w:tblBorders><w:top w:val="single" w:sz="12" w:space="0" w:color="{c}"/>'
        f'<w:bottom w:val="single" w:sz="12" w:space="0" w:color="{c}"/></w:tblBorders>'
        f'<w:tblCellMar><w:left w:w="60" w:type="dxa"/><w:right w:w="160" w:type="dxa"/></w:tblCellMar></w:tblPr>'
        f'<w:tblStylePr w:type="firstRow"><w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="{c}"/>'
        f'</w:tcBorders></w:tcPr></w:tblStylePr></w:style>'))


def add_missing_styles(doc, design: dict, mapping: dict) -> list[str]:
    """Create the plain styles a template lacks (code, source list, table) and map them; returns their names."""
    colors, fonts, added = design["colors"], design["fonts"], []
    if not mapping.get("code"):
        s = _style(doc, "SB Code")
        _font(s, fonts["mono"][0], 9)
        s.paragraph_format.space_after = Pt(0)
        mapping["code"] = "SB Code"
        added.append("SB Code")
    if not mapping.get("source"):
        s = _style(doc, "SB Source")
        s.paragraph_format.left_indent = Cm(0.8)
        s.paragraph_format.first_line_indent = Cm(-0.8)
        s.paragraph_format.space_after = Pt(3)
        s.font.size = Pt(9)
        mapping["source"] = "SB Source"
        added.append("SB Source")
    if not mapping.get("table"):
        add_table_style(doc, color=colors["ink"])
        mapping["table"] = "SB Table"
        added.append("SB Table")
    return added


def _page_field(paragraph) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, " PAGE "), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            el.text = text
        run._r.append(el)


def scaffold(folder: Path, design: dict) -> None:
    """The standard template, built from a design: write template.docx and template.yaml into `folder`."""
    colors, fonts = design["colors"], design["fonts"]
    body, head = fonts["body"][0], fonts["heading"][0]
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin, sec.bottom_margin = Cm(2.5), Cm(2.2)

    normal = doc.styles["Normal"]
    _font(normal, body, 10.5, colors["ink"])
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.2
    _font(doc.styles["Title"], head, 26, colors["primary"], bold=False)
    _font(doc.styles["Subtitle"], head, 14, colors["ink_soft"], italic=False)
    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
        s = doc.styles[name]
        _font(s, head, size, colors["primary"], bold=True)
        s.paragraph_format.space_before = Pt(14 if size > 11 else 10)
        s.paragraph_format.space_after = Pt(4)
        s.paragraph_format.keep_with_next = True
    # the title's rule in python-docx's default template is theme blue: use the design's colour
    for b in doc.styles["Title"].element.iter(qn("w:bottom")):
        b.set(qn("w:color"), colors["primary"].lstrip("#"))
    _font(doc.styles["Caption"], body, 9, colors["ink_soft"], bold=False)
    _font(doc.styles["Quote"], body, 10.5, colors["ink_soft"], italic=True)
    doc.styles["Quote"].paragraph_format.left_indent = Cm(0.8)
    for name in ("List Bullet", "List Number"):
        _font(doc.styles[name], body, 10.5, colors["ink"])
    link = _style(doc, "Hyperlink", WD_STYLE_TYPE.CHARACTER, base=None)
    link.font.color.rgb = _hex(colors["accent"])
    link.font.underline = False
    mapping = {"title": "Title", "subtitle": "Subtitle", "heading1": "Heading 1", "heading2": "Heading 2", "heading3": "Heading 3",
               "body": "Normal", "bullet": "List Bullet", "numbered": "List Number", "quote": "Quote", "code": "", "caption": "Caption",
               "table": "", "source": ""}
    add_missing_styles(doc, design, mapping)

    # header: the logo, if the design has one that Word can show; footer: the page number
    logo = Path(design["folder"]) / design["logo"]["file"] if design.get("folder") and design["logo"].get("file") else None
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if logo and logo.is_file() and logo.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        hp.add_run().add_picture(str(logo), height=Cm(0.9))
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _page_field(fp)
    for r in fp.runs:
        r.font.size, r.font.color.rgb = Pt(9), _hex(colors["ink_faint"])

    doc.add_paragraph("{{title}}", style="Title")
    doc.add_paragraph("{{subtitle}}", style="Subtitle")
    meta = doc.add_paragraph("{{author}}  {{date}}")
    for r in meta.runs:
        r.font.color.rgb = _hex(colors["ink_soft"])
    doc.add_paragraph(MARKER)
    folder.mkdir(parents=True, exist_ok=True)
    doc.save(str(folder / "template.docx"))
    write_yaml(folder, {"kind": "docx", "title": f"Standard Word document ({design.get('name', design['id'])})", "design": design["id"],
                        "for": ["piece", "deliverable"], "file": "template.docx", "content_marker": MARKER,
                        "styles": mapping, "sources": {"style": "numbered", "heading": ""}, "title_from_text": True})


def write_yaml(folder: Path, doc: dict) -> None:
    (folder / "template.yaml").write_text(HEADER.format(id=folder.name) + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                                          encoding="utf-8")


def template_file(template: dict) -> Path:
    folder = Path(template["folder"])
    if template.get("file"):
        return folder / template["file"]
    for suffix in SUFFIXES:
        hits = sorted(f for f in folder.glob(f"*{suffix}") if not f.name.startswith("~$"))
        if hits:
            return hits[0]
    return folder / "template.docx"


def style_names(doc) -> dict[str, dict]:
    """Paragraph, character and table styles of a document by name."""
    out = {}
    for s in doc.styles:
        try:
            kind = {WD_STYLE_TYPE.PARAGRAPH: "paragraph", WD_STYLE_TYPE.CHARACTER: "character", WD_STYLE_TYPE.TABLE: "table",
                    WD_STYLE_TYPE.LIST: "list"}.get(s.type, "other")
        except (ValueError, KeyError):
            continue
        out[s.name] = {"type": kind, "builtin": bool(s.builtin), "id": s.style_id}
    return out


def inspect(path: Path) -> dict:
    """What a corporate template offers, and the mapping it suggests."""
    doc, info = ooxml.open_document(path)
    styles = style_names(doc)
    used: dict[str, int] = {}
    body = doc.element.body
    for p in body.iter(qn("w:p")):
        st = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
        if st is not None:
            used[st.get(qn("w:val"))] = used.get(st.get(qn("w:val")), 0) + 1
    by_id = {v["id"]: k for k, v in styles.items()}
    mapping, others = propose(styles)
    texts = [ooxml.plain(p) for p in body.iter(qn("w:p"))]
    for sec in doc.sections:
        for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            try:
                texts += [p.text for p in part.paragraphs]
            except Exception:                       # a header that is linked to nothing
                continue
    joined = "\n".join(texts)
    return {"file": Path(path).name, "was_template": info["was_template"], "macros": info["macros_dropped"],
            "styles": styles, "used_in_body": {by_id.get(k, k): n for k, n in sorted(used.items(), key=lambda x: -x[1])},
            "mapping": mapping, "other_candidates": others, "missing_roles": [r for r in ROLES if not mapping[r]],
            "marker": MARKER in joined, "placeholders": [p for p in PLACEHOLDERS if "{{%s}}" % p in joined],
            "body_paragraphs": sum(1 for t in texts if t.strip()),
            "content_controls": len(body.findall(f".//{qn('w:sdt')}")),
            "sections": len(doc.sections)}


def adopt(path: Path, registry: Path, ident: str, design: dict, *, title: str = "") -> tuple[Path, dict]:
    """A registry template folder from a corporate file: the file is copied unchanged, the mapping proposed."""
    path = Path(path).expanduser()
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError(f"{path.name}: a Word file is needed (.docx, .dotx, .dotm)")
    rep = inspect(path)
    dest = registry / "templates" / ident
    if dest.exists():
        raise FileExistsError(f"{dest} exists -- edit its template.yaml, or choose another id")
    dest.mkdir(parents=True)
    name = "template" + path.suffix.lower()
    shutil.copy2(path, dest / name)
    write_yaml(dest, {"kind": "docx", "title": title or path.stem, "design": design["id"], "for": ["piece", "deliverable"],
                      "file": name, "content_marker": MARKER if rep["marker"] else "", "styles": rep["mapping"],
                      "sources": {"style": "numbered", "heading": ""}, "title_from_text": True})
    return dest, rep
