"""What python-docx has no API for: content controls, a custom XML part, templates, reading a body.

Content controls carry the link to the research.  Their tag says what they stand for:

    sb:result:<key>            a recorded number
    sb:cite:<k1>;<k2>|<loc>    a citation in parentheses      sb:citet:<key>|<loc>   one in the text
    sb:sources                 the generated source list (a block)
    sb:x:<n>                   any of the above whose readable tag would pass Word's 64 characters;
                               the manifest inside the file says what it stands for
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn

NS = "urn:sourcebound:render"
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
# Main-part content types python-docx refuses: templates and macro-enabled files.
OTHER_MAIN = ("application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
              "application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
              "application/vnd.ms-word.document.macroEnabled.main+xml")
MACRO_PARTS = re.compile(r"word/(vbaProject\.bin|vbaData\.xml|_rels/vbaProject\.bin\.rels)$|customUI/|word/customizations\.xml$", re.I)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
TAG_MAX = 64
BOX = "sb:box"                                      # the description of a table that is a note box, not a table


# ------------------------------------------------------------------ opening
def as_document_bytes(path: Path) -> tuple[bytes, dict]:
    """The file as a plain .docx package: a template's content type becomes a document's,
    and macros are left out (a .docx that holds macros does not open in Word)."""
    raw = Path(path).read_bytes()
    src = zipfile.ZipFile(io.BytesIO(raw))
    types = src.read("[Content_Types].xml").decode("utf-8")
    info = {"was_template": any(t in types for t in OTHER_MAIN[:2]), "macros_dropped": False}
    dropped = [n for n in src.namelist() if MACRO_PARTS.search(n)]
    if not info["was_template"] and OTHER_MAIN[2] not in types and not dropped:
        return raw, info
    info["macros_dropped"] = bool(dropped)
    for t in OTHER_MAIN:
        types = types.replace(t, MAIN)
    types = re.sub(r'<Override[^>]*PartName="/(?:word/vba[^"]*|customUI/[^"]*|word/customizations\.xml)"[^>]*/>', "", types)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            if item.filename in dropped:
                continue
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = types.encode("utf-8")
            elif item.filename.endswith(".rels"):
                data = re.sub(rb'<Relationship[^>]*Target="[^"]*(?:vbaProject\.bin|vbaData\.xml|customUI[^"]*|customizations\.xml)"[^>]*/>', b"", data)
            z.writestr(item, data)
    return out.getvalue(), info


def open_document(path: Path):
    data, info = as_document_bytes(path)
    return Document(io.BytesIO(data)), info


# ------------------------------------------------------------------ content controls
def tag_for(kind: str, key: str, taken: dict) -> str:
    """The control's tag: readable when it fits, a short stand-in otherwise."""
    tag = f"sb:{kind}:{key}"
    if len(tag) <= TAG_MAX:
        return tag
    return f"sb:x:{hashlib.sha256(tag.encode()).hexdigest()[:12]}"


def sdt_run(paragraph, run, tag: str, alias: str, sdt_id: int):
    """Wrap a run that python-docx just added to `paragraph` in an inline plain-text content control."""
    sdt = OxmlElement("w:sdt")
    pr = OxmlElement("w:sdtPr")
    for name, val in (("w:alias", alias[:60]), ("w:tag", tag), ("w:id", str(sdt_id))):
        e = OxmlElement(name)
        e.set(qn("w:val"), val)
        pr.append(e)
    pr.append(OxmlElement("w:text"))
    content = OxmlElement("w:sdtContent")
    sdt.append(pr)
    sdt.append(content)
    run._r.addprevious(sdt)
    content.append(run._r)
    return sdt


def sdt_block(tag: str, alias: str, sdt_id: int):
    sdt = OxmlElement("w:sdt")
    pr = OxmlElement("w:sdtPr")
    for name, val in (("w:alias", alias), ("w:tag", tag), ("w:id", str(sdt_id))):
        e = OxmlElement(name)
        e.set(qn("w:val"), val)
        pr.append(e)
    content = OxmlElement("w:sdtContent")
    sdt.append(pr)
    sdt.append(content)
    return sdt, content


