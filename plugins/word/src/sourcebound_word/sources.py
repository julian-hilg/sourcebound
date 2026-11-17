"""Word's own sources: the store behind References > Manage Sources, and citation fields.

A rendered file carries every cited source in Word's bibliography part (a custom XML part in the
namespace below).  A person can then cite the same sources with Word's own commands, and insert
Word's own bibliography.  The citations Sourcebound wrote are CITATION fields inside their content
controls: Word recognises them, and what they show stays what Sourcebound wrote until a person
asks Word to update the field (Word then formats it in the style selected in the file).

A template chooses with `sources: {word: ...}`: `store` (the default) writes the store only,
`fields` also makes the citations fields, `off` writes neither.
"""
from __future__ import annotations

import hashlib
import re
from xml.sax.saxutils import escape

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from sourcebound import render as core

NS = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography"
PROPS = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
# The style Word applies when a person updates a citation: the one closest to what was rendered.
STYLES = {"numbered": ("\\IEEE2006OfficeOnline.xsl", "IEEE", "2006"),
          "authoryear": ("\\APASixthEditionOfficeOnline.xsl", "APA", "6")}
TYPES = {"article": "JournalArticle", "book": "Book", "mvbook": "Book", "collection": "Book", "incollection": "BookSection",
         "inbook": "BookSection", "inproceedings": "ConferenceProceedings", "report": "Report", "techreport": "Report",
         "thesis": "Report", "phdthesis": "Report", "mastersthesis": "Report", "online": "InternetSite"}
PAGE = re.compile(r"^(?:pp?|S|Seiten?|pages?)\.?\s*(\d[\d\s–\-,]*[a-z]?)$", re.I)
NBSP = " "


def mode(template: dict) -> str:
    """store (the default) | fields | off, from `sources: {word: ...}` of the template."""
    m = (template.get("sources") or {}).get("word", "store")
    m = "off" if m is False else str(m).lower()
    return m if m in ("fields", "store", "off") else "store"


def tags(keys: list[str]) -> dict[str, str]:
    """Word's tag for every source key: letters and digits only, and no two alike."""
    out: dict[str, str] = {}
    for k in keys:
        base = re.sub(r"[^A-Za-z0-9]", "", k) or "S"
        tag, n = base, 1
        while tag.lower() in {t.lower() for t in out.values()}:
            n += 1
            tag = f"{base}{n}"
        out[k] = tag
    return out


def _el(name: str, value) -> str:
    value = str(value or "").replace(NBSP, " ").strip()
    return f"<b:{name}>{escape(value)}</b:{name}>" if value else ""


def _names(text: str, role: str = "Author") -> str:
    people, corporate = [], ""
    for name in (n.strip() for n in re.split(r"\s+and\s+", text or "") if n.strip()):
        if name.lower() == "others":
            continue
        if "," in name:
            last, first = (x.strip() for x in name.split(",", 1))
        elif NBSP in name:                           # {An Institution} in the bibliography: one name
            corporate = corporate or name
            continue
        else:
            first, _, last = name.rpartition(" ")
        people.append(f"<b:Person>{_el('Last', last)}{_el('First', first)}</b:Person>")
    if people:
        return f"<b:{role}><b:NameList>{''.join(people)}</b:NameList></b:{role}>"
    return f"<b:{role}>{_el('Corporate', corporate)}</b:{role}>" if corporate else ""


def _guid(key: str) -> str:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest().upper()
    return "{%s-%s-%s-%s-%s}" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])


def source_xml(key: str, tag: str, doc: core.Document, order: int, lcid: int) -> str:
    """One source as Word stores it; empty for a key that is neither a reference nor a web source."""
    ref, web = doc.references.get(key), doc.web_sources.get(key)
    head = f"{_el('Tag', tag)}%s{_el('Guid', _guid(key))}{_el('LCID', lcid)}"
    if ref:
        kind = TYPES.get(ref.get("type", ""), "InternetSite" if ref.get("url") and not ref.get("publisher") else "Misc")
        authors = _names(ref.get("author", "")) + _names(ref.get("editor", ""), "Editor")
        link = f"https://doi.org/{ref['doi']}" if ref.get("doi") else ref.get("url")
        body = (_el("Title", ref.get("title")) + _el("Year", ref.get("year"))
                + (f"<b:Author>{authors}</b:Author>" if authors else "")
                + _el("JournalName", ref.get("journaltitle") or ref.get("journal"))
                + (_el("BookTitle", ref.get("booktitle")) if kind == "BookSection" else _el("ConferenceName", ref.get("booktitle")) if kind == "ConferenceProceedings" else "")
                + _el("Volume", ref.get("volume")) + _el("Issue", ref.get("number")) + _el("Pages", ref.get("pages"))
                + _el("Publisher", ref.get("publisher") or ref.get("organization"))
                + _el("Institution", ref.get("institution")) + _el("URL", link))
    elif web:
        url = str(web.get("url") or "")
        kind = "InternetSite" if url.startswith("http") else "Misc"
        who = str(web.get("author") or "").strip("{}")
        author = _names(who) if who and ("," in who or " and " in who) else f"<b:Author>{_el('Corporate', who or web.get('publisher'))}</b:Author>"
        seen = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(web.get("accessed") or ""))
        body = (_el("Title", web.get("title")) + _el("Year", str(web.get("date") or "")[:4])
                + (f"<b:Author>{author}</b:Author>" if "<b:" in author[10:] else "")
                + (_el("InternetSiteTitle", web.get("publisher")) if kind == "InternetSite" else _el("Publisher", web.get("publisher")))
                + (_el("YearAccessed", seen.group(1)) + _el("MonthAccessed", seen.group(2)) + _el("DayAccessed", seen.group(3)) if seen and kind == "InternetSite" else "")
                + (_el("URL", url) if kind == "InternetSite" else ""))
    else:
        return ""
    return f"<b:Source>{head % _el('SourceType', kind)}{body}{_el('RefOrder', order)}</b:Source>"


