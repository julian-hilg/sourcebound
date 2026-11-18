"""Database connections of data sources: described field by field, tested, read only.

A database source has a `database:` block in its register entry (`<registry>/datasources/<id>.yaml`):

    database:
      driver: mssql                # mssql | postgresql | mysql | sqlite | duckdb
      server: sql-01.example.org   # client-server drivers
      port: 1433
      database: Research
      auth: windows                # sql (user and password) | windows (SQL Server only) | none
      user: ""
      password_env: ""             # environment variable with the password (for pipelines and jobs)
      encrypt: true                # SQL Server
      trust_server_certificate: false
      ssl_mode: prefer             # PostgreSQL: disable | prefer | require | verify-full
      timeout: 15                  # seconds to wait for an answer when testing
      path: ""                     # sqlite and duckdb: the database file

The password never enters a file.  It comes from the session (typed once into the web view and
held in the memory of `sb ui`, gone when it stops) or from the environment variable that
`password_env` names.  An older entry with `connection_env:` (a whole URI in an environment
variable) keeps working.

Everything here reads: `read` runs one statement that `connections.read_only` accepts, a file
database is opened read-only, and a test asks the server for its version.  SQL Server,
PostgreSQL and MySQL are read through connectorx (`uv sync --extra sql`); SQLite and DuckDB
files need nothing extra.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml

from . import config

DRIVERS = {
    "mssql": {"title": "SQL Server", "port": 1433, "auth": ("sql", "windows"), "version": "SELECT @@VERSION AS version"},
    "postgresql": {"title": "PostgreSQL", "port": 5432, "auth": ("sql", "none"), "version": "SELECT version() AS version"},
    "mysql": {"title": "MySQL / MariaDB", "port": 3306, "auth": ("sql", "none"), "version": "SELECT VERSION() AS version"},
    "sqlite": {"title": "SQLite file", "file": True, "version": "SELECT sqlite_version() AS version"},
    "duckdb": {"title": "DuckDB file", "file": True, "version": "SELECT version() AS version"},
}
SSL_MODES = ("disable", "prefer", "require", "verify-full")
FIELDS = ("driver", "server", "port", "database", "auth", "user", "password_env", "encrypt",
          "trust_server_certificate", "ssl_mode", "timeout", "path")
HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")
ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_SESSION: dict[str, str] = {}                        # source -> password, this process only
_TESTS: dict[str, dict] = {}                         # source -> last test, this process only
_LOCK = threading.Lock()


class SpecError(ValueError):
    """A connection description with problems, one message per field."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _bool(v, default: bool) -> bool:
    if v is None or v == "":
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def check(spec: dict) -> dict:
    """The connection description, normalised, or SpecError naming each field that is wrong."""
    errors: dict[str, str] = {}
    driver = str(spec.get("driver") or "").strip()
    if driver not in DRIVERS:
        raise SpecError({"driver": f"one of {', '.join(DRIVERS)}"})
    d = DRIVERS[driver]
    out: dict = {"driver": driver}
    if d.get("file"):
        path = str(spec.get("path") or "").strip()
        if not path:
            errors["path"] = "the database file"
        out["path"] = path
    else:
        server = str(spec.get("server") or "").strip()
        if not server:
            errors["server"] = "the server's host name"
        elif not HOST.match(server):
            errors["server"] = "a host name or address (an instance is reached through its port: host and port)"
        try:
            port = int(spec.get("port") or d["port"])
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            errors["port"] = "a number from 1 to 65535"
            port = d["port"]
        database = str(spec.get("database") or "").strip()
        if not database:
            errors["database"] = "the database name"
        auth = str(spec.get("auth") or d["auth"][0]).strip()
        if auth not in d["auth"]:
            errors["auth"] = f"for {d['title']}: {' or '.join(d['auth'])}"
        user = str(spec.get("user") or "").strip()
        if auth == "sql" and not user:
            errors["user"] = "a login with a password needs the user name"
        penv = str(spec.get("password_env") or "").strip()
        if penv and not ENV.match(penv):
            errors["password_env"] = "the NAME of an environment variable (letters, digits, _), never the password"
        out.update(server=server, port=port, database=database, auth=auth, user=user if auth == "sql" else "",
                   password_env=penv if auth == "sql" else "")
        if driver == "mssql":
            out.update(encrypt=_bool(spec.get("encrypt"), True),
                       trust_server_certificate=_bool(spec.get("trust_server_certificate"), False))
        if driver == "postgresql":
            mode = str(spec.get("ssl_mode") or "prefer").strip()
            if mode not in SSL_MODES:
                errors["ssl_mode"] = f"one of {', '.join(SSL_MODES)}"
            out["ssl_mode"] = mode
    try:
        timeout = int(spec.get("timeout") or 15)
        if not 1 <= timeout <= 120:
            raise ValueError
    except (TypeError, ValueError):
        errors["timeout"] = "seconds, from 1 to 120"
        timeout = 15
    out["timeout"] = timeout
    if errors:
        raise SpecError(errors)
    return out


