"""Rendering: one `Document`, many formats.

    sb render TARGET --template ID [--design ID]

TARGET is a piece (`pieces/<id>`, or just its id) or a deliverable folder
(`deliverables/<name>`).  Both become a `Document`: text in the handover notation, the
recorded results, tables, figures and sources it refers to.  The template's `kind:` selects the
renderer (a plugin); the design supplies colours, fonts and logo.  Output and a manifest
(`render.json`: what was rendered from which results, with which template) go to

    pieces/<id>/render/<template>/           for a piece
    dist/render/<deliverable>/<template>/    for a deliverable

The core brings two renderers that need no extra package: `markdown` (numbers filled in,
sources listed) and `text` (plain text for a post or an e-mail).  Notation, as in the handover:

    {{result:key}}   [@key; @other, p. 3]   {{table:name}}   ![caption](figures/x.png){#label}
"""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import assets, config, ledger, plugins, results
from .handover import MD_CITE, MD_RESULT, _group, _MATH

FORMAT = {"format": "sourcebound-render", "version": 1}


@dataclass
class Section:
    name: str
    markdown: str
    appendix: bool = False
    source: str = ""                # the file it came from, relative to the project


@dataclass
class Document:
    project: config.Project
    name: str                       # piece id or deliverable folder name
    kind: str                       # "piece" | "deliverable"
    title: str
    lang: str
    folder: Path                    # where its sources are
    sections: list[Section] = field(default_factory=list)
    meta: dict = field(default_factory=dict)            # piece.yaml, or title/subtitle/author/date/keywords
    data: dict = field(default_factory=dict)            # structured content next to the text (slides.yaml, ...)
    results: dict = field(default_factory=dict)         # key -> {value, display, unit, provenance, ...}
    tables: dict = field(default_factory=dict)          # name -> {"columns": [...], "rows": [[...]]}
    figures: dict = field(default_factory=dict)         # file name -> Path
    references: dict = field(default_factory=dict)      # citation key -> bibliography fields
    web_sources: dict = field(default_factory=dict)     # W-0001 -> {title, url, publisher, accessed, ...}

    @property
    def text(self) -> str:
        return "\n\n".join(s.markdown.strip() for s in self.sections)

    @property
    def german(self) -> bool:
        return self.lang.startswith("de")


# ------------------------------------------------------------------ sources and citations
def bib_fields(text: str) -> dict[str, dict]:
    """The fields a reference list needs, per citation key, from a BibLaTeX file."""
    out = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        body = _group(text, text.index("{", m.start()))
        if body is None:
            continue
        entry, text_, i = {"type": m.group(1).lower()}, body[0][body[0].index(",") + 1:], 0
        while (f := re.compile(r"[,\s]*([A-Za-z]+)\s*=\s*").match(text_, i)):
            g = _group(text_, f.end()) or _group(text_, f.end(), '"', '"')
            value, i = (g[0], g[1]) if g else (text_[f.end():].split(",")[0], f.end() + len(text_[f.end():].split(",")[0]))
            if f.group(1).lower() in {"author", "editor"}:      # {An Institution} is one name: keep it in one piece
                value = re.sub(r"\{([^{}]*)\}", lambda g: g.group(1).replace(" ", " "), value)
            entry[f.group(1).lower()] = re.sub(r"[ \t\r\n]+", " ", re.sub(r"[{}]", "", value)).strip()
        if entry.get("pages"):
            entry["pages"] = re.sub(r"-{2,3}", "\u2013", entry["pages"])     # a page range as it is printed
        year = re.match(r"\d{4}", entry.get("date") or entry.get("year") or "")
        out[m.group(2)] = {"type": entry["type"], "year": year.group(0) if year else "",
                           **{k: entry[k] for k in ("author", "editor", "title", "journaltitle", "journal", "booktitle",
                                                    "publisher", "institution", "volume", "number", "pages", "doi", "url",
                                                    "eprint", "howpublished", "organization") if entry.get(k)}}
    return out


def _surname(name: str) -> str:
    return (name.split(",")[0] if "," in name else name.strip().split(" ")[-1]).strip()


def cite_label(key: str, doc: Document) -> tuple[str, str] | None:
    """(who, year) of a source for an author-year citation; None if the key is unknown."""
    ref = doc.references.get(key)
    if ref:
        names = [n.strip() for n in re.split(r"\s+and\s+", ref.get("author") or ref.get("editor") or "") if n.strip()]
        who = (_surname(names[0]) if len(names) == 1 else f"{_surname(names[0])} and {_surname(names[1])}" if len(names) == 2
               else f"{_surname(names[0])} et al." if names else ref.get("title") or key)
        return who.replace(" ", " "), ref.get("year") or "n.d."
    web = doc.web_sources.get(key)
    if web:
        who = str(web.get("author") or "").strip("{}") or web.get("publisher") or web.get("title") or key
        return who, str(web.get("date") or "")[:4] or "n.d."      # the day it was archived is not when it was published
    return None


