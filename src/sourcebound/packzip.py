"""A pack as one .zip file: checked completely before anything is copied.

    sb pack install firm-pack.zip
    sb pack export firm-pack.zip --design firm --template firm-report

A pack is data: designs, templates and playbooks for agents. A zip may hold only that:

* `designs/<id>/...`, `templates/<id>/...` and `skills/<id>/...` (a playbook for Claude Code:
  `SKILL.md` and other text), `docs/<id>.md` (pages the web view's Documentation shows); at the
  top also `pack.yaml`, `README*`, `LICENSE*`.
  One folder around everything is allowed (a zipped pack folder).
* no absolute paths, no `..`, no links; ids are lowercase letters, digits, `-` and `_`
* only data file types (EXTENSIONS): no programs, no Python. The one script a template may carry is
  the layout check of a slide template (`layout.js`), which runs in the browser that lays out slides.
* at most MAX_FILES files, MAX_TOTAL bytes unpacked, MAX_FILE per file, and no file that unpacks to
  more than MAX_RATIO times its packed size (a zip bomb)
* every design folder has `design.yaml`, every template folder `template.yaml`, every skill folder
  `SKILL.md`; a skill holds text only (SKILL_EXTENSIONS)

`pack.yaml` is optional: `name`, `version`, `description`. Installing records it in
`<registry>/packs/<name>.yaml` with the date, the ids, the path of the zip and its sha256 (and of
the installed content), so the installed version can be looked up and traced to its file.
A design or template with an id that is already installed is replaced; the result says which, and
which of them differ from what was installed.
"""
from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

MAX_FILES = 2000
MAX_TOTAL = 200 * 1024 * 1024
MAX_FILE = 50 * 1024 * 1024
MAX_RATIO = 100
EXTENSIONS = {
    ".yaml", ".yml", ".json", ".md", ".txt",
    ".docx", ".dotx", ".dotm", ".xlsx", ".xltx", ".pptx", ".potx",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".emf",
    ".otf", ".ttf", ".woff", ".woff2",
    ".css", ".html", ".j2", ".jinja", ".tex", ".sty", ".cls", ".bib",
}
SKILL_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json"}
SCRIPTS = {"layout.js"}                     # allowed by name, inside a template folder only
TOP = re.compile(r"^(pack\.ya?ml|README[^/]*|LICEN[CS]E[^/]*)$", re.I)
ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
IGNORED = re.compile(r"(^|/)(__MACOSX/|\.DS_Store$|Thumbs\.db$|~\$)")