def spec_of(source: str) -> dict | None:
    """The `database:` block of a source's register entry (checked), None when it has none."""
    from . import sources
    block = sources.entry(source).get("database")
    return check(block) if isinstance(block, dict) else None


def describe(source: str, spec: dict | None) -> str:
    """Where a connection points, for a person: no password, ever."""
    if spec is None:
        return ""
    if DRIVERS[spec["driver"]].get("file"):
        return spec["path"]
    who = {"windows": "Windows login", "none": "no login"}.get(spec["auth"], spec["user"])
    return f"{spec['server']}:{spec['port']}/{spec['database']} ({who})"


# ------------------------------------------------------------------ secrets of this session
def remember(source: str, password: str) -> None:
    with _LOCK:
        if password:
            _SESSION[source] = password
        _TESTS.pop(source, None)


def forget(source: str) -> None:
    with _LOCK:
        _SESSION.pop(source, None)
        _TESTS.pop(source, None)


def has_session_secret(source: str) -> bool:
    return source in _SESSION


def password(source: str, spec: dict) -> str | None:
    """From the session first, then from the environment variable the entry names."""
    if source in _SESSION:
        return _SESSION[source]
    env = spec.get("password_env")
    return os.environ.get(env) if env else None


def needs_password(spec: dict) -> bool:
    return spec.get("auth") == "sql"


def ready(source: str) -> tuple[bool, str]:
    """(can be read now, why not) for a database source."""
    from . import sources
    e = sources.entry(source)
    if isinstance(e.get("database"), dict):
        try:
            spec = check(e["database"])
        except SpecError as err:
            return False, f"the database block is incomplete ({err})"
        if needs_password(spec) and not password(source, spec):
            where = f" or set {spec['password_env']}" if spec.get("password_env") else ""
            return False, f"enter the password in the Connections panel{where}"
        return True, describe(source, spec)
    env = e.get("connection_env")
    if env:
        return bool(os.environ.get(env)), f"URI from the environment variable {env}" + ("" if os.environ.get(env) else " (not set)")
    return False, "not a database source"


# ------------------------------------------------------------------ reading
def uri(source: str, spec: dict) -> str:
    """A connectorx URI for a client-server database (with the password, so never shown or logged)."""
    s = spec
    pw = password(source, s) if needs_password(s) else None
    if needs_password(s) and not pw:
        raise RuntimeError(f"{source}: no password: enter it in the Connections panel"
                           + (f" or set the environment variable {s['password_env']}" if s.get("password_env") else ""))
    cred = f"{quote(s['user'], safe='')}:{quote(pw, safe='')}@" if pw else (f"{quote(s['user'], safe='')}@" if s.get("user") else "")
    base = f"{s['server']}:{s['port']}/{quote(s['database'], safe='')}"
    if s["driver"] == "mssql":
        opts = ["trusted_connection=true"] if s["auth"] == "windows" else []
        opts += [f"encrypt={'true' if s['encrypt'] else 'false'}"]
        if s["trust_server_certificate"]:
            opts.append("trust_server_certificate=true")
        return f"mssql://{'' if s['auth'] == 'windows' else cred}{base}?{'&'.join(opts)}"
    if s["driver"] == "postgresql":
        return f"postgresql://{cred}{base}?sslmode={s['ssl_mode']}"
    return f"mysql://{cred}{base}"


def _file(spec: dict) -> Path:
    p = Path(spec["path"]).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"no database file at {p}")
    return p


def read(source: str, query: str):
    """One statement against a database source, as a polars DataFrame (the caller checks it reads)."""
    import polars as pl

    from . import sources
    e = sources.entry(source)
    if isinstance(e.get("database"), dict):
        spec = check(e["database"])
        if spec["driver"] == "sqlite":
            import sqlite3
            con = sqlite3.connect(f"{_file(spec).as_uri()}?mode=ro", uri=True, timeout=spec["timeout"])
            try:
                return pl.read_database(query, con)
            finally:
                con.close()
        if spec["driver"] == "duckdb":
            import duckdb
            con = duckdb.connect(str(_file(spec)), read_only=True)
            try:
                rel = con.sql(query)
                return rel.pl() if rel is not None else pl.DataFrame()
            finally:
                con.close()
        target = uri(source, spec)
    else:
        env = e.get("connection_env")
        if not env:
            raise ValueError(f"{source} is not a database source (neither a `database:` block nor `connection_env:` "
                             "in its register entry)")
        if not os.environ.get(env):
            raise RuntimeError(f"set the environment variable {env} to the database URI of {source}, then start `sb ui` again")
        target = sqlite_uri(os.environ[env])
    try:
        return pl.read_database_uri(query, target)
    except ModuleNotFoundError as err:
        raise RuntimeError("reading SQL Server, PostgreSQL or MySQL needs connectorx: uv sync --extra sql") from err