def sdt_tag(sdt) -> str:
    t = sdt.find(f"{{{W}}}sdtPr/{{{W}}}tag")
    return t.get(qn("w:val")) or "" if t is not None else ""


def _skip(el) -> bool:
    return el.tag in (qn("w:del"), qn("w:moveFrom"))        # the accepted view: deleted text is gone


def plain(el) -> str:
    """Text of an element as a reader sees it once every tracked change is accepted."""
    out = []
    for node in el.iter():
        if any(_skip(a) for a in node.iterancestors()) or _skip(node):
            continue
        if node.tag == qn("w:t"):
            out.append(node.text or "")
        elif node.tag == qn("w:tab"):
            out.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            out.append("\n")
        elif node.tag == qn("w:noBreakHyphen"):
            out.append("-")
    return "".join(out)


def set_sdt_text(sdt, text: str) -> None:
    """Replace what a control shows, keeping the formatting of its first run."""
    content = sdt.find(qn("w:sdtContent"))
    runs = content.findall(f".//{{{W}}}r")
    kinds = [(r.find(qn("w:fldChar")).get(qn("w:fldCharType")) if r.find(qn("w:fldChar")) is not None else "") for r in runs]
    if "separate" in kinds and "end" in kinds:      # a citation field: text before it stays text, the rest is its result
        a, b = kinds.index("separate"), len(kinds) - 1 - kinds[::-1].index("end")
        lead = [r for r in runs[:kinds.index("begin")] if r.find(qn("w:t")) is not None] if "begin" in kinds else []
        result = [r for r in runs[a + 1:b] if r.find(qn("w:t")) is not None]
        if result:
            cut = max(text.rfind(" ["), text.rfind(" (")) + 1 if lead else 0
            for group, value in ((lead, text[:cut]), (result, text[cut:])):
                for n, r in enumerate(group):
                    for t in r.findall(qn("w:t"))[1:]:
                        r.remove(t)
                    r.find(qn("w:t")).text = value if n == 0 else ""
                    r.find(qn("w:t")).set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            return
    first = runs[0] if runs else OxmlElement("w:r")
    for r in runs[1:]:
        r.getparent().remove(r)
    for child in list(first):
        if child.tag != qn("w:rPr"):
            first.remove(child)
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    first.append(t)
    if not runs:
        content.append(first)
    # a placeholder text ("Click here") would otherwise stay marked as such
    for ph in sdt.findall(f"{{{W}}}sdtPr/{{{W}}}showingPlcHdr"):
        ph.getparent().remove(ph)


def tracked_changes(body) -> dict:
    return {"insertions": len(body.findall(f".//{{{W}}}ins")), "deletions": len(body.findall(f".//{{{W}}}del"))}


# ------------------------------------------------------------------ reading a body
def canonical(p, controls: dict | None = None) -> str:
    """A paragraph's text with every control replaced by what it stands for.

    A number that was refreshed, or renumbered citations, do not change this text; a control the
    person removed or a word they changed does.
    """
    out: list[str] = []

    def walk(el):
        for node in el:
            if _skip(node):
                continue
            if node.tag == qn("w:sdt"):
                tag = sdt_tag(node)
                if tag.startswith("sb:"):
                    out.append("{{%s}}" % tag)
                    continue
                walk(node)
            elif node.tag == qn("w:t"):
                out.append(node.text or "")
            elif node.tag == qn("w:tab"):
                out.append("\t")
            elif node.tag in (qn("w:br"), qn("w:cr")):
                out.append("\n")
            elif node.tag == qn("w:drawing") or node.tag == qn("w:pict"):
                out.append("{{figure}}")
            elif node.tag in (qn("w:pPr"), qn("w:rPr")):
                continue
            else:
                walk(node)
    walk(p)
    return "".join(out)


