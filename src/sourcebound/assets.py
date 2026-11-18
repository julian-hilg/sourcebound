"""Designs, templates and packs: how output looks, kept apart from what it says.

    <registry>/designs/<id>/design.yaml      one corporate design: colours, fonts, logo, chart rules
    <registry>/templates/<id>/template.yaml  one output template of a kind (docx, slides, html, ...)
                                             with its files next to it

A **design** is data: a renderer of any format reads the same colours and fonts, so a Word
report, a slide and a chart of one organisation agree.  A **template** belongs to one renderer
kind and names the design it was built for.  A **pack** is a folder that holds `designs/` and
`templates/`; `sb pack install FOLDER` copies both into the registry.  A corporate design is
therefore never part of the Sourcebound checkout: it lives in a pack that an organisation keeps
for itself.  The checkout ships one neutral design (`designs/sourcebound`) as the default and as
the example to copy.
"""
from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

import yaml

from . import config

DEFAULT_DESIGN = "sourcebound"
ID = re.compile(r"[a-z][a-z0-9_-]*")

# Every key a renderer may rely on.  A design file overrides any of them.
BASE_DESIGN: dict = {
    "name": "Sourcebound",
    "colors": {
        "primary": "#1f3a5f",        # headings, rules, the highlighted series
        "accent": "#0b84c6",         # the one accent: links, markers
        "accent_soft": "#cfe6f4",    # the accent as a tint: text on the primary colour, light fills
        "accent_dark": "#075f8f",    # the accent where it must carry text on white
        "ink": "#111418",            # body text
        "ink_soft": "#4a5566",       # secondary text
        "ink_faint": "#8a93a0",      # captions, source lines
        "neutral": "#c9cfd8",        # the non-highlighted series
        "surface": "#f4f6f8",        # table stripes, panels
        "paper": "#ffffff",
        "good": "#1a7f6b",
        "bad": "#c4472b",
    },
    # Series colours for charts with more than "highlighted vs. the rest", in this order.
    "palette": ["#1f3a5f", "#0b84c6", "#8a93a0", "#1a7f6b", "#c4472b", "#b58a2c"],
    "fonts": {
        "body": ["Source Sans 3", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        "heading": ["Source Sans 3", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        "mono": ["Source Code Pro", "Consolas", "Menlo", "monospace"],
        # Font files in the design folder, for renderers that can embed them. `local` lists the names
        # an installed font answers to, so a machine with the fonts installed needs no files:
        #   - {file: Example-Light.otf, weight: 300, local: ["Example Light"]}
        "faces": [],
        "weights": {"light": 300, "regular": 400, "medium": 600},   # which weight plays which role
    },
    "logo": {"file": "", "file_inverse": "", "height_px": 72},
    "charts": {
        "highlight_one": True,       # one series in the primary colour, the rest neutral
        "direct_labels": True,       # values at the marks, no legend where labels fit
        "gridlines": False,
        "min_font_px": 16,           # at the output's native size
        "min_gap_px": 8,             # labels closer than this count as overlapping
    },
    "text": {"source_prefix": {"en": "Source: ", "de": "Quelle: "}, "decimal": {"en": ".", "de": ","}},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _bases() -> list[Path]:
    """Where designs/ and templates/ are looked up: the registry first, then the packs that
    installed plugins bring, then the checkout."""
    from . import plugins
    h = config.hub()
    home = config.home()
    return [b for b in (h.registry, *plugins.load().packs, home) if b is not None]


def _origin(base: Path) -> str:
    return "registry" if base == config.hub().registry else "checkout" if base == config.home() else "plugin"


def _find(kind: str, ident: str) -> Path | None:
    for base in _bases():
        d = base / kind / ident
        if (d / f"{kind[:-1]}.yaml").exists():
            return d
    return None


def _listing(kind: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for base in _bases():
        for f in sorted((base / kind).glob(f"*/{kind[:-1]}.yaml")):
            if f.parent.name not in seen:
                try:
                    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError as e:
                    doc = {"error": str(e)}
                seen[f.parent.name] = {"id": f.parent.name, "folder": str(f.parent),
                                       "origin": _origin(base), **doc}
    return [seen[k] for k in sorted(seen)]


# ------------------------------------------------------------------ designs
def design(ident: str | None = None) -> dict:
    """A design with every key of BASE_DESIGN filled in; `folder` is where its files are."""
    ident = ident or DEFAULT_DESIGN
    d = _find("designs", ident)
    if d is None:
        if ident == DEFAULT_DESIGN:
            return {**BASE_DESIGN, "id": ident, "folder": None}
        raise FileNotFoundError(f"no design {ident} (sb design list)")
    doc = yaml.safe_load((d / "design.yaml").read_text(encoding="utf-8")) or {}
    return {**_merge(BASE_DESIGN, doc), "id": ident, "folder": str(d)}


def designs() -> list[dict]:
    rows = [{"id": x["id"], "name": x.get("name", x["id"]), "origin": x["origin"], "folder": x["folder"],
             "colors": _merge(BASE_DESIGN, x)["colors"], "error": x.get("error")} for x in _listing("designs")]
    if not any(r["id"] == DEFAULT_DESIGN for r in rows):
        rows.insert(0, {"id": DEFAULT_DESIGN, "name": BASE_DESIGN["name"], "origin": "built in", "folder": None,
                        "colors": BASE_DESIGN["colors"], "error": None})
    return rows


def new_design(ident: str, name: str) -> Path:
    """A design folder in the registry with every key written out, to be edited."""
    if not ID.fullmatch(ident):
        raise ValueError("design id: lowercase letters, digits, - and _")
    d = config.hub().registry / "designs" / ident
    if d.exists():
        raise FileExistsError(f"{d} exists -- edit it instead")
    d.mkdir(parents=True)
    head = (f"# Corporate design `{ident}` (created {date.today()}). Every renderer reads these values.\n"
            "# Put logo and font files into this folder and name them below. Colours are hex values.\n")
    (d / "design.yaml").write_text(head + yaml.safe_dump({**BASE_DESIGN, "name": name}, sort_keys=False, allow_unicode=True),
                                   encoding="utf-8")
    return d


# ------------------------------------------------------------------ templates
def template(ident: str) -> dict:
    d = _find("templates", ident)
    if d is None:
        raise FileNotFoundError(f"no template {ident} (sb template list)")
    doc = yaml.safe_load((d / "template.yaml").read_text(encoding="utf-8")) or {}
    if not doc.get("kind"):
        raise ValueError(f"{d / 'template.yaml'}: `kind:` is missing (docx, slides, html, ...)")
    return {**doc, "id": ident, "folder": str(d)}


def templates(kind: str | None = None) -> list[dict]:
    rows = [{"id": x["id"], "kind": x.get("kind", ""), "title": x.get("title", ""), "design": x.get("design", ""),
             "for": x.get("for", []), "origin": x["origin"], "folder": x["folder"], "error": x.get("error")}
            for x in _listing("templates")]
    return [r for r in rows if kind is None or r["kind"] == kind]


def add_template(folder: str | Path, ident: str | None = None) -> Path:
    """Register a template folder (it must hold a template.yaml with `kind:`) by copying it."""
    src = Path(folder).expanduser().resolve()
    if not (src / "template.yaml").exists():
        raise FileNotFoundError(f"{src} has no template.yaml")
    ident = ident or src.name
    if not ID.fullmatch(ident):
        raise ValueError("template id: lowercase letters, digits, - and _")
    dest = config.hub().registry / "templates" / ident
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("~$*", ".DS_Store", "Thumbs.db", "__pycache__"))
    template(ident)                                 # fails here if the file is not usable
    return dest


def new_template(ident: str, kind: str, *, title: str = "", design_id: str | None = None) -> Path:
    """A starting template of `kind` in the registry, written by the plugin that renders the kind."""
    from . import plugins
    if not ID.fullmatch(ident):
        raise ValueError("template id: lowercase letters, digits, - and _")
    reg = plugins.load()
    if kind not in reg.scaffolds:
        known = ", ".join(sorted(reg.scaffolds)) or "none installed"
        raise ValueError(f"no plugin offers a starting template of kind {kind} (kinds: {known})")
    dest = config.hub().registry / "templates" / ident
    if dest.exists():
        raise FileExistsError(f"{dest} exists -- edit it, or choose another id")
    dest.mkdir(parents=True)
    try:
        reg.scaffolds[kind](dest, design(design_id))
        f = dest / "template.yaml"
        doc = (yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None) or {}
        doc = {"kind": kind, "title": title or doc.get("title") or ident, "design": design_id or DEFAULT_DESIGN,
               **{k: v for k, v in doc.items() if k not in {"kind", "title", "design"}}}
        f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


# ------------------------------------------------------------------ packs
PACK_IGNORE = ("~$*", ".DS_Store", "Thumbs.db", "__pycache__")


def _ignored(rel: Path) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(part, pat) for part in rel.parts for pat in PACK_IGNORE)


def tree_sha256(folder: str | Path, *, only: tuple[str, ...] = ()) -> str:
    """One sha256 over a folder: every file's relative path and content, in sorted order.

    Files a pack install skips (Office lock files, .DS_Store, Thumbs.db, __pycache__) are left
    out, so a pack folder and the copy installed from it give the same value.  `only` limits the
    hash to these top-level folders (e.g. designs and templates).
    """
    import hashlib
    root = Path(folder)
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = f.relative_to(root)
        if _ignored(rel) or (only and rel.parts[0] not in only):
            continue
        h.update(rel.as_posix().encode("utf-8") + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def file_sha256(path: str | Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack_records() -> list[dict]:
    """What was installed from which pack: `<registry>/packs/<name>.yaml`, newest first."""
    d = config.hub().registry / "packs"
    out = []
    for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        try:
            rec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(rec, dict):
            out.append({**rec, "record": f.name})
    return sorted(out, key=lambda r: str(r.get("installed") or ""), reverse=True)


def _installed_from(kind: str, ident: str, records: list[dict]) -> dict | None:
    return next((r for r in records if ident in (r.get(kind) or [])), None)


def install_pack(folder: str | Path, *, provenance: dict | None = None) -> dict:
    """Copy the designs and templates of a pack folder (or a checked .zip, see packzip) into the registry.

    The install is recorded in `<registry>/packs/<name>.yaml`: where it came from (path), the
    sha256 of the source (the zip file, or the folder's files) and of the installed content.  A
    design or template that is installed already is compared with the new one first: the result
    lists it under `changed` (with the pack it came from) or `unchanged`.
    """
    if str(folder).lower().endswith(".zip"):
        from . import packzip
        return packzip.install(folder)
    src = Path(folder).expanduser().resolve()
    reg = config.hub().registry
    records = pack_records()
    out: dict = {"designs": [], "templates": [], "skills": [], "replaced": [], "changed": [], "unchanged": []}
    marker = {"designs": "design.yaml", "templates": "template.yaml", "skills": "SKILL.md"}
    for kind in ("designs", "templates", "skills"):
        for d in sorted((src / kind).glob("*")):
            if (d / marker[kind]).exists():
                dest = reg / kind / d.name
                if dest.exists():
                    out["replaced"].append(f"{kind[:-1]} {d.name}")
                    if tree_sha256(dest) == tree_sha256(d):
                        out["unchanged"].append(f"{kind[:-1]} {d.name}")
                    else:
                        was = _installed_from(kind, d.name, records)
                        out["changed"].append(f"{kind[:-1]} {d.name}" + (
                            f" (installed {str(was.get('installed', ''))[:10]} from {was.get('source') or was.get('file')})" if was else ""))
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(d, dest, ignore=shutil.ignore_patterns(*PACK_IGNORE))
                out[kind].append(d.name)
    if not out["designs"] and not out["templates"] and not out["skills"]:
        raise FileNotFoundError(f"{src} holds neither designs/<id>/design.yaml, templates/<id>/template.yaml nor skills/<id>/SKILL.md")
    if provenance is None:                       # a folder: its own pack.yaml, else the folder's name
        manifest = {}
        if (src / "pack.yaml").is_file():
            manifest = yaml.safe_load((src / "pack.yaml").read_text(encoding="utf-8")) or {}
        provenance = {"name": str(manifest.get("name") or src.name), "version": str(manifest.get("version") or ""),
                      "description": str(manifest.get("description") or ""), "source": str(src), "source_kind": "folder",
                      "sha256": tree_sha256(src)}
    out["pack"] = {**provenance, "files": sum(1 for f in src.rglob("*") if f.is_file() and not _ignored(f.relative_to(src)))}
    # the same pack installed before: did its content change? (content, so that a zip and the
    # folder it was made from count as the same pack)
    content = tree_sha256(src, only=("designs", "templates", "skills"))
    out["previous"] = next((r for r in records if r.get("name") == provenance["name"]), None)
    out["source_differs"] = bool(out["previous"] and out["previous"].get("content_sha256")
                                 and out["previous"]["content_sha256"] != content)
    from datetime import datetime, timezone
    record = {**provenance, "content_sha256": content,
              "installed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "designs": out["designs"], "templates": out["templates"], "skills": out["skills"]}
    (reg / "packs").mkdir(parents=True, exist_ok=True)
    config.write_atomic(reg / "packs" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', record['name'])}.yaml",
                        yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return out


def export_pack(folder: str | Path, *, designs_: list[str], templates_: list[str], skills_: list[str] = ()) -> Path:
    """Write the named designs, templates and skills (installed from packs) as a pack folder, or as a
    .zip (to carry to another machine)."""
    if str(folder).lower().endswith(".zip"):
        import tempfile

        from . import packzip
        with tempfile.TemporaryDirectory(prefix="sb-pack-") as tmp:
            export_pack(tmp, designs_=designs_, templates_=templates_, skills_=skills_)
            return packzip.export(folder, Path(tmp))
    dest = Path(folder).expanduser().resolve()
    skills = {d.name: d for d in pack_skills()}
    for kind, ids in (("designs", designs_), ("templates", templates_), ("skills", skills_)):
        for ident in ids:
            d = skills.get(ident) if kind == "skills" else _find(kind, ident)
            if d is None:
                raise FileNotFoundError(f"no {kind[:-1]} {ident}")
            (dest / kind).mkdir(parents=True, exist_ok=True)
            shutil.copytree(d, dest / kind / ident, dirs_exist_ok=True)
    return dest


def pack_skills() -> list[Path]:
    """Playbooks for agents that installed packs brought (<registry>/skills/<id>/SKILL.md)."""
    folder = config.hub().registry / "skills"
    return sorted(d for d in folder.glob("*") if (d / "SKILL.md").is_file()) if folder.is_dir() else []