def source_line(key: str, doc: Document, *, markup: bool = False) -> str:
    """One entry of a source list. `markup=True` sets the journal in *italics* (Markdown)."""
    it = (lambda s: f"*{s}*") if markup else (lambda s: s)
    ref = doc.references.get(key)
    if ref:
        names = [n.strip().replace(" ", " ") for n in re.split(r"\s+and\s+", ref.get("author") or ref.get("editor") or "") if n.strip()]
        who = "; ".join(names[:6]) + (" et al." if len(names) > 6 else "")
        where = ref.get("journaltitle") or ref.get("journal") or ref.get("booktitle")
        issue = (ref.get("volume") or "") + (f"({ref['number']})" if ref.get("number") else "")
        link = f"https://doi.org/{ref['doi']}" if ref.get("doi") else ref.get("url")
        parts = [f"{who or ref.get('title') or key} ({ref.get('year') or 'n.d.'}).",
                 f"{ref['title']}." if who and ref.get("title") else "",
                 (f"{it(where)}{' ' + issue if issue else ''}{', ' + ref['pages'] if ref.get('pages') else ''}." if where
                  else f"{ref.get('publisher') or ref.get('institution')}." if ref.get("publisher") or ref.get("institution") else ""),
                 link or ""]
        return " ".join(p for p in parts if p)
    web = doc.web_sources.get(key)
    if web:
        who, year = cite_label(key, doc)
        return " ".join(p for p in (f"{who} ({year}).", f"{web['title']}." if web.get("title") else "",
                                   "" if str(web.get("url") or "").startswith("file:") else str(web.get("url") or "")) if p)
    return key


def cited(text: str) -> list[str]:
    """Citation keys in order of first use (not inside code or mathematics)."""
    seen: list[str] = []
    for k in MD_CITE.findall(_MATH.sub(" ", text)):
        if k not in seen:
            seen.append(k)
    return seen


def fill(text: str, doc: Document, *, cite=None, missing: list | None = None) -> str:
    """The text with recorded numbers filled in.

    `cite(keys, locator, textual) -> str` formats one citation group; without it citations are
    left as written.  Keys of results the text uses but nobody recorded are appended to `missing`.
    """
    def number(m):
        key = m.group(1).strip()
        if key not in doc.results and missing is not None and key not in missing:
            missing.append(key)
        return str(doc.results[key]["display"]) if key in doc.results else f"?{key}"
    held: list[str] = []

    def keep(m):
        held.append(MD_RESULT.sub(number, m.group(0)) if m.group(0).startswith("$") else m.group(0))
        return f"\0{len(held) - 1}\0"
    s = MD_RESULT.sub(number, _MATH.sub(keep, text))
    if cite is not None:
        def group(m):
            items = [re.match(r"^(.*?)@([A-Za-z][\w:.-]*\w)(.*)$", x.strip()) for x in m.group(1).split(";")]
            if not all(items):
                return m.group(0)
            return cite([i.group(2) for i in items], items[-1].group(3).strip(" ,"), False)
        s = re.sub(r"\[([^\[\]]*@[A-Za-z][^\[\]]*)\](?!\()", group, s)
        s = MD_CITE.sub(lambda m: cite([m.group(1)], "", True), s)
    return re.sub(r"\0(\d+)\0", lambda m: held[int(m.group(1))], s)


