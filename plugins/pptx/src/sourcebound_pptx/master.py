"""Building a master .pptx: helpers for the plugin's starting template and for a pack's build script.

A pptx template is a master file whose layouts are named in template.yaml and whose
placeholders carry the roles the renderer fills (title, tracker, body, page; eyebrow, title, sub,
note on a cover). A master is built by a script, not edited by hand, so that a change to the
design can be built again:

    from sourcebound_pptx import master as m
    prs = m.open_master("their.pptx", width_px=1080, height_px=1350)    # slides removed, size set
    m.keep_layouts(prs, {"Their content layout": "Content", "Their cover": "Cover"})
    layout = m.layout(prs, "Content")
    m.clear(layout)
    m.placeholder(layout, "Title", "title", box=(80, 124, 920, 160), text=style, px=px)
    prs.save("master.pptx")

Boxes are (left, top, width, height) in the template's pixels; `px` is EMU per pixel
(`emu_per_px(prs, width_px)`). A text style here is resolved: {font, size (px), color (hex),
bold, caps, spacing (em), line, align, anchor}.
"""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
A = "{%s}" % NS["a"]
P = "{%s}" % NS["p"]
EMU_PER_PX_96 = 9525                    # 1 px at 96 dpi
PT_EMU = 12700


def emu_per_px(prs, width_px: float) -> float:
    return prs.slide_width / float(width_px)


def pt_per_px(prs, width_px: float) -> float:
    return emu_per_px(prs, width_px) / PT_EMU


def open_master(path, *, width_px: int, height_px: int, emu_per_px_: float = EMU_PER_PX_96):
    """A presentation from `path` with every slide removed and the slide size set."""
    from pptx import Presentation
    prs = Presentation(str(path))
    remove_slides(prs)
    prs.slide_width, prs.slide_height = round(width_px * emu_per_px_), round(height_px * emu_per_px_)
    return prs


def remove_slides(prs) -> None:
    lst = prs.slides._sldIdLst
    for sld in list(lst):
        prs.part.drop_rel(sld.rId)
        lst.remove(sld)


def layout(prs, name: str):
    for m in prs.slide_masters:
        for lay in m.slide_layouts:
            if lay.name == name:
                return lay
    raise KeyError(f"no layout named {name!r} (have: {', '.join(lay.name for m in prs.slide_masters for lay in m.slide_layouts)})")


def keep_layouts(prs, keep: dict[str, str]) -> None:
    """Keep only the layouts named in `keep` (old name -> new name), renamed; every other is removed."""
    for m in prs.slide_masters:
        lst = m._element.get_or_add_sldLayoutIdLst()
        for entry in list(lst):
            part = m.part.related_part(entry.rId)
            name = part.slide_layout.name
            if name in keep:
                part.slide_layout._element.cSld.set("name", keep[name])
            else:
                lst.remove(entry)
                m.part.drop_rel(entry.rId)
    for old in keep:
        layout(prs, keep[old])                       # fails when a named layout was not there


def clear(target, *, keep: tuple[str, ...] = ()) -> None:
    """Remove every shape of a layout (or master) except those named in `keep`."""
    tree = target.shapes._spTree
    for sp in list(tree.iterchildren()):
        if sp.tag in (P + "nvGrpSpPr", P + "grpSpPr", P + "extLst"):
            continue
        name = sp.find(".//p:cNvPr", NS)
        if name is not None and name.get("name") in keep:
            continue
        tree.remove(sp)


def _xp(el, expr: str) -> list:
    """XPath with the a:, p:, r: prefixes, on lxml and python-pptx elements alike."""
    return etree._Element.xpath(el, expr, namespaces=NS)


def _next_id(target) -> int:
    ids = [int(x) for x in _xp(target.shapes._spTree, ".//p:cNvPr/@id") if str(x).isdigit()]
    return max(ids + [1]) + 1


def _box(box, px) -> tuple[int, int, int, int]:
    return tuple(round(v * px) for v in box)


def _color(hex_: str) -> str:
    h = hex_.strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", h):
        raise ValueError(f"{hex_!r} is not a hex colour")
    return h