def store_xml(doc: core.Document, order: list[str], style: str, lcid: int) -> tuple[bytes, dict[str, str]]:
    """The bibliography part for the cited sources, and the Word tag of each."""
    known = [k for k in order if k in doc.references or k in doc.web_sources]
    tag = tags(known)
    sheet, name, version = STYLES.get(style, STYLES["numbered"])
    items = "".join(source_xml(k, tag[k], doc, n, lcid) for n, k in enumerate(known, 1))
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<b:Sources SelectedStyle="{sheet}" StyleName="{name}" '
           f'Version="{version}" xmlns:b="{NS}" xmlns="{NS}">{items}</b:Sources>')
    return xml.encode("utf-8"), tag


def write_store(document, blob: bytes) -> None:
    """Put the bibliography part into the package, in place of one the template brought."""
    package = document.part.package
    parts = list(package.iter_parts())
    for part in parts:
        if str(part.partname).startswith("/customXml/") and part.content_type != PROPS:
            try:
                if NS.encode() in part.blob[:600]:
                    part._blob = blob
                    return
            except Exception:
                continue
    names = {str(p.partname) for p in parts}
    n = 1
    while f"/customXml/item{n}.xml" in names or f"/customXml/itemProps{n}.xml" in names:
        n += 1
    item = Part(PackURI(f"/customXml/item{n}.xml"), "application/xml", blob, package)
    props = Part(PackURI(f"/customXml/itemProps{n}.xml"), PROPS,
                 (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<ds:datastoreItem ds:itemID="{_guid(NS)}" '
                  f'xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml"><ds:schemaRefs>'
                  f'<ds:schemaRef ds:uri="{NS}"/></ds:schemaRefs></ds:datastoreItem>').encode("utf-8"), package)
    item.relate_to(props, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps")
    document.part.relate_to(item, RT.CUSTOM_XML)


# ------------------------------------------------------------------ citation fields
def instruction(keys: list[str], tag: dict[str, str], locator: str, lcid: int, *, no_author: bool = False) -> str | None:
    """The CITATION field for a group of keys; None when one of them is not in the store."""
    if not keys or any(k not in tag for k in keys):
        return None
    last = ""
    if locator:
        page = PAGE.match(locator.strip())
        value = (page.group(1).strip() if page else ", " + locator.strip()).replace('"', "'")
        last = f' \\{"p" if page else "s"} "{value}"'
    parts = []
    for n, k in enumerate(keys):
        parts.append(("\\m " if n else "") + tag[k] + (last if n == len(keys) - 1 else "") + (" \\n" if no_author else "") + f" \\l {lcid}")
    return " CITATION " + " ".join(parts) + " "


def _mark(kind: str):
    r = OxmlElement("w:r")
    c = OxmlElement("w:fldChar")
    c.set(qn("w:fldCharType"), kind)
    r.append(c)
    return r


def wrap_field(sdt, shown: str, instr: str, prefix: str = "") -> None:
    """Turn a citation control into Word's citation: `prefix` as text, the rest as the field's result."""
    pr, content = sdt.find(qn("w:sdtPr")), sdt.find(qn("w:sdtContent"))
    for plain in pr.findall(qn("w:text")):
        pr.remove(plain)
    pr.append(OxmlElement("w:citation"))
    run = content.find(qn("w:r"))
    t = run.find(qn("w:t"))
    t.text = shown[len(prefix):]
    code = OxmlElement("w:r")
    it = OxmlElement("w:instrText")
    it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    it.text = instr
    code.append(it)
    for el in (_mark("begin"), code, _mark("separate")):
        run.addprevious(el)
    run.addnext(_mark("end"))
    if prefix:
        lead = OxmlElement("w:r")
        lt = OxmlElement("w:t")
        lt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        lt.text = prefix
        lead.append(lt)
        content.insert(0, lead)