def check(path: str | Path) -> dict:
    """What the zip would install, or ValueError naming every problem. Reads, never writes."""
    z = Path(path).expanduser()
    if not zipfile.is_zipfile(z):
        raise ValueError(f"{z} is not a zip file")
    problems: list[str] = []
    with zipfile.ZipFile(z) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not IGNORED.search(i.filename)]
        prefix = _prefix([i.filename for i in infos])
        if len(infos) > MAX_FILES:
            problems.append(f"{len(infos)} files (at most {MAX_FILES})")
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL:
            problems.append(f"{total / 1e6:.0f} MB unpacked (at most {MAX_TOTAL / 1e6:.0f} MB)")
        ids: dict[str, set[str]] = {"designs": set(), "templates": set(), "skills": set()}
        has: set[str] = set()
        docs: set[str] = set()
        manifest = {}
        for i in infos:
            name = i.filename.replace("\\", "/")
            rel = name[len(prefix):] if prefix else name
            p = PurePosixPath(rel)
            mode = (i.external_attr >> 16) & 0o170000
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in p.parts:
                problems.append(f"{name}: path leaves the pack")
                continue
            if mode == stat.S_IFLNK:
                problems.append(f"{name}: a link")
                continue
            if i.file_size > MAX_FILE:
                problems.append(f"{name}: {i.file_size / 1e6:.0f} MB (at most {MAX_FILE / 1e6:.0f} MB per file)")
            if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > 1_000_000:
                problems.append(f"{name}: unpacks to {i.file_size / i.compress_size:.0f} times its size")
            if len(p.parts) == 1:
                if TOP.match(rel):
                    if rel.lower() in ("pack.yaml", "pack.yml"):
                        try:
                            manifest = yaml.safe_load(zf.read(i).decode("utf-8")) or {}
                        except (yaml.YAMLError, UnicodeDecodeError) as e:
                            problems.append(f"{rel}: not readable ({e})")
                    continue
                problems.append(f"{rel}: only designs/, templates/, skills/, docs/, pack.yaml, README and LICENSE may be at the top")
                continue
            kind = p.parts[0]
            if kind == "docs":                         # one level: docs/<id>.md, Markdown only
                if len(p.parts) != 2 or p.suffix.lower() != ".md" or not ID.match(p.stem):
                    problems.append(f"{rel}: docs/ holds pages as docs/<id>.md (lowercase id)")
                else:
                    docs.add(p.stem)
                continue
            if kind not in ids or len(p.parts) < 3:
                problems.append(f"{rel}: not inside designs/<id>/, templates/<id>/ or skills/<id>/")
                continue
            ident = p.parts[1]
            if not ID.match(ident):
                problems.append(f"{rel}: id `{ident}` (lowercase letters, digits, - and _)")
                continue
            ids[kind].add(ident)
            suffix = p.suffix.lower()
            if kind == "skills" and suffix not in SKILL_EXTENSIONS:
                problems.append(f"{rel}: a skill holds text only ({', '.join(sorted(SKILL_EXTENSIONS))})")
            elif not (suffix in EXTENSIONS or (kind == "templates" and p.name in SCRIPTS)):
                problems.append(f"{rel}: file type {suffix or '(none)'} is not allowed in a pack")
            if len(p.parts) == 3 and p.name in ("design.yaml", "template.yaml", "SKILL.md"):
                has.add(f"{kind}/{ident}/{p.name}")
        for kind, need in (("designs", "design.yaml"), ("templates", "template.yaml"), ("skills", "SKILL.md")):
            for ident in sorted(ids[kind]):
                if f"{kind}/{ident}/{need}" not in has:
                    problems.append(f"{kind}/{ident}: no {need}")
        if not any(ids.values()) and not docs:
            problems.append("neither designs/<id>/, templates/<id>/ nor skills/<id>/ in the zip")
    if problems:
        raise ValueError(f"pack {z.name} refused, nothing was installed:\n  " + "\n  ".join(sorted(set(problems))))
    return {"file": str(z), "prefix": prefix, "designs": sorted(ids["designs"]), "templates": sorted(ids["templates"]), "skills": sorted(ids["skills"]), "docs": sorted(docs),
            "files": len(infos), "bytes": total, "name": str(manifest.get("name") or z.stem),
            "version": str(manifest.get("version") or ""), "description": str(manifest.get("description") or "")}


def _prefix(names: list[str]) -> str:
    """The one folder around everything, if the zip is a zipped pack folder (`firm-pack/designs/...`)."""
    tops = {n.replace("\\", "/").split("/")[0] for n in names}
    if len(tops) == 1:
        top = next(iter(tops))
        if top not in ("designs", "templates") and all("/" in n.replace("\\", "/") for n in names):
            return top + "/"
    return ""


def install(path: str | Path) -> dict:
    """Check, unpack into a temporary folder, install from there; returns what was installed and replaced."""
    from . import assets
    info = check(path)
    z = Path(path).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="sb-pack-") as tmp, zipfile.ZipFile(z) as zf:
        root = Path(tmp)
        for i in zf.infolist():
            name = i.filename.replace("\\", "/")
            if i.is_dir() or IGNORED.search(name):
                continue
            rel = name[len(info["prefix"]):] if info["prefix"] else name
            dest = (root / rel).resolve()
            if not dest.is_relative_to(root.resolve()):          # checked above; a second guard costs nothing
                raise ValueError(f"{name}: path leaves the pack")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(i) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
        done = assets.install_pack(root, provenance={
            "name": info["name"], "version": info["version"], "description": info["description"],
            "source": str(z), "source_kind": "zip", "file": z.name, "sha256": assets.file_sha256(z)})
    done["pack"] = {**done["pack"], "files": info["files"]}
    return done


def export(path: str | Path, folder: Path, *, name: str = "", version: str = "") -> Path:
    """Zip a pack folder (as `export_pack` writes it), with a pack.yaml, after checking it like an install."""
    dest = Path(path).expanduser().resolve()
    manifest = {"name": name or dest.stem, "version": version or datetime.now().strftime("%Y-%m-%d")}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pack.yaml", yaml.safe_dump(manifest, sort_keys=False))
        for f in sorted(folder.rglob("*")):
            if f.is_file() and not IGNORED.search(f.relative_to(folder).as_posix()):
                zf.write(f, f.relative_to(folder).as_posix())
    try:
        check(dest)
    except ValueError:
        dest.unlink()
        raise
    return dest