def plain_text(doc: Document, *, sources_heading: str | None = None, missing: list | None = None) -> str:
    """Plain text for a post or an e-mail: no markup, numbered sources at the end."""
    order: list[str] = []

    def cite(keys, locator, textual):
        for k in keys:
            if k not in order:
                order.append(k)
        nums = ", ".join(str(order.index(k) + 1) for k in keys)
        if textual:
            who = cite_label(keys[0], doc)
            return f"{who[0] if who else keys[0]} [{nums}]"
        return f"[{nums}]"
    s = fill(doc.text, doc, cite=cite, missing=missing)
    s = re.sub(r"(?m)^#{1,6}\s+(.*?)(?:\s*\{#[^}]*\})?$", r"\1", s)                      # headings
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)(?:\{#[^}]*\})?", "", s)                           # images
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)                                 # links
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", s)
    s = re.sub(r"`([^`\n]*)`", r"\1", s)
    s = re.sub(r"\{\{(?:ref|table):[^}]*\}\}", "", s)
    s = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", s)).strip()
    if order:
        head = sources_heading or ("Quellen:" if doc.german else "Sources:")
        s += f"\n\n{head}\n" + "\n".join(f"{n}. {source_line(k, doc)}" for n, k in enumerate(order, 1))
    return s + "\n"


# ------------------------------------------------------------------ building a Document
def _commit(root: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() or None if r.returncode == 0 else None


def _evidence(p: config.Project) -> tuple[dict, dict]:
    """(bibliography fields, web sources) known to the project."""
    refs: dict = {}
    for f in [p.root / "evidence" / "inbox.bib", *sorted(p.root.glob("deliverables/*/references.bib")),
              p.root / "evidence" / "references.bib"]:
        if f.exists():
            refs.update(bib_fields(f.read_text(encoding="utf-8", errors="replace")))
    web = {s["id"]: s for s in json.loads(json.dumps(ledger.load(p)["sources"], default=str)) if s.get("id")}
    return refs, web


evidence = _evidence          # for plugins: the sources of a project without building a Document


def _tables(folder: Path) -> dict:
    """Tables of a folder for display: the cells as printed where the folder knows them (a
    `.display.csv` in a handover, the generated `.tex` in a project), else the exact values."""
    from . import tables as _t
    from .handover import to_markdown
    clean = lambda c: to_markdown(c)[0].strip() if "\\" in c else c.replace("---", "\u2014").replace("--", "\u2013")
    out = {}
    for f in sorted(folder.glob("*.csv")) if folder.is_dir() else []:
        if f.name.endswith(".display.csv"):
            continue
        shown = f.with_name(f.stem + ".display.csv")
        if shown.exists():
            rows = list(csv.reader(io.StringIO(shown.read_text(encoding="utf-8"))))
        else:
            printed = _t.displayed(f.with_suffix(".tex"))
            rows = [printed[0], *printed[1]] if printed else list(csv.reader(io.StringIO(f.read_text(encoding="utf-8"))))
        rows = [[clean(c) for c in r] for r in rows]
        out[f.stem] = {"columns": rows[0] if rows else [], "rows": rows[1:]}
    return out


def from_piece(p: config.Project, piece_id: str) -> Document:
    from . import pieces
    meta = pieces.get(piece_id, p)
    folder = pieces.folder(p, piece_id)
    text = (folder / "text.md").read_text(encoding="utf-8") if (folder / "text.md").exists() else ""
    data = {}
    for f in sorted(folder.glob("*.yaml")):
        if f.name != "piece.yaml":
            data[f.stem] = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    refs, web = _evidence(p)
    figures = {f.name: f for d in (p.root / "figures", folder / "figures") if d.is_dir() for f in sorted(d.glob("*")) if f.is_file()}
    return Document(project=p, name=piece_id, kind="piece", title=meta.get("title") or piece_id, lang=meta.get("lang") or p.lang,
                    folder=folder, sections=[Section("text", text, source=f"pieces/{piece_id}/text.md")], meta=meta, data=data,
                    results=results.load(p), tables={**_tables(p.root / "tables"), **_tables(folder / "tables")},
                    figures=figures, references=refs, web_sources=web)


def from_deliverable(p: config.Project, name: str) -> Document:
    """A deliverable through the handover (built fresh, so the Document matches the files)."""
    from . import handover
    doc = handover.build(p)
    entry = next((d for d in doc["deliverables"] if d["name"] == name), None)
    if entry is None:
        raise FileNotFoundError(f"no deliverable {name} (found: {', '.join(d['name'] for d in doc['deliverables']) or 'none'})")
    out = p.root / "dist" / "handover"
    refs, web = _evidence(p)
    if (out / "references.bib").exists():
        refs.update(bib_fields((out / "references.bib").read_text(encoding="utf-8")))
    for key in web:                                 # a web source is described by the ledger, not by the copy of it in
        refs.pop(key, None)                         # the bibliography, which is older (no date until the next `sb bib sync`)
    return Document(project=p, name=name, kind="deliverable", title=entry.get("title") or p.title, lang=p.lang,
                    folder=p.root / "deliverables" / name,
                    sections=[Section(Path(s["file"]).stem, (out / s["file"]).read_text(encoding="utf-8"), s["appendix"], s["source"])
                              for s in entry["sections"]],
                    meta={k: entry[k] for k in ("title", "subtitle", "author", "date", "keywords") if entry.get(k)},
                    results=results.load(p), tables=_tables(out / "tables"),
                    figures={f.name: f for f in sorted((out / "figures").glob("*"))} if (out / "figures").is_dir() else {},
                    references=refs, web_sources=web)


def document(target: str, project: config.Project | None = None) -> Document:
    p = project or config.project()
    t = target.strip("/").replace("\\", "/")
    if t.startswith("deliverables/"):
        return from_deliverable(p, t.split("/")[1])
    return from_piece(p, t.split("/")[1] if t.startswith("pieces/") else t)


# ------------------------------------------------------------------ rendering
def out_dir(doc: Document, template_id: str) -> Path:
    return (doc.folder / "render" / template_id if doc.kind == "piece"
            else doc.project.root / "dist" / "render" / doc.name / template_id)


def render(target: str, template_id: str, *, design_id: str | None = None, project: config.Project | None = None) -> dict:
    """Render a piece or deliverable with a registered template; returns the manifest."""
    doc = document(target, project)
    tpl = assets.template(template_id)
    reg = plugins.load()
    if tpl["kind"] not in reg.renderers:
        have = ", ".join(sorted(reg.renderers))
        raise RuntimeError(f"template {template_id} is of kind `{tpl['kind']}`, and no installed plugin renders it "
                           f"(installed kinds: {have}; see `sb plugin list`)")
    design = assets.design(design_id or doc.meta.get("design") or tpl.get("design"))
    problems = [x for fn in reg.checks.get(tpl["kind"], []) for x in fn(doc, tpl, design)]
    if problems:
        raise ValueError("not rendered:\n  " + "\n  ".join(problems))
    out = out_dir(doc, template_id)
    out.mkdir(parents=True, exist_ok=True)
    try:
        files = reg.renderers[tpl["kind"]].fn(doc, tpl, design, out) or []
    except PermissionError as e:                    # Windows: a viewer holds a file of the last render
        raise RuntimeError(f"not rendered: {e.filename or out} is open in another program (a PDF or image viewer?); "
                           "close it and render again") from e
    notes: list[str] = []
    if isinstance(files, tuple):                    # a renderer may return (files, notes): what it adjusted or could not do
        files, notes = list(files[0]), [str(n) for n in files[1]]
    used = sorted({k.strip() for s in doc.sections for k in MD_RESULT.findall(s.markdown)}
                  | {k.strip() for k in MD_RESULT.findall(json.dumps(doc.data, ensure_ascii=False))})
    manifest = {**FORMAT, "target": f"{'pieces' if doc.kind == 'piece' else 'deliverables'}/{doc.name}",
                "template": template_id, "kind": tpl["kind"], "design": design["id"],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": _commit(doc.project.root),
                "files": sorted(Path(f).relative_to(out).as_posix() for f in files),
                "results": {k: doc.results[k]["display"] for k in used if k in doc.results},
                "missing_results": [k for k in used if k not in doc.results],
                "sources": cited(doc.text), "notes": notes}
    config.write_atomic(out / "render.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return {**manifest, "folder": str(out)}


def renders(folder: Path) -> list[dict]:
    """Manifests of what was rendered below `folder` (a piece's render/ or dist/render/<name>/)."""
    out = []
    for f in sorted(folder.glob("*/render.json")) if folder.is_dir() else []:
        try:
            out.append({**json.loads(f.read_text(encoding="utf-8")), "folder": f.parent.as_posix()})
        except json.JSONDecodeError:
            continue
    return out


def stale(manifest: dict, current: dict) -> list[str]:
    """Result keys whose recorded value changed since a render."""
    return sorted(k for k, shown in (manifest.get("results") or {}).items()
                  if k not in current or str(current[k]["display"]) != str(shown))


# ------------------------------------------------------------------ the two built-in renderers
def _markdown(doc: Document, template: dict, design: dict, out: Path) -> list[Path]:
    order: list[str] = []

    def cite(keys, locator, textual):
        order.extend(k for k in keys if k not in order)
        labels = [cite_label(k, doc) or (k, "") for k in keys]
        if textual:
            return f"{labels[0][0]} ({labels[0][1]})"
        return "(" + "; ".join(f"{w} {y}".strip() for w, y in labels) + (f", {locator}" if locator else "") + ")"
    body = fill(doc.text, doc, cite=cite)
    body = re.sub(r"\{\{table:([^}]+)\}\}", lambda m: _md_table(doc.tables.get(m.group(1).strip())) or m.group(0), body)
    if order:
        body += f"\n\n## {'Quellen' if doc.german else 'Sources'}\n\n" + "\n".join(f"- {source_line(k, doc, markup=True)}" for k in order)
    head = "" if re.match(r"\s*# ", body) else f"# {doc.title}\n\n"
    f = out / f"{doc.name}.md"
    f.write_text(head + body.strip() + "\n", encoding="utf-8")
    return [f]


def _md_table(t: dict | None) -> str:
    if not t:
        return ""
    line = lambda r: "| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |"
    return "\n".join([line(t["columns"]), "|" + " --- |" * len(t["columns"]), *map(line, t["rows"])])


def _text(doc: Document, template: dict, design: dict, out: Path) -> list[Path]:
    f = out / f"{doc.name}.txt"
    f.write_text(plain_text(doc, sources_heading=template.get("sources_heading")), encoding="utf-8")
    return [f]


def register_builtin(api) -> None:
    api.renderer("markdown", _markdown, title="Markdown with numbers filled in and a source list", outputs=(".md",))
    api.renderer("text", _text, title="Plain text (post, e-mail) with numbered sources", outputs=(".txt",))