def text_props(style: dict, *, ptpx: float, tag: str = "defRPr") -> str:
    """An <a:defRPr> or <a:rPr> for a resolved text style."""
    size = round(float(style["size"]) * ptpx * 100)
    attrs = [f'sz="{size}"', f'b="{1 if style.get("bold") else 0}"', 'i="0"']
    attrs.append(f'cap="{"all" if style.get("caps") else "none"}"')           # explicit: a master may set capitals
    attrs.append(f'spc="{round(float(style.get("spacing") or 0) * float(style["size"]) * ptpx * 100)}"')
    attrs.append('baseline="0"')
    font = style["font"]
    return (f'<a:{tag} {" ".join(attrs)}><a:solidFill><a:srgbClr val="{_color(style["color"])}"/></a:solidFill>'
            f'<a:latin typeface="{font}"/><a:ea typeface="{font}"/><a:cs typeface="{font}"/></a:{tag}>')


def para_props(style: dict, *, ptpx: float, inner: str = "") -> str:
    line = round(float(style["size"]) * float(style.get("line") or 1.2) * ptpx * 100)
    algn = {"left": "l", "right": "r", "center": "ctr"}.get(style.get("align") or "left", "l")
    return (f'<a:lvl1pPr marL="0" indent="0" algn="{algn}"><a:lnSpc><a:spcPts val="{line}"/></a:lnSpc>'
            f'<a:spcBef><a:spcPts val="0"/></a:spcBef><a:spcAft><a:spcPts val="0"/></a:spcAft><a:buNone/>{inner}</a:lvl1pPr>')


def body_pr(anchor: str = "t", *, wrap: bool = True) -> str:
    return (f'<a:bodyPr wrap="{"square" if wrap else "none"}" lIns="0" tIns="0" rIns="0" bIns="0" '
            f'anchor="{ {"top": "t", "bottom": "b", "middle": "ctr"}.get(anchor, anchor) }" anchorCtr="0" rtlCol="0">'
            '<a:noAutofit/></a:bodyPr>')


