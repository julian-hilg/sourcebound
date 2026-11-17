"""Custom and private data sources: register entry, archived documentation, files, databases.

    sb datasource add acme_api --name "Acme API" --url https://api.acme.example --auth-env ACME_TOKEN
    sb datasource docs acme_api openapi.json https://api.acme.example/docs   # kept for good
    sb ingest report.xlsx --source acme_reports                              # manual file -> raw archive

    from sourcebound import sources
    df, ref = sources.query("warehouse", "SELECT id, price FROM dbo.prices")  # extract -> raw archive

A source is onboarded from what it already offers: its API documentation, or the tool
descriptions of its MCP server (save the server's tool list to a JSON file).  That
documentation is stored unchanged next to the register entry in the data root
(`<registry>/datasources/<id>/docs/`), with date and sha256, so every project can read it and
a pipeline can still be understood after the provider changed or removed its documentation.

Secrets never enter a file: the register entry names an environment variable
(`auth: {env: ...}` for an API token, `connection_env:` for a database URI).  Extracts and
manual files go through the same immutable raw archive as fetched responses, so tables built
from them carry `raw_ref` and stay rebuildable.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import config
from .fetch import Fetcher, RawRef, read_raw

ACCESS = ["api", "download", "scrape", "licensed", "manual", "cooperation", "database"]
TYPES = {".csv": "text/csv", ".json": "application/json", ".xml": "application/xml", ".pdf": "application/pdf",
         ".html": "text/html", ".txt": "text/plain", ".md": "text/markdown", ".yaml": "application/yaml",
         ".yml": "application/yaml", ".parquet": "application/vnd.apache.parquet", ".zip": "application/zip",
         ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         ".xls": "application/vnd.ms-excel"}
ENTRY = """# Data source register entry (written by the data-scout agent, reviewed by a human).
id: {id}
name: {name}
url: {url}
publisher: ""
access: {access}                 # {choices}
auth: {auth}
{extra}terms: ""
license: ""                 # start with "restricted" or "proprietary" to keep its tables out of `sb publish`
robots: ""
rate_limit: ""
frequency: ""
history: ""
legal_notes: ""
cost: ""
status: candidate           # candidate | approved | active | paused | rejected
tables: []
contact: ""
checked: {today}
"""


def _check_id(source: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", source):
        raise ValueError("source id: lowercase letters, digits and _ (e.g. warehouse)")


def entry(source: str) -> dict:
    """The register entry of a source ({} when there is none)."""
    f = config.hub().datasource(source)
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f else {}


def add(source: str, *, name: str, url: str = "", access: str = "api", auth_env: str | None = None,
        connection_env: str | None = None, mcp: str | None = None, database: dict | None = None) -> Path:
    """Write the register entry `<registry>/datasources/<id>.yaml` (status: candidate).

    `database` describes a database connection field by field (see `databases`); it makes the
    source a database source."""
    from . import databases
    _check_id(source)
    if access not in ACCESS:
        raise ValueError(f"access: one of {', '.join(ACCESS)}")
    spec = databases.check(database) if database is not None else None
    access = "database" if spec else access
    h = config.hub()
    if h.datasource(source):
        raise FileExistsError(f"{h.datasource(source)} exists -- edit it instead")
    auth = ("\n  env: %s            # environment variable that holds the token (never the token itself)\n"
            "  header: Authorization\n  prefix: \"Bearer \"" % auth_env) if auth_env else "none"
    extra = ""
    if connection_env:
        extra += f"connection_env: {connection_env}   # environment variable with the database URI\n"
    if mcp:
        extra += f"mcp: {mcp}                 # MCP server of the provider (its tool list is archived under docs/)\n"
    if spec:
        extra += databases.block_text(spec)
    f = h.datasources_dir / f"{source}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(ENTRY.format(id=source, name=json.dumps(name), url=url or '""', access=access,
                              choices=" | ".join(ACCESS), auth=auth, extra=extra, today=date.today().isoformat()),
                 encoding="utf-8")
    return f


def docs_dir(source: str) -> Path:
    f = config.hub().datasource(source)
    if f is None:
        raise FileNotFoundError(f"no register entry for {source} (sb datasource add {source} --name ...)")
    return f.parent / source / "docs"


def docs(source: str) -> list[dict]:
    """Manifest of the archived documentation of a source, oldest first."""
    m = docs_dir(source) / "manifest.jsonl"
    return [json.loads(x) for x in m.read_text(encoding="utf-8").splitlines()] if m.exists() else []


def archive_docs(source: str, items: list[str]) -> list[dict]:
    """Store API documentation or an MCP tool list (files or URLs) unchanged, for good.

    URLs are fetched with the polite fetcher.  Content that is already archived is not stored
    twice; a changed document is added next to the older version, never over it.
    """
    d = docs_dir(source)
    d.mkdir(parents=True, exist_ok=True)
    known = {x["sha256"] for x in docs(source)}
    out = []
    for item in items:
        if re.match(r"https?://", item):
            resp, _ = Fetcher(source).get(item)
            body, origin = resp.content, item
            name = Path(item.split("?")[0].rstrip("/")).name or "index"
            if not Path(name).suffix:
                name += mimetypes.guess_extension(resp.headers.get("content-type", "").split(";")[0].strip()) or ".html"
        else:
            p = Path(item).expanduser()
            body, origin, name = p.read_bytes(), f"file:{p.name}", p.name      # no local paths in the archive
        sha = hashlib.sha256(body).hexdigest()
        if sha in known:
            out.append({"origin": origin, "sha256": sha, "file": None, "note": "already archived"})
            continue
        known.add(sha)
        fname = f"{date.today().isoformat()}_{sha[:8]}_{re.sub(r'[^A-Za-z0-9._-]', '_', name)}"
        (d / fname).write_bytes(body)
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "origin": origin,
                "sha256": sha, "file": fname, "bytes": len(body)}
        with (d / "manifest.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
        out.append(line)
    return out


def listing() -> list[dict]:
    """Every source in the registry (and the checkout's examples) with its documentation count."""
    h = config.hub()
    seen: dict[str, dict] = {}
    for base in (h.registry, h.root):
        for f in sorted((base / "datasources").glob("*.yaml")):
            if f.stem not in seen:
                e = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                m = f.parent / f.stem / "docs" / "manifest.jsonl"
                seen[f.stem] = {"id": f.stem, "name": e.get("name", ""), "access": e.get("access", ""),
                                "status": e.get("status", ""),
                                "docs": len(m.read_text(encoding="utf-8").splitlines()) if m.exists() else 0}
    return [seen[k] for k in sorted(seen)]


# ------------------------------------------------------------------ files and databases
def ingest(path: str | Path, source: str, *, note: str | None = None) -> RawRef:
    """A manual file (CSV, XLSX, PDF report, licensed download) into the raw archive."""
    _check_id(source)
    p = Path(path).expanduser()
    ctype = TYPES.get(p.suffix.lower(), "application/octet-stream")
    meta = {"file": p.name, **({"note": note} if note else {})}
    return Fetcher(source).store(p.read_bytes(), url=f"file:{p.name}", content_type=ctype, meta=meta)


def query(source: str, sql: str, *, connection=None):
    """Run `sql` against a database source; returns (polars DataFrame, RawRef).

    The extract is archived as Parquet in the raw archive with the query text in the manifest,
    so the table built from it can be rebuilt (`read_extract`) without the database.
    Without `connection` the source's register entry says how to connect: its `database:` block
    (driver, server, ...; the password from the variable `password_env` names, see `databases`),
    or an older `connection_env:` with a whole URI.  `connection` may be any DB-API or
    SQLAlchemy connection.
    """
    import polars as pl

    from . import databases
    _check_id(source)
    if connection is not None:
        df = pl.read_database(sql, connection)
    else:
        try:
            df = databases.read(source, sql)
        except ValueError as e:
            raise RuntimeError(f"datasource {source}: {e}") from e
    buf = io.BytesIO()
    df.write_parquet(buf)
    ref = Fetcher(source).store(buf.getvalue(), url=f"sql:{source}", content_type=TYPES[".parquet"],
                                meta={"query": sql, "rows": df.height})
    return df, ref


def read_extract(source: str, sha256: str):
    """An archived database extract as a DataFrame (for --reparse without the database)."""
    import polars as pl
    return pl.read_parquet(io.BytesIO(read_raw(source, sha256)))