def sqlite_uri(uri: str) -> str:
    """A SQLite URI as connectorx reads it: `sqlite:///C:/data/x.sqlite` on Windows. The form people write,
    `sqlite://C:\\data\\x.sqlite`, would be read as host `C` and fail to open; other URIs pass unchanged."""
    m = re.match(r"(?i)^sqlite:/{2,3}([A-Za-z]):[\\/](.*)$", uri)
    return f"sqlite:///{m.group(1)}:/{m.group(2).replace(chr(92), '/')}" if m else uri


def test(source: str, password_: str | None = None) -> dict:
    """Connect and ask the server for its version. The answer is kept for this session (`last_test`)."""
    if password_:
        remember(source, password_)
    spec = spec_of(source)
    statement = DRIVERS[spec["driver"]]["version"] if spec else "SELECT 1 AS ok"
    timeout = spec["timeout"] if spec else 15
    answer: dict = {}

    def run():
        try:
            df = read(source, statement)
            answer["value"] = str(df.row(0)[0]) if df.height and df.width else "connected"
        except Exception as err:                       # what the driver says is what the person needs
            answer["error"] = str(err).strip().splitlines()[0][:400] or type(err).__name__
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout + 5)
    if t.is_alive():
        result = {"status": "failed", "message": f"no answer within {timeout} s (server, port or firewall?)"}
    elif "error" in answer:
        result = {"status": "failed", "message": answer["error"]}
    else:
        result = {"status": "ok", "message": answer["value"].splitlines()[0][:300]}
    result["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        _TESTS[source] = result
    return result


def last_test(source: str) -> dict | None:
    return _TESTS.get(source)


# ------------------------------------------------------------------ the register entry
def block_text(spec: dict) -> str:
    """The `database:` block as YAML, with a comment on where the password comes from."""
    body = yaml.safe_dump({"database": {k: spec[k] for k in FIELDS if k in spec}}, sort_keys=False, allow_unicode=True)
    note = "# the password is never in this file: the session (web view) or the variable password_env names\n"
    return note + body


def set_block(text: str, spec: dict) -> str:
    """Register entry text with its `database:` block replaced (or added); other lines stay as written."""
    lines = text.splitlines(keepends=True)
    out, skip = [], False
    for ln in lines:
        if re.match(r"^database:", ln) or re.match(r"^# the password is never in this file", ln):
            skip = True
            continue
        if skip and (ln.startswith((" ", "\t")) or not ln.strip()):
            continue
        skip = False
        out.append(ln)
    text = "".join(out)
    block = block_text(spec)
    m = re.search(r"(?m)^terms:", text)
    return text[:m.start()] + block + text[m.start():] if m else text.rstrip("\n") + "\n" + block


def save(source: str, *, name: str | None, spec: dict) -> dict:
    """Create or change a database source. Returns {path, created, before} (`before`: the old text, for undo)."""
    from . import sources
    spec = check(spec)
    h = config.hub()
    f = h.datasource(source)
    if f is None:
        f = sources.add(source, name=name or source, access="database", database=spec)
        return {"path": str(f), "created": True, "before": None}
    before = f.read_text(encoding="utf-8")
    text = set_block(before, spec)
    if name is not None:
        text = re.sub(r"(?m)^name:.*$", lambda m: "name: " + yaml.safe_dump(name, default_style='"').strip(), text, count=1)
    text = re.sub(r"(?m)^access:\s*\S+", "access: database", text, count=1)
    config.write_atomic(f, text)
    forget(source)
    return {"path": str(f), "created": False, "before": before}


def remove(source: str) -> dict:
    """Delete a database source's register entry, if nothing was ever read from it. Returns {path, before}."""
    h = config.hub()
    f = h.datasource(source)
    if f is None:
        raise FileNotFoundError(f"no register entry for {source}")
    if not f.is_relative_to(h.datasources_dir):
        raise PermissionError(f"{source} is an example of the checkout, not an entry of this machine")
    e = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    if e.get("access") != "database":
        raise PermissionError(f"{source} is not a database source; remove its register entry by hand")
    if (h.raw_root / source).exists() or (f.parent / source).exists() or e.get("tables"):
        raise PermissionError(f"{source} has archived extracts, documentation or tables; its entry stays (set status: paused)")
    before = f.read_text(encoding="utf-8")
    f.unlink()
    forget(source)
    return {"path": str(f), "before": before}


def restore(source: str, text: str) -> dict:
    """Put a register entry back as it was (the undo of save or remove)."""
    from . import sources
    sources._check_id(source)
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict) or doc.get("id") != source:
        raise ValueError("not the register entry of this source")
    if isinstance(doc.get("database"), dict):
        check(doc["database"])
    h = config.hub()
    f = h.datasources_dir / f"{source}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(f, text)
    forget(source)
    return {"path": str(f)}
