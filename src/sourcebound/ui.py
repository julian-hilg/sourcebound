"""Local web view (`sb ui`): the files of all projects as JSON, and the built frontend.

    GET  /api/health                         what is running, which configuration
    GET  /api/projects                       every project: phase, gates, counts, last activity
    GET  /api/projects/<id>                  one project: card, hypotheses, claims, results, reviews, log, notes
    GET  /api/projects/<id>/file?path=..     one text file of the project (research/, reviews/, log.md, ...)
    GET  /api/projects/<id>/raw?path=..      a figure or PDF (a PDF figure as PNG with &as=png)
    GET  /api/projects/<id>/handover         dist/handover: sections, results, tables, references
    POST /api/projects/<id>/run              {command: check | review-edits | handover}  -> runs `sb <command>`
    POST /api/projects/<id>/notes            {op: add | set | rm | put, ...}             -> what `sb note` does
    GET  /api/fetch                          fetch log and stopped hosts per source
    GET  /api/activity                       what the agents are doing (hook events)
    GET  /api/workspace                      a VS Code workspace of all projects;  POST writes it (`sb workspace`)
    GET  /api/system                         what is installed and configured (`sb doctor --json`)
    GET  /api/lake                           tables of the data lake with their contracts, and snapshots
    GET  /api/lake/table?name=s.t&limit=100  rows of one table
    POST /api/sql                            {target, query, limit}: one read-only statement (`sb sql`)
    GET  /api/connections                    data sources, SQL targets, registered MCP servers
    POST /api/connections                    {op: save | remove | restore | test | secret | forget, id, ...}  -> `sb datasource`
    GET  /api/jobs                           scheduled jobs and their log;  POST /api/jobs/run {id} runs one now
    GET  /api/assets                         designs, templates, plugins and the formats they render
    GET  /api/projects/<id>/pieces           pieces with text and renders
    POST /api/projects/<id>/pieces           {op: add | set | rm | restore | render | check, ...}  -> what `sb piece` / `sb render` do

There is no second source of truth: every answer is read from the project files at request
time, and the three things that write (`run`, `notes`, `workspace`) do what the command
line does.  The server listens on 127.0.0.1 only and refuses requests that name another
host or come from another site.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from . import __version__, activity, config, deliverable, ledger, notes, render, results
from .handover import _group, to_markdown

PHASES = ["brief", "landscape", "hypotheses", "data", "analysis", "review", "deliverables", "published"]
RUN = {"check": ["check"], "check-offline": ["check", "--offline"], "review-edits": ["review-edits"], "handover": ["handover"]}
TEXT = {".md", ".yaml", ".yml", ".json", ".csv", ".txt", ".py"}
TEXT_ROOTS = ("research/", "reviews/", "evidence/", "analysis/", "dist/handover/", "pieces/", "log.md", "README.md", "AGENTS.md",
              "hypotheses.yaml", "project.yaml")
TEXT = TEXT | {".html"}
RAW = {".png", ".svg", ".jpg", ".jpeg", ".pdf", ".docx", ".html"}
RAW_ROOTS = ("figures/", "deliverables/", "dist/handover/", "dist/render/", "pieces/")
LOCAL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
PORT = 5210


class NotFound(Exception):
    pass


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ projects
def project_roots() -> dict[str, Path]:
    """Every project the configuration knows: {id: folder}.

    The folders directly inside the hub, inside `[projects] dir`, and the project around the
    working directory.  The id is the slug; a second project with the same slug gets `slug~2`.
    """
    h = config.hub()
    parents = [h.config_file.parent] if h.source == "hub" and h.config_file else []
    if h.projects_dir:
        parents.append(h.projects_dir)
    found: list[Path] = []
    here = config.find_up("project.yaml")
    for d in ([here] if here else []) + [d for p in parents if p.is_dir() for d in sorted(p.iterdir())]:
        if d.is_dir() and not d.name.startswith(".") and (d / "project.yaml").exists() and d.resolve() not in found:
            found.append(d.resolve())
    out: dict[str, Path] = {}
    for d in found:
        try:
            slug = str((yaml.safe_load((d / "project.yaml").read_text(encoding="utf-8")) or {}).get("slug") or d.name)
        except (OSError, yaml.YAMLError):
            slug = d.name
        pid, n = slug, 1
        while pid in out:
            n += 1
            pid = f"{slug}~{n}"
        out[pid] = d
    return out


def _project(pid: str) -> config.Project:
    root = project_roots().get(pid)
    if root is None:
        raise NotFound(f"no project {pid}")
    return config.project(root)


def _count(items: list[dict], statuses) -> dict[str, int]:
    return {s: sum(1 for x in items if x.get("status") == s) for s in sorted(statuses)
            if any(x.get("status") == s for x in items)}


def _log(root: Path) -> list[dict]:
    f = root / "log.md"
    out = []
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []:
        m = re.match(r"^- (\d{4}-\d{2}-\d{2}) ([^:]{1,40}): (.*)$", ln)
        if m:
            out.append({"date": m.group(1), "who": m.group(2), "text": m.group(3)})
    return out


def _gates(p: config.Project, L: dict, log: list[dict]) -> list[dict]:
    """G1-G3 as far as the files show them: the log line that names a gate, else what the phase implies."""
    phase = p.meta.get("phase")
    at = PHASES.index(phase) if phase in PHASES else -1
    frozen = L["hdoc"].get("frozen") or {}

    def logged(gate: str) -> dict | None:
        return next((x for x in log if re.search(rf"\b{gate}\b", x["text"])), None)
    out = []
    for gate, title, passed, basis in (
            ("G1", "Brief approved", at >= 1, "the phase is past the brief"),
            ("G2", "Hypotheses approved and frozen", bool(frozen), f"frozen on {frozen.get('date')}" if frozen else ""),
            ("G3", "Published", at == len(PHASES) - 1, "the phase is published")):
        entry = logged(gate)
        out.append({"id": gate, "title": title, "passed": passed,
                    "basis": f"log {entry['date']}: {entry['text']}" if entry and passed else basis if passed else ""})
    return out


def _mtime(root: Path) -> float:
    files = [root / n for n in ("project.yaml", "hypotheses.yaml", "log.md", "evidence/claims.yaml", "results/results.json")]
    files += [*root.glob("reviews/*.md"), *root.glob("research/**/*.md"), *root.glob("deliverables/*/sections/*")]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


def summary(pid: str, root: Path) -> dict:
    """One row of the overview. A project that cannot be read is listed with the reason."""
    base = {"id": pid, "path": str(root)}
    try:
        p = config.project(root)
        L = ledger.load(p)
        log = _log(root)
        res = results.load(p)
        frozen = L["hdoc"].get("frozen") or {}
        from . import pieces as _pieces
        return {**base, "slug": p.slug, "title": p.title, "lang": p.lang, "phase": p.meta.get("phase"),
                "kind": p.meta.get("kind") or "study", "topic": p.meta.get("topic") or "",
                "pieces": {"total": len(_pieces.load(p)), "by_status": _count(_pieces.load(p), _pieces.STATUS)},
                "created": str(p.meta.get("created") or ""), "gates": _gates(p, L, log),
                "hypotheses": {"total": len(L["hypotheses"]), "by_status": _count(L["hypotheses"], ledger.H_STATUS),
                               "frozen": str(frozen.get("date") or "") or None},
                "claims": {"total": len(L["claims"]), "by_status": _count(L["claims"], ledger.C_STATUS)},
                "web_sources": len(L["sources"]), "results": len(res),
                "reviews": len([f for f in root.glob("reviews/*.md") if f.name != "README.md"]),
                "deliverables": [d.name for d in deliverable.folders(p, markdown=True)],
                "last_change": _iso(_mtime(root)) if _mtime(root) else None,
                "last_log": log[-1] if log else None}
    except Exception as e:                           # a broken project.yaml must not hide the others
        return {**base, "slug": pid, "title": pid, "error": f"{type(e).__name__}: {e}"}


def _documents(root: Path) -> list[dict]:
    groups = (("Research", ["research/brief.md", "research/landscape.md"]),
              ("Notes", sorted(f.relative_to(root).as_posix() for f in root.glob("research/notes/*.md"))),
              ("Reviews", sorted((f.relative_to(root).as_posix() for f in root.glob("reviews/*.md") if f.name != "README.md"),
                                 reverse=True)),
              ("Project", ["log.md", "README.md"]))
    return [{"path": rel, "group": g, "name": Path(rel).stem, "changed": _iso((root / rel).stat().st_mtime),
             "bytes": (root / rel).stat().st_size} for g, rels in groups for rel in rels if (root / rel).is_file()]


def _handover_state(p: config.Project) -> dict:
    f = p.root / "dist" / "handover" / "handover.json"
    if not f.exists():
        return {"built": False}
    newer = [x for x in [*p.root.glob("deliverables/*/sections/*"), p.root / "results" / "results.json"]
             if x.exists() and x.stat().st_mtime > f.stat().st_mtime]
    return {"built": True, "at": _iso(f.stat().st_mtime), "stale": bool(newer),
            "changed_since": sorted(x.relative_to(p.root).as_posix() for x in newer)[:12]}


def detail(pid: str) -> dict:
    p = _project(pid)
    L = ledger.load(p)
    frozen = L["hdoc"].get("frozen") or {}
    hashes = frozen.get("hashes") or {}
    hyps = []
    for h in L["hypotheses"]:
        now = ledger.fingerprint(h)
        was = hashes.get(h.get("id"))
        hyps.append({**h, "fingerprint": now, "registered": was,
                     "registration": "unchanged" if was == now else "changed" if was else "frozen without hash" if frozen else "not frozen"})
    errs, warns = results.problems(p)
    folders = []
    for d in deliverable.folders(p, markdown=True):
        pdfs = sorted(x.relative_to(p.root).as_posix() for x in [*d.glob("main.pdf"), *p.root.glob(f"deliverables/{d.name}.pdf")])
        spec = next((x for x in p.meta.get("deliverables") or [] if str(x.get("path", "")).startswith(f"deliverables/{d.name}/")), {})
        if spec.get("pdf") and (p.root / spec["pdf"]).exists():
            pdfs = [spec["pdf"], *[x for x in pdfs if x != spec["pdf"]]]
        folders.append({"name": d.name, "kind": spec.get("kind") or "", "format": "markdown" if deliverable.is_markdown(d) else "latex",
                        "sections": len([*d.glob("sections/*.tex"), *d.glob("sections/*.md")]), "pdf": pdfs[0] if pdfs else None})
    log = _log(p.root)
    return {**summary(pid, p.root), "card": json.loads(json.dumps(p.meta, default=str)),
            "frozen": json.loads(json.dumps(frozen, default=str)) or None,
            "amendments": json.loads(json.dumps(L["hdoc"].get("amendments") or [], default=str)),
            "hypothesis_list": json.loads(json.dumps(hyps, default=str)),
            "claim_list": json.loads(json.dumps(L["claims"], default=str)),
            "source_list": json.loads(json.dumps(L["sources"], default=str)),
            "result_list": [{"key": k, **{x: v.get(x) for x in ("value", "display", "unit", "ci", "hypothesis", "note")},
                             **{x: (v.get("provenance") or {}).get(x) for x in ("script", "git", "data", "at")}}
                            for k, v in sorted(results.load(p).items())],
            "result_problems": {"errors": errs, "warnings": warns},
            "documents": _documents(p.root), "log": log, "deliverable_folders": folders,
            "handover": _handover_state(p), "notes": notes.load(p)}


def _inside(p: config.Project, rel: str, roots: tuple, suffixes: set) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    f = (p.root / rel).resolve()
    if not f.is_relative_to(p.root.resolve()) or f.suffix.lower() not in suffixes or not rel.startswith(roots):
        raise NotFound(f"{rel} is not a file the web view serves")
    if not f.is_file():
        raise NotFound(f"{rel} does not exist")
    return f


def text_file(pid: str, rel: str) -> dict:
    p = _project(pid)
    f = _inside(p, rel, TEXT_ROOTS, TEXT)
    return {"path": f.relative_to(p.root.resolve()).as_posix(), "changed": _iso(f.stat().st_mtime),
            "text": f.read_text(encoding="utf-8", errors="replace")}


def raw_file(pid: str, rel: str, as_png: bool) -> tuple[bytes, str]:
    """A figure or PDF; a PDF as PNG where a converter is installed (browsers do not show PDF images)."""
    f = _inside(_project(pid), rel, RAW_ROOTS, RAW)
    if as_png and f.suffix.lower() == ".pdf":
        png = _png(f)
        if png is not None:
            return png.read_bytes(), "image/png"
    return f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream"


def pdf_as_png() -> bool:
    """A PDF figure can be shown as an image (else the page shows the PDF itself)."""
    return bool(shutil.which("pdftoppm") or shutil.which("sips"))


def _png(pdf: Path) -> Path | None:
    cache = Path(tempfile.gettempdir()) / "sourcebound-ui"
    cache.mkdir(exist_ok=True)
    out = cache / (hashlib.sha256(f"{pdf}|{pdf.stat().st_mtime_ns}".encode()).hexdigest()[:24] + ".png")
    if out.exists():
        return out
    if shutil.which("pdftoppm"):
        run = ["pdftoppm", "-png", "-r", "200", "-singlefile", str(pdf), str(out.with_suffix(""))]
    elif shutil.which("sips"):
        run = ["sips", "-s", "format", "png", str(pdf), "--out", str(out)]
    else:
        return None
    try:
        subprocess.run(run, capture_output=True, timeout=60, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    return out if out.exists() else None


# ------------------------------------------------------------------ deliverables (from the handover)
_bib = render.bib_fields


def handover(pid: str) -> dict:
    """What `sb handover` wrote, in one answer: the prose, and everything the prose refers to."""
    p = _project(pid)
    out = p.root / "dist" / "handover"
    if not (out / "handover.json").exists():
        return {"built": False}
    doc = json.loads((out / "handover.json").read_text(encoding="utf-8"))
    sections = {s["file"]: (out / s["file"]).read_text(encoding="utf-8")
                for d in doc["deliverables"] for s in d["sections"] if (out / s["file"]).exists()}
    tables = render._tables(out / "tables")
    res = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").exists() else {}
    bib = _bib((out / "references.bib").read_text(encoding="utf-8")) if (out / "references.bib").exists() else {}
    web = {s["id"]: {k: s.get(k) for k in ("title", "url", "publisher", "accessed", "date", "author")}
           for s in json.loads(json.dumps(ledger.load(p)["sources"], default=str)) if s.get("id")}
    try:
        edited = sorted(k for k, v in deliverable.review(p)["files"].items() if not v.get("deleted"))
    except Exception:                                # not a git repository, or git is missing
        edited = None
    return {"built": True, **_handover_state(p), "handover": doc, "sections": sections, "results": res,
            "tables": tables, "references": bib, "web_sources": web, "edited_by_person": edited,
            "figures": sorted(f.name for f in (out / "figures").glob("*")) if (out / "figures").is_dir() else [],
            "pdf_as_png": pdf_as_png()}


# ------------------------------------------------------------------ actions (what the command line does)
def run(pid: str, command: str) -> dict:
    if command not in RUN:
        raise ValueError(f"the web view runs only: {', '.join(RUN)}")
    p = _project(pid)
    r = subprocess.run([sys.executable, "-m", "sourcebound.cli", *RUN[command]], cwd=p.root, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900)
    return {"command": "sb " + " ".join(RUN[command]), "project": pid, "exit_code": r.returncode,
            "output": (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip(),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def note(pid: str, body: dict) -> dict:
    p = _project(pid)
    op = body.get("op")
    fields = {k: body[k] for k in notes.FIELDS if k in body}
    if op == "add":
        return {"note": notes.add(p, **fields)}
    if op == "set":
        before, after = notes.update(str(body.get("id")), p, **fields)
        return {"before": before, "note": after}
    if op == "rm":
        return {"removed": notes.remove(str(body.get("id")), p)}
    if op == "put":
        return {"note": notes.put(dict(body.get("note") or {}), p)}
    raise ValueError("op must be add, set, rm or put")


# ------------------------------------------------------------------ pieces, the lake, connections, jobs
def pieces_of(pid: str) -> dict:
    from . import assets, pieces
    p = _project(pid)
    return {"project": pid, "statuses": pieces.STATUS, "defaults": p.meta.get("piece_defaults") or {},
            "pieces": pieces.summary(p),
            "templates": [t for t in assets.templates() if not t["for"] or "piece" in t["for"]]}


def piece(pid: str, body: dict) -> dict:
    from . import pieces
    p = _project(pid)
    op, piece_id = body.get("op"), str(body.get("id") or "")
    fields = {k: body[k] for k in pieces.FIELDS if k in body}
    if op == "add":
        return {"piece": pieces.add(p, piece_id=piece_id or None, text=body.get("text"), **fields)}
    if op == "set":
        before, after = pieces.update(piece_id, p, text=body.get("text"), **fields)
        return {"before": before, "piece": after}
    if op == "rm":
        return {"removed": pieces.remove(piece_id, p)}
    if op == "restore":
        return {"piece": pieces.restore(piece_id, p)}
    if op == "check":
        errs, warns = pieces.check(piece_id, p)
        return {"id": piece_id, "errors": errs, "warnings": warns}
    if op == "render":
        try:
            return {"render": render.render(piece_id, str(body.get("template") or ""), design_id=body.get("design") or None, project=p)}
        except (RuntimeError, FileNotFoundError) as e:
            raise ValueError(str(e))
    raise ValueError("op must be add, set, rm, restore, check or render")


def lake_overview() -> dict:
    from . import contracts, lake
    h = config.hub()
    kind, _, where = h.catalog.partition(":")
    if kind in {"sqlite", "duckdb"} and not Path(where).exists():      # nothing was ever written: an empty lake, not an error
        return {"catalog": h.catalog, "data_path": h.data_path, "tables": [], "snapshots": []}
    con = lake.connect(read_only=True, fresh=True)
    try:
        tabs = lake._run(con, """SELECT schema_name, table_name, estimated_size, comment FROM duckdb_tables()
                                 WHERE database_name = 'lake' ORDER BY 1, 2""")
        cols = lake._run(con, """SELECT schema_name, table_name, column_name, data_type FROM duckdb_columns()
                                 WHERE database_name = 'lake' ORDER BY 1, 2, column_index""")
        snaps = lake._run(con, """SELECT snapshot_id, snapshot_time::VARCHAR, changes::VARCHAR, author, commit_message
                                  FROM lake.snapshots() ORDER BY snapshot_id DESC LIMIT 40""")
    finally:
        con.close()
    out = []
    for schema, table, rows, comment in tabs:
        name = f"{schema}.{table}"
        try:
            c = contracts.find(name, hub_root=h.root, registry=h.registry)
        except Exception:
            c = None
        spec = c.columns if c else {}
        out.append({"name": name, "schema": schema, "table": table, "rows": rows, "comment": comment or "",
                    "contract": {"title": c.title, "description": c.description, "grain": c.grain, "primary_key": c.primary_key,
                                 "license": c.license, "sources": c.sources, "pipeline": c.pipeline, "owner": c.owner} if c else None,
                    "restricted": bool(c and c.license.lower().startswith(("restricted", "proprietary"))),
                    "columns": [{"name": cn, "type": ct, "description": (spec.get(cn) or {}).get("description", ""),
                                 "unit": (spec.get(cn) or {}).get("unit", "")} for s2, t2, cn, ct in cols if (s2, t2) == (schema, table)]})
    return {"catalog": h.catalog, "data_path": h.data_path, "tables": out,
            "snapshots": [{"id": i, "at": str(t), "changes": ch or "", "author": a or "", "message": m or ""}
                          for i, t, ch, a, m in snaps]}


def lake_table(name: str, limit: int) -> dict:
    from . import connections, lake
    lake._check_name(name)
    if not re.fullmatch(r"[A-Za-z_][\w]*\.[A-Za-z_][\w]*", name):
        raise ValueError(f"not a table name: {name}")
    return connections.sql("lake", f"SELECT * FROM lake.{name}", limit=limit)


def connections_overview() -> dict:
    from . import connections
    return {"sources": connections.status(), "sql_targets": connections.targets(), "mcp_servers": connections.mcp_list(),
            "seconds_between_requests": config.hub().min_interval}


def connection(body: dict) -> dict:
    """What `sb datasource add|set|test|rm` do for a database source, for the Connections panel.

    {op: save, id, name?, spec, password?}   create or change; answers {path, created, before} (before: for undo)
    {op: remove, id}                         answers {path, before}
    {op: restore, id, text}                  the undo of save and remove
    {op: test, id}                           connect and ask for the version
    {op: secret, id, password}               hold a password for this session, in memory only
    {op: forget, id}                         drop it
    A password is never written and never returned. The page sends it with `secret` (not through
    a command, whose input the app's history records), then runs the test.
    """
    from . import databases
    op, sid = body.get("op"), str(body.get("id") or "")
    if op == "save":
        return databases.save(sid, name=body.get("name"), spec=body.get("spec") or {})
    if op == "secret":
        if not str(body.get("password") or ""):
            raise ValueError("no password")
        databases.remember(sid, str(body["password"]))
        return {"id": sid, "password_in_session": True}
    if op == "remove":
        return databases.remove(sid)
    if op == "restore":
        return databases.restore(sid, str(body.get("text") or ""))
    if op == "test":
        return databases.test(sid)
    if op == "forget":
        databases.forget(sid)
        return {"id": sid, "forgotten": True}
    raise ValueError("op: save, remove, restore, test, secret or forget")


def jobs_overview() -> dict:
    from . import jobs
    return {"jobs": jobs.listing(), "log": jobs.log(60), "schedule_hint": jobs.schedule_hint()}


def assets_overview() -> dict:
    from . import assets, plugins
    reg = plugins.load()
    return {"designs": assets.designs(), "templates": assets.templates(), "plugins": plugins.listing(),
            "renderers": [{"kind": r.kind, "title": r.title, "plugin": r.plugin, "outputs": list(r.outputs)} for r in reg.renderers.values()],
            "registry": str(config.hub().registry)}


# ------------------------------------------------------------------ fetch log, activity, VS Code
def fetch_log(limit: int = 200) -> dict:
    h = config.hub()
    sources = []
    for d in sorted(h.raw_root.iterdir()) if h.raw_root.is_dir() else []:
        m = d / "manifest.jsonl"
        if not d.is_dir() or not (m.exists() or any(d.glob("BLOCKED*"))):
            continue
        rows = []
        for ln in m.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:] if m.exists() else []:
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        stopped = [{"host": f.name.removeprefix("BLOCKED.").removeprefix("BLOCKED") or "(all hosts)",
                    "reason": f.read_text(encoding="utf-8", errors="replace").strip(), "since": _iso(f.stat().st_mtime)}
                   for f in sorted(d.glob("BLOCKED*"))]
        total = sum(1 for _ in m.open(encoding="utf-8", errors="replace")) if m.exists() else 0
        sources.append({"source": d.name, "requests": total, "stopped": stopped, "entries": rows[::-1]})
    return {"raw_root": str(h.raw_root), "min_interval_s": h.min_interval, "sources": sources}


def workspace() -> dict:
    """A VS Code workspace: every project, the data root, the checkout, and the usual `sb` steps as tasks."""
    h = config.hub()
    folders = [{"name": pid, "path": str(root)} for pid, root in project_roots().items()]
    home = config.home()
    if home is not None and all(Path(f["path"]) != home for f in folders):
        folders.append({"name": "sourcebound", "path": str(home)})
    folders.append({"name": "data root", "path": str(h.lake_root)})
    task = lambda label, cmd: {"label": label, "type": "shell", "command": cmd,
                               "options": {"cwd": "${fileWorkspaceFolder}"}, "problemMatcher": []}
    return {"folders": folders,
            "settings": {"files.exclude": {"**/__pycache__": True, "**/.venv": True}},
            "tasks": {"version": "2.0.0", "tasks": [
                task("sb status", "sb status"), task("sb check", "sb check"),
                task("sb run analysis", "sb run analysis"), task("sb build", "sb build"),
                task("sb handover", "sb handover"), task("sb ui", "sb ui")]}}


def workspace_path() -> Path:
    h = config.hub()
    base = h.projects_dir or (h.config_file.parent if h.source == "hub" and h.config_file else Path.cwd())
    return base / "research.code-workspace"


def write_workspace(path: str | Path | None = None) -> Path:
    f = Path(path).expanduser().resolve() if path else workspace_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(f, json.dumps(workspace(), indent=2) + "\n")
    return f


def health() -> dict:
    h = config.hub()
    return {"name": "sourcebound-ui", "version": __version__, "config": str(h.config_file), "data_root": str(h.lake_root),
            "projects_dir": str(h.projects_dir) if h.projects_dir else None, "activity_log": str(activity.log_path()),
            "frontend_built": (dist_dir() or Path()).joinpath("index.html").exists()}


# ------------------------------------------------------------------ HTTP
def dist_dir() -> Path | None:
    home = config.home()
    return home / "frontend" / "dist" if home else None


class Handler(BaseHTTPRequestHandler):
    server_version = "sourcebound-ui"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):                    # quiet: this runs next to an agent session
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True             # the browser went away (a reload, a closed tab): nothing to answer

    def _json(self, value, code: int = 200) -> None:
        self._send(code, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _local(self) -> bool:
        """Only this machine's browser: the Host header names this server, the Origin (if any) is local."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        origin = self.headers.get("Origin")
        return host in {"127.0.0.1", "localhost", "[::1]"} and (origin is None or bool(LOCAL.match(origin)))

    def _route(self, method: str) -> None:
        if not self._local():
            return self._json({"error": "this server answers local requests only"}, 403)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [unquote(x) for x in url.path.strip("/").split("/")]
        try:
            if parts[0] != "api":
                return self._static(url.path) if method == "GET" else self._json({"error": "not found"}, 404)
            body = {}
            if method == "POST":
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._json({"error": "send JSON"}, 415)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            match (method, *parts[1:]):
                case ("GET", "health"):
                    self._json(health())
                case ("GET", "projects"):
                    self._json({"projects": [summary(pid, root) for pid, root in project_roots().items()]})
                case ("GET", "projects", pid):
                    self._json(detail(pid))
                case ("GET", "projects", pid, "file"):
                    self._json(text_file(pid, q.get("path", "")))
                case ("GET", "projects", pid, "raw"):
                    data, ctype = raw_file(pid, q.get("path", ""), q.get("as") == "png")
                    self._send(200, data, ctype)
                case ("GET", "projects", pid, "handover"):
                    self._json(handover(pid))
                case ("POST", "projects", pid, "run"):
                    self._json(run(pid, str(body.get("command"))))
                case ("POST", "projects", pid, "notes"):
                    self._json(note(pid, body))
                case ("GET", "projects", pid, "pieces"):
                    self._json(pieces_of(pid))
                case ("POST", "projects", pid, "pieces"):
                    self._json(piece(pid, body))
                case ("GET", "system"):
                    from . import system
                    self._json(system.report())
                case ("GET", "lake"):
                    self._json(lake_overview())
                case ("GET", "lake", "table"):
                    self._json(lake_table(q.get("name", ""), int(q.get("limit", 100))))
                case ("POST", "sql"):
                    from . import connections
                    self._json(connections.sql(str(body.get("target") or "lake"), str(body.get("query") or ""), limit=int(body.get("limit") or 500)))
                case ("GET", "connections"):
                    self._json(connections_overview())
                case ("POST", "connections"):
                    self._json(connection(body))
                case ("GET", "jobs"):
                    self._json(jobs_overview())
                case ("POST", "jobs", "run"):
                    from . import jobs
                    self._json(jobs.run(str(body.get("id"))))
                case ("GET", "assets"):
                    self._json(assets_overview())
                case ("GET", "fetch"):
                    self._json(fetch_log())
                case ("GET", "activity"):
                    self._json({"log": str(activity.log_path()), "events": activity.tail(int(q.get("limit", 300)))})
                case ("GET", "workspace"):
                    self._json({"path": str(workspace_path()), "workspace": workspace()})
                case ("POST", "workspace"):
                    self._json({"path": str(write_workspace(body.get("path") or None))})
                case _:
                    self._json({"error": "not found"}, 404)
        except NotFound as e:
            self._json({"error": str(e)}, 404)
        except PermissionError as e:                  # a rule refused it (an entry with extracts stays)
            self._json({"error": str(e)}, 409)
        except ValueError as e:
            fields = getattr(e, "errors", None)       # databases.SpecError: one message per field, for the form
            self._json({"error": str(e).strip("'\""), **({"fields": fields} if fields else {})}, 400)
        except (KeyError, FileExistsError, FileNotFoundError) as e:
            self._json({"error": str(e).strip("'\"")}, 400)
        except RuntimeError as e:                    # a database refused, a tool is missing: the person can act on the message
            self._json({"error": str(e)}, 422)
        except subprocess.TimeoutExpired:
            self._json({"error": "the command did not finish within 15 minutes"}, 504)
        except Exception as e:                       # the next request must still be answered
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _static(self, path: str) -> None:
        dist = dist_dir()
        if dist is None or not (dist / "index.html").exists():
            return self._send(200, NOT_BUILT.encode("utf-8"), "text/html; charset=utf-8")
        f = (dist / path.lstrip("/")).resolve()
        if not f.is_relative_to(dist.resolve()) or not f.is_file():
            f = dist / "index.html"
        self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                   cache=f.parent.name == "assets")

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Sourcebound</title>
<body style="font: 15px/1.5 system-ui; max-width: 40em; margin: 4em auto">
<h1>The frontend is not built yet</h1>
<p>The data service is running (<a href="/api/health">/api/health</a>). To build the web view once,
run in the <code>frontend</code> folder of the Sourcebound checkout (needs Node.js 22 or newer):</p>
<pre>npm install
npm run build</pre>
<p>Then reload this page. While working on the frontend itself, use <code>npm run dev</code> there instead.</p>
"""


BRIDGE_SCRIPT = "node_modules/@werkbank/bridge/src/server.js"


def _drive_path(path: Path) -> str:
    """A UNC path (\\\\server\\share\\...) as the mapped drive that reaches it (Z:\\...); WSL knows only drives."""
    p = str(path)
    if p.startswith("\\\\"):
        import os
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                unc = os.path.realpath(root).rstrip("\\")
                if unc.startswith("\\\\") and (p.lower() + "\\").startswith(unc.lower() + "\\"):
                    return root + p[len(unc):].lstrip("\\")
    return p


def _node_tool(tool: str, cwd: Path) -> list[str] | None:
    """How to run `node` or `npm` (or any command) in `cwd`: the one on the PATH, else (Windows) inside WSL.

    In WSL the command runs in an interactive shell so that version managers (nvm, fnm) and the
    user's own setup apply. The folder is changed inside that shell: if WSL cannot reach it,
    the command fails instead of running somewhere else."""
    found = shutil.which(tool)
    if found:
        return [found]
    if sys.platform == "win32" and shutil.which("wsl.exe"):
        return ["wsl.exe", "--exec", "bash", "-ic", f'cd "$(wslpath -u "$1")" && shift && {tool} "$@"', "bash", _drive_path(cwd)]
    return None


def _in_wsl(cmd: list[str]) -> bool:
    return Path(cmd[0]).name.lower() == "wsl.exe"


def _cwd(cmd: list[str], folder: Path) -> Path:
    """Where to start a tool: the folder itself, or for WSL a neutral one (it enters the folder from its
    argument, and complains about a working folder on a network share it cannot translate)."""
    import os
    return Path(os.environ.get("SystemRoot", "C:\\Windows")) if _in_wsl(cmd) else folder


def _bridge() -> subprocess.Popen | None:
    """The Werkbank agent bridge, if the frontend's packages are installed (agents drive the app through it)."""
    home = config.home()
    if home is None or not (home / "frontend" / "package.json").exists():
        return None
    front = home / "frontend"
    node = _node_tool("node", front)
    if node is None:
        return None
    if _in_wsl(node):
        # node_modules may live on the Linux side only (invisible from Windows): ask WSL whether it is there
        probe = node[:4] + [f'cd "$(wslpath -u "$1")" && test -f {BRIDGE_SCRIPT}', "bash", node[-1]]
        if subprocess.run(probe, cwd=_cwd(probe, front), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            return None
    elif not (front / BRIDGE_SCRIPT).exists():
        return None
    return subprocess.Popen(node + [BRIDGE_SCRIPT, "--hub"], cwd=_cwd(node, front),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_frontend() -> None:
    """Install the frontend's packages (first time) and build it: what `sb ui --build` does."""
    home = config.home()
    if home is None or not (home / "frontend" / "package.json").exists():
        raise RuntimeError("the frontend is part of the Sourcebound checkout (folder frontend/); this installation has none")
    front = home / "frontend"
    npm = _node_tool("npm", front)
    if npm is None:
        raise RuntimeError("building the frontend needs Node.js 22 or newer (npm was not found)")
    if _in_wsl(npm):
        print("npm is not on the PATH; using the one in WSL", flush=True)
    installed = (front / "node_modules").exists() and any((front / "node_modules").iterdir())
    for step in (None if installed else ["install"], ["run", "build"]):
        if step and subprocess.run(npm + step, cwd=_cwd(npm, front)).returncode:
            raise RuntimeError(f"`npm {' '.join(step)}` failed in {front}")


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port silently, and requests then
    # go to either one; there the port is taken exclusively, so a second start fails and says so.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def server_bind(self):
        import socket
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def running(port: int = PORT) -> dict | None:
    """The health answer of a Sourcebound web view already listening on this port, else None."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body if body.get("name") == "sourcebound-ui" else None
    except (OSError, ValueError):
        return None


def serve(port: int = PORT, *, open_browser: bool = True, bridge: bool = True) -> None:
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("font/woff2", ".woff2")
    url = f"http://127.0.0.1:{port}"
    if running(port):                                # a second start (the desktop icon twice): use the first
        print(f"Sourcebound web view is already running: {url}", flush=True)
        if open_browser:
            import webbrowser
            webbrowser.open(url)
        return
    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError as e:
        raise SystemExit(f"sb ui: port {port} is in use by another program ({e.strerror or e}); try --port") from None
    child = _bridge() if bridge else None
    print(f"Sourcebound web view: {url}  (data root {config.hub().lake_root}; Ctrl+C stops it)")
    print("agent bridge: " + ("started on 127.0.0.1:8787" if child else "not started" + ("" if not bridge else
          " (needs Node.js and `npm install` in the frontend folder; the web view works without it)")), flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if child:
            child.terminate()
        server.server_close()
