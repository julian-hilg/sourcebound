"""Connections: read-only SQL, and the MCP servers agents may use.

Read-only SQL
    sb sql lake "SELECT ..."           the data lake
    sb sql SOURCE "SELECT ..."         a registered database source (its URI comes from the
                                       environment variable its register entry names)
  One statement that reads: SELECT, WITH, SHOW, DESCRIBE or EXPLAIN.  This is a look at the
  data, not a load: nothing is archived and no lineage is recorded.  A table built from a
  database goes through `sourcebound.sources.query` in a pipeline.

MCP servers
    <registry>/mcp/<name>.yaml         name, transport, url or command, the environment
                                       variables it needs (names only, never values)
    sb mcp add NAME --url URL | --command "..."     register one
    sb mcp link [NAME ...]             write them into the project's .mcp.json for Claude Code
  The register is shared by all projects on the machine; a project links the servers it needs.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
from datetime import date
from pathlib import Path

import yaml

from . import config, sources

READS = ("select", "with", "show", "describe", "desc", "explain", "summarize", "from")
WRITES = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|call|exec|execute|merge|"
                    r"truncate|grant|revoke|install|load|export|import|set|use|vacuum|checkpoint|into)\b", re.I)
MAX_ROWS = 5000


def read_only(query: str) -> str:
    """The statement if it only reads; ValueError with the reason otherwise."""
    q = query.strip().rstrip(";").strip()
    bare = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", " ", q, flags=re.S)
    if not q:
        raise ValueError("no statement")
    if ";" in bare:
        raise ValueError("one statement only")
    first = (re.match(r"\s*\(*\s*([a-zA-Z]+)", bare) or [None, ""])[1].lower()
    if first not in READS:
        raise ValueError(f"only statements that read are run here (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN), not {first.upper() or 'this'}")
    hit = WRITES.search(bare)
    if hit:
        raise ValueError(f"only statements that read are run here: `{hit.group(1).upper()}` is not allowed")
    return q


def targets() -> list[dict]:
    """What `sql` can be run against: the lake, and every source with a database connection."""
    from . import databases
    out = [{"id": "lake", "title": "Data lake", "ready": True, "hint": "tables as <schema>.<table>"}]
    for s in sources.listing():
        e = sources.entry(s["id"])
        if isinstance(e.get("database"), dict) or e.get("connection_env"):
            ok, hint = databases.ready(s["id"])
            test = databases.last_test(s["id"])
            out.append({"id": s["id"], "title": e.get("name") or s["id"], "ready": ok, "hint": hint,
                        "tested": test["status"] if test else None})
    return out


def sql(target: str, query: str, *, limit: int = 500) -> dict:
    """Run one reading statement; returns {columns, types, rows, truncated, seconds}."""
    import polars as pl
    q = read_only(query)
    limit = max(1, min(int(limit), MAX_ROWS))
    start = time.monotonic()
    if target == "lake":
        from . import lake
        con = lake.connect(read_only=True, fresh=True)
        try:
            df = con.sql(q).pl() if not re.match(r"\s*(show|describe|desc|explain|summarize)\b", q, re.I) else con.execute(q).pl()
        finally:
            con.close()
    else:
        from . import databases
        df = databases.read(target, q)
    total = df.height
    df = df.head(limit)
    rows = [[v if isinstance(v, (int, float, bool, str)) or v is None else str(v) for v in r] for r in df.rows()]
    return {"target": target, "columns": df.columns, "types": [str(t) for t in df.dtypes], "rows": rows,
            "row_count": total, "truncated": total > limit, "seconds": round(time.monotonic() - start, 3)}


def status() -> list[dict]:
    """Every registered source with what it needs and whether that is in place."""
    from .fetch import blocked
    h, out = config.hub(), []
    for s in sources.listing():
        e = sources.entry(s["id"])
        auth = e.get("auth") if isinstance(e.get("auth"), dict) else {}
        envs = [x for x in (auth.get("env"), e.get("connection_env")) if x]
        m = h.raw_root / s["id"] / "manifest.jsonl"
        last = None
        if m.exists():
            with m.open("rb") as fh:
                fh.seek(max(0, m.stat().st_size - 2000))
                tail = fh.read().decode("utf-8", errors="replace").splitlines()
            try:
                last = json.loads(tail[-1]) if tail else None
            except json.JSONDecodeError:
                last = None
        try:
            stops = blocked(s["id"])
        except OSError:
            stops = {}
        db = None
        if isinstance(e.get("database"), dict):
            from . import databases
            try:
                spec, problem = databases.check(e["database"]), None
            except databases.SpecError as err:
                spec, problem = None, err.errors
            ok, why = databases.ready(s["id"])
            db = {"spec": spec or e["database"], "problems": problem, "where": databases.describe(s["id"], spec),
                  "needs_password": bool(spec and databases.needs_password(spec)),
                  "password_in_session": databases.has_session_secret(s["id"]), "ready": ok, "why": why,
                  "last_test": databases.last_test(s["id"])}
            if spec and spec.get("password_env"):
                envs.append(spec["password_env"])
        out.append({**s, "url": e.get("url", ""), "publisher": e.get("publisher", ""), "license": e.get("license", ""),
                    "connection": db,
                    "terms": e.get("terms", ""), "tables": e.get("tables") or [], "mcp": e.get("mcp", ""),
                    "frequency": e.get("frequency", ""), "checked": str(e.get("checked") or ""),
                    "needs_env": [{"name": x, "set": bool(os.environ.get(x))} for x in envs],
                    "database": bool(e.get("connection_env")) or db is not None,
                    "last_request": {"ts": last.get("ts"), "status": last.get("status")} if last else None,
                    "stopped_hosts": sorted(stops)})
    return out


# ------------------------------------------------------------------ MCP servers
def _mcp_dir() -> Path:
    return config.hub().registry / "mcp"


def mcp_add(name: str, *, url: str | None = None, command: str | None = None, env: list[str] | None = None,
            note: str = "", source: str = "") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError("server name: lowercase letters, digits, - and _")
    if bool(url) == bool(command):
        raise ValueError("give either --url (an HTTP server) or --command (a program that speaks MCP on stdio)")
    for v in env or []:
        if "=" in v:
            raise ValueError(f"--env takes the NAME of a variable, never its value ({v.split('=')[0]}=...)")
    f = _mcp_dir() / f"{name}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    parts = ([x.strip('"') for x in shlex.split(command, posix=False)] if os.name == "nt" else shlex.split(command)) if command else []
    doc = {"name": name, "transport": "http" if url else "stdio", **({"url": url} if url else {"command": parts[0], "args": parts[1:]}),
           "env": list(env or []), "note": note, "source": source, "added": date.today().isoformat()}
    f.write_text("# An MCP server agents may use (`sb mcp`). Secrets stay in environment variables.\n"
                 + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return f


def mcp_list() -> list[dict]:
    out = []
    for f in sorted(_mcp_dir().glob("*.yaml")) if _mcp_dir().is_dir() else []:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        out.append({**d, "name": d.get("name") or f.stem,
                    "env": [{"name": x, "set": bool(os.environ.get(x))} for x in d.get("env") or []]})
    return out


def mcp_remove(name: str) -> None:
    f = _mcp_dir() / f"{name}.yaml"
    if not f.exists():
        raise KeyError(f"no MCP server {name}")
    f.unlink()


def mcp_link(names: list[str] | None = None, folder: Path | None = None) -> tuple[Path, list[str]]:
    """Write registered servers into `.mcp.json` of a project (other entries there are kept)."""
    folder = folder or (config.find_up("project.yaml") or Path.cwd())
    servers = {s["name"]: s for s in mcp_list()}
    wanted = names or sorted(servers)
    missing = [n for n in wanted if n not in servers]
    if missing:
        raise KeyError(f"not registered: {', '.join(missing)} (sb mcp list)")
    f = folder / ".mcp.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    block = doc.setdefault("mcpServers", {})
    for n in wanted:
        s = servers[n]
        env = {e["name"]: "${%s}" % e["name"] for e in s["env"]}       # Claude Code expands these from the environment
        block[n] = ({"type": "http", "url": s["url"]} if s["transport"] == "http"
                    else {"command": s["command"], "args": s.get("args") or [], **({"env": env} if env else {})})
    config.write_atomic(f, json.dumps(doc, indent=2) + "\n")
    return f, wanted