def placeholder(target, name: str, kind: str, *, box, px: float, ptpx: float, text: dict | None = None,
                prompt: str = "", idx: int | None = None) -> None:
    """Add a placeholder to a layout. `kind`: title, body (text), obj (any content), pic."""
    sid = _next_id(target)
    ph_attrs = {"title": 'type="title"', "body": 'type="body"', "obj": "", "pic": 'type="pic"'}[kind]
    if kind != "title":
        ph_attrs += f' idx="{idx if idx is not None else 10 + sid}"'
    if prompt:
        ph_attrs += ' hasCustomPrompt="1"'
    x, y, w, h = _box(box, px)
    lst = ""
    if text:
        lst = "<a:lstStyle>" + para_props(text, ptpx=ptpx, inner=text_props(text, ptpx=ptpx)) + "</a:lstStyle>"
    body = ""
    if kind != "pic":
        run = f'<a:r><a:rPr lang="de-DE" dirty="0"/><a:t>{_xml(prompt)}</a:t></a:r>' if prompt else ""
        body = (f'<p:txBody>{body_pr((text or {}).get("anchor", "top"))}{lst or "<a:lstStyle/>"}'
                f'<a:p>{run}<a:endParaRPr lang="de-DE" dirty="0"/></a:p></p:txBody>')
    xml = (f'<p:sp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:nvSpPr><p:cNvPr id="{sid}" name="{_xml(name)}"/>'
           f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph {ph_attrs.strip()}/></p:nvPr></p:nvSpPr>'
           f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm></p:spPr>{body}</p:sp>')
    target.shapes._spTree.append(etree.fromstring(xml))


def _xml(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def rect(target, name: str, *, box, px: float, fill: str, gradient: list[tuple[float, str, float]] | None = None,
         angle: float = 90) -> None:
    """A filled rectangle without outline. `gradient`: [(position 0..1, hex, alpha 0..1), ...] from top."""
    sid = _next_id(target)
    x, y, w, h = _box(box, px)
    if gradient:
        stops = "".join(f'<a:gs pos="{round(pos * 100000)}"><a:srgbClr val="{_color(c)}"><a:alpha val="{round(al * 100000)}"/></a:srgbClr></a:gs>'
                        for pos, c, al in gradient)
        fill_xml = f'<a:gradFill rotWithShape="1"><a:gsLst>{stops}</a:gsLst><a:lin ang="{round(angle * 60000)}" scaled="0"/></a:gradFill>'
    else:
        fill_xml = f'<a:solidFill><a:srgbClr val="{_color(fill)}"/></a:solidFill>'
    xml = (f'<p:sp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:nvSpPr><p:cNvPr id="{sid}" name="{_xml(name)}"/><p:cNvSpPr/>'
           f'<p:nvPr userDrawn="1"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
           f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill_xml}<a:ln><a:noFill/></a:ln></p:spPr>'
           f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="de-DE"/></a:p></p:txBody></p:sp>')
    target.shapes._spTree.append(etree.fromstring(xml))


def line(target, name: str, *, start, end, px: float, color: str, width_px: float = 1.0) -> None:
    sid = _next_id(target)
    (x1, y1), (x2, y2) = [(round(a * px), round(b * px)) for a, b in (start, end)]
    flip = ' flipV="1"' if y2 < y1 else ""
    xml = (f'<p:cxnSp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:nvCxnSpPr><p:cNvPr id="{sid}" name="{_xml(name)}"/><p:cNvCxnSpPr/>'
           f'<p:nvPr userDrawn="1"/></p:nvCxnSpPr><p:spPr><a:xfrm{flip}><a:off x="{min(x1, x2)}" y="{min(y1, y2)}"/>'
           f'<a:ext cx="{abs(x2 - x1)}" cy="{abs(y2 - y1)}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
           f'<a:ln w="{round(width_px * px)}"><a:solidFill><a:srgbClr val="{_color(color)}"/></a:solidFill></a:ln></p:spPr></p:cxnSp>')
    target.shapes._spTree.append(etree.fromstring(xml))


def text(target, name: str, *, box, px: float, ptpx: float, runs: list[tuple[str, dict]], anchor: str = "top") -> None:
    """Fixed text on a layout (an address line, a company name): runs of (text, resolved style)."""
    sid = _next_id(target)
    x, y, w, h = _box(box, px)
    first = runs[0][1]
    rs = "".join("<a:r>" + text_props(st, ptpx=ptpx, tag="rPr").replace("<a:rPr ", '<a:rPr lang="de-DE" ', 1)
                 + f"<a:t>{_xml(t)}</a:t></a:r>" for t, st in runs)
    ppr = para_props(first, ptpx=ptpx).replace("a:lvl1pPr", "a:pPr")
    xml = (f'<p:sp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:nvSpPr><p:cNvPr id="{sid}" name="{_xml(name)}"/><p:cNvSpPr txBox="1"/>'
           f'<p:nvPr userDrawn="1"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
           f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
           f'<p:txBody>{body_pr(anchor)}<a:lstStyle/><a:p>{ppr}{rs}</a:p></p:txBody></p:sp>')
    target.shapes._spTree.append(etree.fromstring(xml))


def picture(target, name: str, image, *, box, px: float, crop: tuple[float, float, float, float] | None = None,
            descr: str = "") -> None:
    """A picture on a layout or master. `crop` = (left, top, right, bottom) shares of the image cut away."""
    from pptx.oxml.shapes.picture import CT_Picture
    _part, rid = target.part.get_or_add_image_part(str(image))
    x, y, w, h = _box(box, px)
    pic = CT_Picture.new_pic(_next_id(target), name, descr, rid, x, y, w, h)
    pic.nvPicPr.nvPr.set("userDrawn", "1")
    if crop:
        src = pic.blipFill.find(A + "srcRect")
        if src is None:
            src = etree.Element(A + "srcRect")
            pic.blipFill.insert(1, src)
        for key, v in zip(("l", "t", "r", "b"), crop):
            if v:
                src.set(key, str(round(v * 100000)))
    target.shapes._spTree.append(pic)


def background(target, color: str) -> None:
    """A solid background for a layout or the master."""
    csld = target._element.cSld
    old = csld.find(P + "bg")
    if old is not None:
        csld.remove(old)
    bg = etree.fromstring(f'<p:bg xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:bgPr><a:solidFill><a:srgbClr val="{_color(color)}"/>'
                          '</a:solidFill><a:effectLst/></p:bgPr></p:bg>')
    csld.insert(0, bg)


# ------------------------------------------------------------------ theme and fonts
def theme_part(prs):
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    return prs.slide_masters[0].part.part_related_by(RT.THEME)


def set_theme(prs, *, colors: dict[str, str] | None = None, major: str | None = None, minor: str | None = None,
              name: str | None = None) -> None:
    """Theme colours (dk1, lt1, dk2, lt2, accent1..6, hlink, folHlink: hex) and the heading and body fonts."""
    part = theme_part(prs)
    root = etree.fromstring(part.blob)
    scheme = root.find(".//a:clrScheme", NS)
    for key, hexv in (colors or {}).items():
        el = scheme.find(f"a:{key}", NS)
        if el is None:
            raise KeyError(f"theme colour {key}")
        for child in list(el):
            el.remove(child)
        etree.SubElement(el, A + "srgbClr").set("val", _color(hexv))
    if name:
        scheme.set("name", name)
        root.find(".//a:fontScheme", NS).set("name", name)
        root.set("name", name)
    for tag, face in (("majorFont", major), ("minorFont", minor)):
        if face:
            f = root.find(f".//a:fontScheme/a:{tag}", NS)
            for child in list(f):
                if child.tag in (A + "latin", A + "ea", A + "cs"):
                    child.set("typeface", face if child.tag == A + "latin" else "")
                    for k in ("panose", "pitchFamily", "charset"):
                        child.attrib.pop(k, None)
                elif child.tag == A + "font":
                    f.remove(child)                       # script fonts of other writing systems
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def fonts_in(prs) -> set[str]:
    """Every typeface a master, its layouts and its theme name explicitly."""
    seen: set[str] = set()
    for m in prs.slide_masters:
        for el in [m._element, *(lay._element for lay in m.slide_layouts)]:
            seen.update(t for t in _xp(el, ".//a:latin/@typeface | .//a:ea/@typeface | .//a:cs/@typeface | .//a:buFont/@typeface") if t and not t.startswith("+"))
    root = etree.fromstring(theme_part(prs).blob)
    seen.update(t for t in root.xpath(".//a:fontScheme//@typeface", namespaces=NS) if t)
    return seen


def replace_fonts(prs, mapping: dict[str, str], *, default: str | None = None, keep: set[str] = frozenset()) -> None:
    """Replace typefaces in the master and its layouts (text and bullet fonts): `mapping` old -> new,
    anything else -> `default`. Fonts in `keep` stay (a symbol font that draws bullets, say)."""
    for m in prs.slide_masters:
        for el in [m._element, *(lay._element for lay in m.slide_layouts)]:
            for node in _xp(el, ".//a:latin | .//a:ea | .//a:cs | .//a:buFont"):
                face = node.get("typeface") or ""
                if not face or face.startswith("+") or face in keep:
                    continue
                new = mapping.get(face, default)
                if new and new != face:
                    node.set("typeface", new)
                    for k in ("panose", "pitchFamily", "charset"):
                        node.attrib.pop(k, None)


def drop_unused(prs) -> None:
    """Drop relationships of the master and its layouts that no shape uses any more (images of removed shapes)."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    for mst in prs.slide_masters:
        for target in [mst, *mst.slide_layouts]:
            xml = etree.tostring(target._element).decode("utf-8")
            for rid, rel in list(target.part.rels.items()):
                if rel.reltype in (RT.IMAGE, RT.MEDIA, RT.VIDEO, RT.HYPERLINK) and f'"{rid}"' not in xml:
                    target.part.drop_rel(rid)


def resolved(style: dict, design: dict, faces: dict) -> dict:
    """A template style with its font role and colour token turned into a face name and a hex value."""
    face = faces.get(style.get("font") or "body") or faces["body"]
    colors = design["colors"]
    token = style.get("color") or "ink"
    if token not in colors:
        raise KeyError(f"colour {token!r} is not in design {design.get('id')} (colors: {', '.join(colors)})")
    return {**style, "font": face.name, "bold": face.bold, "color": colors[token]}


def save(prs, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    drop_unused(prs)
    prs.save(str(path))
    return path
