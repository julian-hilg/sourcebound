"""What is installed and configured on this machine, as data (`sb doctor --json`, the frontend).

Everything here is optional except Python and the data root: the report says what is there,
what is missing and what the missing part would be needed for.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

from . import __version__, config

_SIZES: dict[str, tuple[float, dict]] = {}

# (id, title, how it is found, what it is for, how to get it)
TOOLS = [
    ("git", "git", "Results record the commit of the code that produced them", "https://git-scm.com"),
    ("uv", "uv", "Installs Sourcebound and runs published bundles", "https://docs.astral.sh/uv/"),
    ("latexmk", "LaTeX (latexmk)", "Builds LaTeX deliverables as PDF; everything else works without", "TeX Live or MiKTeX"),
    ("latexpand", "latexpand", "`sb flatten`: one .tex file for a journal", "part of TeX Live"),
    ("pdftoppm", "poppler (pdftoppm)", "Shows PDF figures in the web view; text of papers without a converter", "poppler"),
    ("node", "Node.js", "Builds the web view (`sb ui --build`) and runs its agent bridge", "https://nodejs.org (22 or newer)"),
    ("claude", "Claude Code", "The agents that do the research", "https://claude.com/claude-code"),
]
# (module, extra or package, what it is for)
MODULES = [
    ("connectorx", "uv sync --extra sql", "Database sources by URI (SQL Server, Postgres)"),
    ("playwright", "uv sync --extra browser", "Pages that need a browser to render; slides and infographics as PNG"),
    ("jinja2", "a plugin that needs it installs it", "HTML templates (slides, infographics)"),
    ("docx", "a plugin that needs it installs it", "Word documents"),
]


def _version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
        return (r.stdout or r.stderr).strip().splitlines()[0][:80] if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _size(d: Path, *, ttl: float = 120.0) -> dict:
    """Files and bytes below a folder; cached, because the raw archive can be large."""
    hit = _SIZES.get(str(d))
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    files = size = 0
    for root, _dirs, names in os.walk(d) if d.is_dir() else []:
        for n in names:
            try:
                size += os.lstat(os.path.join(root, n)).st_size
                files += 1
            except OSError:
                continue
    out = {"path": str(d), "exists": d.is_dir(), "files": files, "bytes": size}
    _SIZES[str(d)] = (time.monotonic(), out)
    return out


def _zotero(url: str) -> dict:
    import httpx
    try:
        r = httpx.get(url.rstrip("/") + "/connector/ping", timeout=0.8)
        return {"running": r.status_code == 200}
    except Exception:                               # closed, or no network stack: both mean "not running"
        return {"running": False}


def report(*, sizes: bool = True) -> dict:
    from . import activity, assets, contracts, deliverable, jobs, plugins, sources
    h = config.hub()
    home = config.home()
    p = config.project(required=False)
    claude = Path.home() / ".claude"
    problems: list[dict] = []
    add = lambda level, text, fix="": problems.append({"level": level, "text": text, "fix": fix})

    tools = []
    for exe, title, purpose, get in TOOLS:
        path = shutil.which(exe)
        tools.append({"id": exe, "title": title, "installed": path is not None, "path": path or "",
                      "version": _version([path, "--version"]) if path else "", "purpose": purpose, "get": get})
    modules = [{"id": m, "installed": importlib.util.find_spec(m) is not None, "install": how, "purpose": why}
               for m, how, why in MODULES]
    packages = {}
    for name in ("duckdb", "polars", "pyarrow", "httpx", "matplotlib"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None

    for name, d in (("data root", h.lake_root), ("raw archive", h.raw_root)):
        if not d.is_dir():
            add("error", f"{name} {d} does not exist", "sb init")
        elif not os.access(d, os.W_OK):
            add("error", f"{name} {d} is not writable")
    if not (h.registry / "contracts").is_dir():
        add("warning", f"no registry at {h.registry}; using the examples in the checkout", "sb init")

    lake_info: dict = {"catalog": h.catalog, "data_path": h.data_path, "tables": 0, "snapshot": None}
    kind, _, where = h.catalog.partition(":")
    if h.lake_root.is_dir() and (kind not in {"sqlite", "duckdb"} or Path(where).exists()):
        try:
            from . import lake
            con = lake.connect(read_only=True, fresh=True)
            lake_info.update(tables=lake._run(con, "SELECT count(*) FROM duckdb_tables() WHERE database_name = 'lake'")[0][0],
                             snapshot=lake.snapshot_id(con))
            con.close()
        except Exception as e:                      # a broken catalog is a finding, not a crash
            lake_info["error"] = f"{type(e).__name__}: {e}"
            add("error", f"catalog: {e}")
    names: set[str] = set()
    for base in h.contract_bases:
        try:
            names |= {c.name for c in contracts.all_contracts(base)}
        except Exception as e:
            add("error", f"contract in {base / 'contracts'}: {e}")

    exe = shutil.which("sb")
    hooks = False
    try:
        doc = json.loads((claude / "settings.json").read_text(encoding="utf-8")) if (claude / "settings.json").exists() else {}
        hooks = any(x.get("command") == "sb hook" for groups in (doc.get("hooks") or {}).values() for g in groups for x in g.get("hooks", []))
    except (json.JSONDecodeError, OSError, AttributeError):
        pass
    setup = [
        {"id": "path", "title": "`sb` on PATH", "done": exe is not None, "detail": exe or "", "fix": "sb install path"},
        {"id": "skill", "title": "Lead playbook for Claude Code", "done": (claude / "skills" / "research-study").exists(), "detail": "", "fix": "sb install skill"},
        {"id": "agents", "title": "Subagents at user level", "done": bool(list((claude / "agents").glob("sb-*.md"))) if (claude / "agents").is_dir() else False,
         "detail": "needed for projects outside the checkout", "fix": "sb install agents"},
        {"id": "hooks", "title": "Agent activity hooks", "done": hooks, "detail": "the Agents panel of the web view", "fix": "sb install hooks"},
        {"id": "frontend", "title": "Web view built", "done": bool(home and (home / "frontend" / "dist" / "index.html").exists()),
         "detail": "optional", "fix": "sb ui --build"},
    ]
    reg = plugins.load()
    for pl in reg.plugins:
        if pl.error:
            add("warning", f"plugin {pl.name} did not load: {pl.error}")
    try:
        job_rows = jobs.listing()
    except Exception:
        job_rows = []
    return {
        "sourcebound": {"version": __version__, "python": platform.python_version(), "executable": sys.executable,
                        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
                        "checkout": str(home) if home else None, "packages": packages},
        "configuration": {"file": str(h.config_file), "from": h.source, "data_root": str(h.lake_root),
                          "data_root_from": h.lake_root_from, "registry": str(h.registry),
                          "projects_dir": str(h.projects_dir) if h.projects_dir else None,
                          "project": {"slug": p.slug, "root": str(p.root)} if p else None,
                          "user_agent": h.user_agent, "seconds_between_requests": h.min_interval, "jitter_seconds": h.jitter,
                          "respect_robots": h.respect_robots, "zotero_url": h.zotero_url, "converter": h.converter,
                          "latex_templates": [{"name": n, "folder": f} for n, f in h.latex_templates],
                          "github_owner": h.github_owner},
        "lake": lake_info,
        "storage": [{"id": k, **_size(d)} if sizes else {"id": k, "path": str(d), "exists": d.is_dir()}
                    for k, d in (("raw archive", h.raw_root), ("tables", Path(h.data_path) if "://" not in h.data_path else Path("/nonexistent")),
                                 ("paper store", h.library), ("registry", h.registry))],
        "registry": {"contracts": len(names), "datasources": len(sources.listing()), "designs": len(assets.designs()),
                     "templates": len(assets.templates()), "jobs": len(job_rows), "jobs_due": sum(1 for j in job_rows if j.get("due")),
                     "mcp_servers": len(list((h.registry / "mcp").glob("*.yaml"))) if (h.registry / "mcp").is_dir() else 0},
        "tools": tools,
        "latex": {**deliverable.tex_tools(), "ready": all(deliverable.tex_tools()[t] for t in ("latexmk", "pdflatex"))},
        "zotero": {"url": h.zotero_url, **_zotero(h.zotero_url)},
        "modules": modules,
        "plugins": plugins.listing(),
        "renderers": [{"kind": r.kind, "title": r.title, "plugin": r.plugin, "outputs": list(r.outputs)} for r in reg.renderers.values()],
        "setup": setup,
        "activity_log": str(activity.log_path()),
        "problems": problems,
    }
