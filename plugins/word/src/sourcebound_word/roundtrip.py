"""After a person edited the Word file: what changed, bring the numbers up to date, take the text back.

    status    compares the file with what was rendered (the manifest inside it) and with the
              project's results and sources.  Changes nothing.
    refresh   updates numbers that are out of date, renumbers citations and regenerates the source
              list.  A control the person typed over is theirs: it is reported, not changed.
    pull      writes the file's text back as Markdown in the handover notation, next to the source
              as <name>.from-word.md.  The source itself is never written.

Tracked changes are read as if every one of them were accepted.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from pathlib import Path

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from sourcebound import config, render as core, results

from . import markdown, ooxml
from .render import cite_text, source_lines

NOT_OURS = "this file carries no Sourcebound manifest: it was not rendered by `sb render`, or the manifest was removed"


def load(path: Path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{path}: no such file")
    d, _info = ooxml.open_document(path)
    manifest = ooxml.read_manifest(d)
    if manifest is None:
        raise ValueError(f"{path.name}: {NOT_OURS}")
    return d, manifest


def find_project(path: Path, manifest: dict, explicit: str | Path | None = None) -> config.Project | None:
    """The project the file was rendered from: given, around the file, or around the working directory."""
    for start in ([explicit] if explicit else [Path(path).resolve().parent, Path.cwd()]):
        root = config.find_up("project.yaml", start)
        if root is not None:
            try:
                p = config.project(root)
            except Exception:
                continue
            if explicit or p.slug == manifest.get("project"):
                return p
    return None


def evidence(p: config.Project, manifest: dict) -> core.Document:
    """Results and sources of the project as a Document without text (enough to check and to refresh)."""
    refs, web = core._evidence(p)
    kind, name = manifest["target"].split("/", 1)
    return core.Document(project=p, name=name, kind="piece" if kind == "pieces" else "deliverable", title="",
                         lang=manifest.get("lang") or p.lang, folder=p.root / manifest["target"],
                         results=results.load(p), references=refs, web_sources=web)


# ------------------------------------------------------------------ comparing
def compare(d, manifest: dict) -> dict:
    body = d.element.body
    now_all = ooxml.body_blocks(body)
    now = [b for b in now_all if b["kind"] != "sources"]
    old = [b for b in manifest["blocks"] if b["k"] != "sources"]
    a, b = [x["h"] for x in old], [ooxml.fingerprint(x["text"]) for x in now]
    ops = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    equal, gone, new = [], [], []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            equal += list(zip(range(i1, i2), range(j1, j2)))
        else:
            gone += list(range(i1, i2))
            new += list(range(j1, j2))
    # the same text gone in one place and new in another was moved, not rewritten
    moved = []
    for i in list(gone):
        j = next((j for j in new if b[j] == a[i]), None)
        if j is not None:
            moved.append((i, j))
            gone.remove(i)
            new.remove(j)
    # what is left: a paragraph that reads much like one that is gone was changed; the rest was added or deleted
    scored = sorted(((difflib.SequenceMatcher(None, old[i]["t"], now[j]["text"]).ratio(), -abs(i - j), i, j)
                     for i in gone for j in new if old[i]["k"] == now[j]["kind"]), reverse=True)
    pairs = []
    for ratio, _near, i, j in scored:
        if ratio >= 0.5 and i in gone and j in new:
            pairs.append((i, j))
            gone.remove(i)
            new.remove(j)
    pairs.sort()
    deleted, added = gone, new

    controls = manifest.get("controls") or {}
    present = [(ooxml.sdt_tag(s), ooxml.plain(s), s) for s in ooxml.controls_in(body) if ooxml.sdt_tag(s) != "sb:sources"]
    typed = [{"tag": t, "was": controls[t]["shown"], "now": text} for t, text, _ in present if t in controls and text != controls[t]["shown"]]
    removed = []
    for tag, c in controls.items():
        was = sum(x["t"].count("{{%s}}" % tag) for x in manifest["blocks"])
        is_ = sum(1 for t, _, _ in present if t == tag)
        if is_ < was:
            removed.append({"tag": tag, "times": was - is_, **{k: c[k] for k in ("type", "key", "keys") if k in c}})
    src_now = next((x for x in now_all if x["kind"] == "sources"), None)
    src_old = (manifest.get("sources") or {}).get("text", "")
    return {"old": old, "now": now, "equal": equal, "changed": pairs, "added": sorted(added), "deleted": sorted(deleted), "moved": moved,
            "present": present, "typed_over": typed, "removed": removed,
            "sources": {"present": src_now is not None, "edited": src_now is not None and _norm(src_now["text"]) != _norm(src_old),
                        "expected": bool(src_old)},
            "tracked": ooxml.tracked_changes(body)}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def edited(path: Path) -> bool:
    """True if a person changed the file since it was rendered."""
    d, manifest = load(path)
    c = compare(d, manifest)
    return bool(c["changed"] or c["added"] or c["deleted"] or c["moved"] or c["typed_over"] or c["removed"] or c["sources"]["edited"]
                or (c["sources"]["expected"] and not c["sources"]["present"]))


def _show(text: str, n: int = 90) -> str:
    text = re.sub(r"\{\{sb:(?:result|x):([^}]*)\}\}", r"{{result:\1}}", re.sub(r"\{\{sb:citet?:([^}|]*)[^}]*\}\}", r"[@\1]", text))
    text = _norm(text)
    return text if len(text) <= n else text[:n - 1] + "…"


def status(path: Path, project: str | Path | None = None) -> dict:
    d, manifest = load(path)
    c = compare(d, manifest)
    p = find_project(path, manifest, project)
    out = {"file": str(path), "target": manifest["target"], "template": manifest["template"], "rendered_at": manifest["at"],
           "refreshed_at": manifest.get("refreshed_at"), "project": p.slug if p else None,
           "paragraphs": {"unchanged": len(c["equal"]),
                          "changed": [{"was": _show(c["old"][i]["t"]), "now": _show(c["now"][j]["text"])} for i, j in c["changed"]],
                          "added": [_show(c["now"][j]["text"]) for j in c["added"]],
                          "deleted": [_show(c["old"][i]["t"]) for i in c["deleted"]],
                          "moved": [_show(c["now"][j]["text"]) for _, j in c["moved"]]},
           "typed_over": c["typed_over"], "removed_controls": c["removed"], "sources_list": c["sources"], "tracked_changes": c["tracked"],
           "stale": [], "missing_results": [], "unknown_sources": [], "notes": manifest.get("notes") or {}}
    if p is None:
        out["problem"] = (f"the project `{manifest.get('project')}` was not found around the file or the working directory: numbers and "
                          "sources were not checked (run it inside the project, or pass --project FOLDER)")
        return out
    doc = evidence(p, manifest)
    controls, typed = manifest["controls"], {t["tag"] for t in c["typed_over"]}
    seen = set()
    for tag, _text, _s in c["present"]:
        ctl = controls.get(tag)
        if ctl is None or tag in seen:
            continue
        seen.add(tag)
        if ctl["type"] == "result":
            if ctl["key"] not in doc.results:
                out["missing_results"].append(ctl["key"])
            elif str(doc.results[ctl["key"]]["display"]) != ctl["shown"] and tag not in typed:
                out["stale"].append({"key": ctl["key"], "shown": ctl["shown"], "recorded": str(doc.results[ctl["key"]]["display"])})
        else:
            out["unknown_sources"] += [k for k in ctl["keys"] if core.cite_label(k, doc) is None and k not in out["unknown_sources"]]
    return out


# ------------------------------------------------------------------ refresh
def refresh(path: Path, project: str | Path | None = None, *, sources: bool = False) -> dict:
    """Update numbers and the source list in place. `sources=True` regenerates a source list the person edited."""
    path = Path(path).expanduser()
    d, manifest = load(path)
    p = find_project(path, manifest, project)
    if p is None:
        raise RuntimeError(f"the project `{manifest.get('project')}` was not found: run this inside the project, or pass --project FOLDER")
    doc = evidence(p, manifest)
    body, controls = d.element.body, manifest["controls"]
    present = [(ooxml.sdt_tag(s), ooxml.plain(s), s) for s in ooxml.controls_in(body) if ooxml.sdt_tag(s) != "sb:sources"]
    changes, kept = [], []
    for tag, text, sdt in present:
        ctl = controls.get(tag)
        if ctl is None or ctl["type"] != "result":
            continue
        if text != ctl["shown"]:
            kept.append({"key": ctl["key"], "typed": text, "rendered": ctl["shown"]})
        elif ctl["key"] in doc.results and str(doc.results[ctl["key"]]["display"]) != text:
            ooxml.set_sdt_text(sdt, str(doc.results[ctl["key"]]["display"]))
            changes.append({"what": "number", "key": ctl["key"], "from": text, "to": str(doc.results[ctl["key"]]["display"])})
    for tag, ctl in controls.items():               # after the loop, so that every occurrence compared against the old value
        if ctl["type"] == "result" and ctl["key"] in doc.results and not any(k["key"] == ctl["key"] for k in kept):
            ctl["shown"] = str(doc.results[ctl["key"]]["display"])

    # citations: the order may have changed because the person removed or moved one
    style = manifest["sources"]["style"]
    order: list[str] = []
    for tag, _text, _sdt in present:
        ctl = controls.get(tag)
        if ctl and ctl["type"] == "cite":
            order += [k for k in ctl["keys"] if k not in order]
    for tag, text, sdt in present:
        ctl = controls.get(tag)
        if ctl is None or ctl["type"] != "cite":
            continue
        new = cite_text(doc, style, order, ctl["keys"], ctl["locator"], ctl["textual"])
        if text != ctl["shown"]:
            kept.append({"key": ";".join(ctl["keys"]), "typed": text, "rendered": ctl["shown"]})
        elif new != text:
            ooxml.set_sdt_text(sdt, new)
            changes.append({"what": "citation", "key": ";".join(ctl["keys"]), "from": text, "to": new})
    for tag, ctl in controls.items():
        if ctl["type"] == "cite" and not any(k["key"] == ";".join(ctl["keys"]) for k in kept):
            ctl["shown"] = cite_text(doc, style, order, ctl["keys"], ctl["locator"], ctl["textual"])
    lines = source_lines(doc, style, order)
    block = next((s for s in body.iter(qn("w:sdt")) if ooxml.sdt_tag(s) == "sb:sources"), None)
    note = ""
    if block is None:
        note = "the source list was removed from the file and is not put back" if manifest["sources"].get("text") else ""
    else:
        content = block.find(qn("w:sdtContent"))
        paras = content.findall(qn("w:p"))
        current = "\n".join(ooxml.plain(x) for x in paras) if paras else ooxml.plain(content)
        if _norm(current) != _norm(manifest["sources"].get("text", "")) and not sources:
            note = "the source list was edited by hand and is kept (use --sources to regenerate it)"
        elif _norm(current) != _norm("\n".join(lines)) and block.getparent().tag == qn("w:p"):
            # the list sits inside a paragraph (see ooxml.body_blocks): its entries become lines of that paragraph
            ooxml.set_sdt_text(block, "")
            run = content.find(f".//{qn('w:r')}")
            for old in run.findall(qn("w:t")):
                run.remove(old)
            for n, line in enumerate(lines):
                if n:
                    run.append(OxmlElement("w:br"))
                for m, piece in enumerate(line.split("\t")):
                    if m:
                        run.append(OxmlElement("w:tab"))
                    t = OxmlElement("w:t")
                    t.text = piece
                    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    run.append(t)
            changes.append({"what": "source list", "key": "", "from": "", "to": f"{len(lines)} entries"})
            manifest["sources"].update(order=order, text="\n".join(lines))
        elif _norm(current) != _norm("\n".join(lines)):
            ppr = paras[0].find(qn("w:pPr")) if paras else None
            for x in paras:
                content.remove(x)
            for line in lines or [""]:
                np_ = OxmlElement("w:p")
                if ppr is not None:
                    np_.append(ooxml.clone(ppr))
                r = OxmlElement("w:r")
                for n, piece in enumerate(line.split("\t")):
                    if n:
                        r.append(OxmlElement("w:tab"))
                    t = OxmlElement("w:t")
                    t.text = piece
                    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    r.append(t)
                np_.append(r)
                content.append(np_)
            changes.append({"what": "source list", "key": "", "from": f"{len(paras)} entries", "to": f"{len(lines)} entries"})
            manifest["sources"].update(order=order, text="\n".join(lines))
    if changes:
        manifest["results"] = {c["key"]: c["shown"] for c in controls.values() if c["type"] == "result" and c["key"] in doc.results}
        manifest["refreshed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ooxml.write_manifest(d, manifest)
        try:
            d.save(str(path))
        except PermissionError:
            raise RuntimeError(f"{path.name} is open in another program: close it there and run the refresh again")
    return {"file": str(path), "changes": changes, "kept": kept, "note": note,
            "unknown_sources": [k for k in order if core.cite_label(k, doc) is None]}


# ------------------------------------------------------------------ pull
def _run_format(r, mono_fonts: tuple) -> tuple[str, str]:
    """(format, text) of a run: "" | b | i | bi | code | math."""
    text = ooxml.plain(r)
    rpr = r.find(qn("w:rPr"))

    def on(name: str) -> bool:
        el = rpr.find(qn(name)) if rpr is not None else None
        return el is not None and el.get(qn("w:val")) not in ("0", "false")
    fonts = rpr.find(qn("w:rFonts")) if rpr is not None else None
    font = fonts.get(qn("w:ascii")) if fonts is not None else None
    if font and font in mono_fonts:
        return "code", text
    if font == "Cambria Math":
        return "math", text
    return ("b" if on("w:b") else "") + ("i" if on("w:i") else ""), text


def _wrap(fmt: str, text: str) -> str:
    if fmt == "code":
        return f"`{text}`"
    if fmt == "math":
        return f"${text}$"
    lead, body, trail = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S).groups()
    if not body:
        return text
    body = re.sub(r"([\\*_`\[\]])", r"\\\1", body).replace("\n", "  \n")
    mark = {"b": "**", "i": "*", "bi": "***"}.get(fmt, "")
    return f"{lead}{mark}{body}{mark}{trail}"


def _inline_markdown(p, d, manifest: dict, typed: list) -> str:
    controls = manifest.get("controls") or {}
    mono = tuple(x for x in ("Source Code Pro", "Consolas", "Menlo", "Courier New", manifest.get("mono")) if x)
    out: list[tuple[str, str]] = []                 # (format, text); format "raw" is Markdown already

    def walk(el):
        for node in el:
            if node.tag in (qn("w:del"), qn("w:moveFrom"), qn("w:pPr")):
                continue
            if node.tag == qn("w:sdt"):
                ctl = controls.get(ooxml.sdt_tag(node))
                if ctl is None:
                    walk(node)
                    continue
                text = ooxml.plain(node)
                if text != ctl["shown"]:            # the person wrote something else there: their text stands
                    typed.append(text)
                    out.append(("", text))
                elif ctl["type"] == "result":
                    out.append(("raw", "{{result:%s}}" % ctl["key"]))
                else:
                    out.append(("raw", markdown.cite_markdown(ctl["keys"], ctl["locator"], ctl["textual"])))
            elif node.tag == qn("w:hyperlink"):
                rid = node.get(qn("r:id"))
                url = d.part.rels[rid].target_ref if rid and rid in d.part.rels else ""
                text = ooxml.plain(node)
                out.append(("raw", f"<{url}>" if url == text else f"[{text}]({url})" if url else text))
            elif node.tag == qn("w:r"):
                fmt, text = _run_format(node, mono)
                if text:
                    # Word splits one phrase into several runs: neighbours of one format are one phrase
                    if out and out[-1][0] == fmt and fmt != "raw":
                        out[-1] = (fmt, out[-1][1] + text)
                    else:
                        out.append((fmt, text))
            else:
                walk(node)
    walk(p)
    return "".join(t if f == "raw" else _wrap(f, t) for f, t in out).strip()


def _block_markdown(block: dict, d, manifest: dict, typed: list) -> tuple[str, str]:
    """(markdown, kind) of one block of the file as it is now."""
    el = block["el"]
    if block["kind"] == "table":
        rows = [[" ".join(_inline_markdown(p, d, manifest, typed) for p in c.findall(qn("w:p"))).replace("|", "\\|")
                 for c in r.findall(qn("w:tc"))] for r in el.findall(qn("w:tr"))]
        if not rows:
            return "", "table"
        line = lambda r: "| " + " | ".join(r) + " |"
        return "\n".join([line(rows[0]), "|" + " --- |" * len(rows[0]), *map(line, rows[1:])]), "table"
    st = el.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
    role = (manifest.get("styles") or {}).get(st.get(qn("w:val")) if st is not None else "", "body")
    text = _inline_markdown(el, d, manifest, typed)
    if not text and "{{figure}}" in block["text"]:
        return "", "figure"                         # a picture the person put in: named in the summary, not in the text
    numbered = el.find(f"{qn('w:pPr')}/{qn('w:numPr')}") is not None
    if role.startswith("heading"):
        return "#" * (int(role[-1]) + int(manifest.get("heading_shift") or 0)) + " " + text, "heading"
    if role == "title":
        return f"# {text}", "heading"
    ind = el.find(f"{qn('w:pPr')}/{qn('w:ind')}")
    left = int(ind.get(qn("w:left")) or ind.get(qn("w:start")) or 0) if ind is not None else 0
    pad = "  " * max(0, min(round(left / 357) - 1, 2))      # the renderer indents a nested item by 0.63 cm per level
    if role == "bullet" or re.match(r"^[•–]\s", text):
        return pad + "- " + re.sub(r"^[•–]\s+", "", text), "item"
    if role == "numbered" or numbered or re.match(r"^\d+\.\s", text):
        return pad + "1. " + re.sub(r"^\d+\.\s+", "", text), "item"
    if role == "quote":
        return "> " + text, "para"
    if role == "code":
        return "```\n" + ooxml.plain(el) + "\n```", "para"
    if role == "caption":
        m = re.match(r"^\*{0,2}(?:Table|Tabelle|Figure|Abbildung)\s*\*{0,2}\s*\*{0,2}\d+\*{0,2}\s*\*{0,2}[.:]?\*{0,2}\s*(.*)$", text, re.S)
        return ": " + (m.group(1) if m else text), "para"
    return text, "para"


def pull(path: Path, project: str | Path | None = None, out: str | Path | None = None) -> dict:
    path = Path(path).expanduser()
    d, manifest = load(path)
    c = compare(d, manifest)
    old, now, groups = c["old"], c["now"], manifest.get("groups") or []
    match = {i: j for i, j in c["equal"]}
    whole = {}                                       # group -> every one of its blocks is still as rendered
    for i, b in enumerate(old):
        if b.get("g") is not None:
            whole[b["g"]] = whole.get(b["g"], True) and i in match
    by_new: dict[int, int | None] = {j: i for i, j in c["equal"]} | {j: i for i, j in c["changed"]} | {j: i for i, j in c["moved"]}
    typed: list[str] = []
    chunks: list[tuple[str, str]] = []
    emitted: set[int] = set()
    section, sections = None, {g["section"] for g in groups if g.get("section")}
    notes: list[str] = []
    if manifest.get("title_md"):
        chunks.append((manifest["title_md"], "heading"))
    for j, block in enumerate(now):
        i = by_new.get(j)
        g = old[i].get("g") if i is not None else None
        if i is not None and g is None:
            if (i, j) in c["changed"]:
                notes.append(f"text of the template was changed and is not part of the Markdown: {_show(block['text'], 60)}")
            continue                                # cover page, title: the template's, not the text's
        if g is not None and len(sections) > 1 and groups[g].get("section") and groups[g]["section"] != section:
            section = groups[g]["section"]
            chunks.append((f"<!-- section: {section} -->", "para"))
        if g is not None and whole.get(g) and groups[g]["type"] != "sources-heading":
            if g not in emitted:
                emitted.add(g)
                chunks.append((groups[g]["md"], "group"))
            continue
        if g is not None and groups[g]["type"] == "sources-heading":
            continue
        md, kind = _block_markdown(block, d, manifest, typed)
        if kind == "figure":
            notes.append("a picture in the file has no figure in the project and was left out")
        elif md:
            chunks.append((md, kind))
    text, prev = "", ""
    for md, kind in chunks:
        text += ("\n" if kind == "item" and prev == "item" else "\n\n" if text else "") + md
        prev = kind
    text = text.strip() + "\n"

    p = find_project(path, manifest, project)
    kind, name = manifest["target"].split("/", 1)
    if out:
        dest = Path(out).expanduser()
    elif p is not None:
        dest = p.root / manifest["target"] / f"{name}.from-word.md"
    else:
        dest = path.with_name(f"{name}.from-word.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    diff: list[str] = []
    if p is not None and kind == "pieces" and (p.root / manifest["target"] / "text.md").exists():
        source = (p.root / manifest["target"] / "text.md").read_text(encoding="utf-8")
        diff = [ln for ln in difflib.unified_diff(source.splitlines(), text.splitlines(), "text.md", dest.name, lineterm="", n=0)][:60]
    if typed:
        notes.append(f"{len(typed)} controls were typed over; their text is in the Markdown as written, no longer linked to a result or source")
    if c["tracked"]["insertions"] or c["tracked"]["deletions"]:
        notes.append(f"the file has tracked changes ({c['tracked']['insertions']} insertions, {c['tracked']['deletions']} deletions): read as if all were accepted")
    return {"file": str(path), "written": str(dest), "unchanged": len(c["equal"]), "changed": len(c["changed"]), "added": len(c["added"]),
            "deleted": len(c["deleted"]), "moved": len(c["moved"]), "removed_controls": c["removed"], "notes": notes, "diff": diff}