def body_blocks(body) -> list[dict]:
    """The body as a flat list: paragraphs, tables and the source list, in reading order.

    Each has `kind` (p | table | sources), `text` (canonical) and `el`.  Empty paragraphs are left
    out: people add and remove blank lines without meaning anything by it.
    """
    out: list[dict] = []

    def walk(parent):
        for el in parent:
            if el.tag == qn("w:p"):
                text = canonical(el)
                # Word turns a source list of one line into a control inside its paragraph once
                # something is typed next to it: it is still the source list
                inner = next((x for x in el.iter(qn("w:sdt")) if sdt_tag(x) == "sb:sources"), None)
                if inner is not None:
                    out.append({"kind": "sources", "text": plain(inner), "el": inner})
                    text = text.replace("{{sb:sources}}", "")
                if text.strip():
                    out.append({"kind": "p", "text": text, "el": el})
            elif el.tag == qn("w:tbl") and is_box(el):
                for tc in el.iter(qn("w:tc")):
                    walk(tc)                        # a note box: its paragraphs are text
            elif el.tag == qn("w:tbl"):
                rows = [" | ".join(canonical_cell(c) for c in r.findall(qn("w:tc"))) for r in el.findall(qn("w:tr"))]
                out.append({"kind": "table", "text": "\n".join(rows), "el": el})
            elif el.tag == qn("w:sdt"):
                content = el.find(qn("w:sdtContent"))
                if sdt_tag(el) == "sb:sources":
                    out.append({"kind": "sources", "text": "\n".join(plain(p) for p in content.findall(qn("w:p"))) if content is not None else "", "el": el})
                elif content is not None:
                    walk(content)                   # a cover page of a corporate template is often one
    walk(body)
    return out


def is_box(tbl) -> bool:
    d = tbl.find(f"{qn('w:tblPr')}/{qn('w:tblDescription')}")
    return d is not None and d.get(qn("w:val")) == BOX


def canonical_cell(tc) -> str:
    return " ".join(canonical(p) for p in tc.findall(qn("w:p"))).strip()


def fingerprint(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:16]


def controls_in(el) -> list:
    """Every Sourcebound content control below `el`, in reading order (not inside deleted text)."""
    return [s for s in el.iter(qn("w:sdt")) if sdt_tag(s).startswith("sb:") and not any(_skip(a) for a in s.iterancestors())]


# ------------------------------------------------------------------ the manifest inside the file
def _find_manifest_part(document):
    for part in document.part.package.iter_parts():
        if str(part.partname).startswith("/customXml/") and part.content_type != "application/vnd.openxmlformats-officedocument.customXmlProperties+xml":
            try:
                blob = part.blob
            except Exception:
                continue
            if NS.encode() in blob[:400]:
                return part
    return None


def read_manifest(document) -> dict | None:
    part = _find_manifest_part(document)
    if part is None:
        return None
    root = parse_xml(part.blob)
    node = root.find(f"{{{NS}}}manifest")
    try:
        return json.loads(node.text) if node is not None and node.text else None
    except json.JSONDecodeError:
        return None


def write_manifest(document, manifest: dict) -> None:
    """Store the manifest as a custom XML part of the package (replacing an earlier one)."""
    text = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    blob = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sb:render xmlns:sb="{NS}"><sb:manifest>{text}</sb:manifest></sb:render>').encode("utf-8")
    part = _find_manifest_part(document)
    if part is not None:
        part._blob = blob
        return
    package = document.part.package
    names = {str(p.partname) for p in package.iter_parts()}
    n = 1
    while f"/customXml/item{n}.xml" in names or f"/customXml/itemProps{n}.xml" in names:
        n += 1
    item = Part(PackURI(f"/customXml/item{n}.xml"), "application/xml", blob, package)
    # Word keeps a custom XML part across its own saves when it has a properties part with an id.
    item_id = "{%s-%s-%s-%s-%s}" % tuple(hashlib.sha256(NS.encode()).hexdigest().upper()[a:b] for a, b in ((0, 8), (8, 12), (12, 16), (16, 20), (20, 32)))
    props = Part(PackURI(f"/customXml/itemProps{n}.xml"), "application/vnd.openxmlformats-officedocument.customXmlProperties+xml",
                 (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<ds:datastoreItem ds:itemID="{item_id}" '
                  f'xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml"><ds:schemaRefs>'
                  f'<ds:schemaRef ds:uri="{NS}"/></ds:schemaRefs></ds:datastoreItem>').encode("utf-8"), package)
    item.relate_to(props, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps")
    document.part.relate_to(item, RT.CUSTOM_XML)


def clone(el):
    return copy.deepcopy(el)
