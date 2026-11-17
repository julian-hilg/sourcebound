"""Paper store: the PDFs a project works with, and their text, shared by all projects.

    <data root>/library/
      index.json                 citation key -> sha256 of the PDF
      <sha256>/paper.pdf         unchanged copy of the Zotero attachment
      <sha256>/source.json       citation keys, original file name, date
      <sha256>/paper.md, ...     written by the converter, if one is configured
      convert.log, convert.lock  the background conversion

    sb bib link                  are the project's Zotero collections there? (create them in Zotero)
    sb papers sync               copy the PDFs of linked collections and cited items; start converting
    sb papers convert [--background] [--retry]
    sb papers status
    sb source <citekey> [--grep WORD] [--page N]     text of a paper, for verification

The store is keyed by the PDF's sha256: a paper used by two projects is stored and converted
once, and replacing a file in Zotero adds a new entry instead of changing an old one.

Conversion to Markdown is optional.  Sourcebound runs the command named in the configuration

    [library]
    converter = "formula-snip convert {pdf} --out {out}"     # a recommendation; any tool works

and keeps whatever it writes into {out}.  Without a converter (or before it has run) the text
comes from `pdftotext` when that is installed.  The PDF page is the authority; converted text
is for finding and checking passages.  PDFs and their text are copyrighted: they stay in the
data root and never enter a project repository, `sb publish` or the handover.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, zotero


def root() -> Path:
    return config.hub().library


def _index() -> dict[str, str]:
    f = root() / "index.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def collections(project: config.Project) -> list[str]:
    """Zotero collection paths linked to the project (`zotero_collections:` or `zotero_collection:`)."""
    many = project.meta.get("zotero_collections")
    one = project.meta.get("zotero_collection")
    return [str(c).strip("/") for c in (many or ([one] if one else []))]


def linked(project: config.Project | None = None) -> dict[str, list[str] | None]:
    """{collection path: citation keys in it}; None for a collection that is not in Zotero."""
    p = project or config.project()
    return {c: zotero.collection_keys(c) for c in collections(p)}


def wanted(project: config.Project) -> set[str]:
    """Citation keys whose papers belong in the store: linked collections and cited items."""
    keys = {k for ks in linked(project).values() for k in ks or []}
    web, inbox = zotero._web_sources(project), zotero.inbox_keys(project)
    return keys | {k for k in zotero.cited_keys(project) if k not in web and k not in inbox}


def sync(project: config.Project | None = None) -> dict[str, list[str]]:
    """Copy the PDFs of the project's papers from Zotero into the store."""
    p = project or config.project()
    lib = root()
    lib.mkdir(parents=True, exist_ok=True)
    index = _index()
    rep: dict[str, list[str]] = {"added": [], "present": [], "no_pdf": []}
    for key in sorted(wanted(p)):
        pdfs = [Path(a["path"]) for a in zotero.attachments(key)
                if str(a.get("path", "")).lower().endswith(".pdf") and Path(a["path"]).is_file()]
        if not pdfs:
            rep["no_pdf"].append(key)
            continue
        body = pdfs[0].read_bytes()
        sha = hashlib.sha256(body).hexdigest()
        d = lib / sha
        if not (d / "paper.pdf").exists():
            d.mkdir(exist_ok=True)
            (d / "paper.pdf").write_bytes(body)
        meta_f = d / "source.json"
        meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {
            "sha256": sha, "file": pdfs[0].name, "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "citekeys": []}
        if key not in meta["citekeys"]:
            meta["citekeys"] = sorted({*meta["citekeys"], key})
            meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rep["present" if index.get(key) == sha else "added"].append(key)
        index[key] = sha
    (lib / "index.json").write_text(json.dumps(dict(sorted(index.items())), indent=1) + "\n", encoding="utf-8")
    return rep


# ------------------------------------------------------------------ conversion
def markdown(entry: Path) -> Path | None:
    """The converted text of a store entry, if a converter wrote one."""
    if (entry / "paper.md").exists():
        return entry / "paper.md"
    return next(iter(sorted(entry.glob("*.md"))), None)


def status() -> list[dict]:
    """One row per stored paper: sha256, citation keys, state (converted | failed | pending)."""
    lib, rows = root(), []
    for d in sorted(x for x in lib.iterdir() if (x / "paper.pdf").exists()) if lib.is_dir() else []:
        meta = json.loads((d / "source.json").read_text(encoding="utf-8")) if (d / "source.json").exists() else {}
        state = "converted" if markdown(d) else "failed" if (d / "convert_error.txt").exists() else "pending"
        rows.append({"sha256": d.name, "citekeys": meta.get("citekeys", []), "file": meta.get("file", ""), "state": state})
    return rows


def converter() -> list[str] | None:
    """The configured converter command, or None (conversion is optional)."""
    cmd = config.hub().converter
    if not cmd:
        return None
    if os.name == "nt":                       # keep the backslashes of Windows paths
        return [a.strip('"') for a in shlex.split(cmd, posix=False)]
    return shlex.split(cmd)


def running() -> int | None:
    """Process id of a conversion that is under way, if any."""
    lock = root() / "convert.lock"
    try:
        pid = int(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    if os.name == "nt":                         # os.kill(pid, 0) would end the process on Windows
        import ctypes
        k = ctypes.windll.kernel32
        handle = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(handle, ctypes.byref(code))
        k.CloseHandle(handle)
        return code.value == 259                            # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def convert(*, retry: bool = False) -> dict[str, list[str]]:
    """Run the converter on every stored PDF without text.  One conversion runs at a time."""
    cmd = converter()
    if cmd is None:
        raise RuntimeError("no converter configured (optional): set `converter` under [library] in the "
                           'configuration, e.g. converter = "formula-snip convert {pdf} --out {out}"')
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(f"converter not found on PATH: {cmd[0]}")
    if running():
        raise RuntimeError(f"a conversion is already running (process {running()}); see `sb papers status`")
    lib = root()
    lock = lib / "convert.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    rep: dict[str, list[str]] = {"converted": [], "failed": []}
    try:
        for row in status():
            if row["state"] == "converted" or (row["state"] == "failed" and not retry):
                continue
            d = lib / row["sha256"]
            (d / "convert_error.txt").unlink(missing_ok=True)
            run = [a.format(pdf=str(d / "paper.pdf"), out=str(d)) for a in cmd]
            r = subprocess.run(run, capture_output=True, text=True, encoding="utf-8", errors="replace")
            name = ", ".join(row["citekeys"]) or row["sha256"][:12]
            if r.returncode == 0 and markdown(d):
                rep["converted"].append(name)
            else:
                (d / "convert_error.txt").write_text(
                    f"exit {r.returncode}\n{(r.stderr or r.stdout)[-2000:]}\n" if r.returncode else
                    "the converter wrote no Markdown file\n", encoding="utf-8")
                rep["failed"].append(name)
            print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {'ok    ' if markdown(d) else 'FAILED'} {name}", flush=True)
    finally:
        lock.unlink(missing_ok=True)
    return rep


def convert_in_background(*, retry: bool = False) -> int | None:
    """Start `sb papers convert` detached from this session; returns its process id.

    None when nothing is to do, no converter is configured or one is running already.
    """
    todo = [r for r in status() if r["state"] == "pending" or (retry and r["state"] == "failed")]
    cmd = converter()
    if not todo or cmd is None or shutil.which(cmd[0]) is None or running():
        return None
    log = (root() / "convert.log").open("a", encoding="utf-8")
    detached = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                if os.name == "nt" else {"start_new_session": True})
    proc = subprocess.Popen([sys.executable, "-m", "sourcebound.cli", "papers", "convert", *(["--retry"] if retry else [])],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **detached)
    return proc.pid


# ------------------------------------------------------------------ reading
def text(citekey: str, *, page: int | None = None) -> tuple[str, dict]:
    """Text of a stored paper (converted Markdown, else pdftotext), whole or one page."""
    sha = _index().get(citekey)
    if sha is None:
        raise FileNotFoundError(f"{citekey}: not in the paper store (sb papers sync)")
    d = root() / sha
    md = markdown(d)
    info = {"sha256": sha, "kind": "converted Markdown" if md else "pdftotext", "page": page}
    if md:
        body = md.read_text(encoding="utf-8", errors="replace")
        if page is not None:
            parts = re.split(r"<!--\s*page\s+(\d+)\s*-->", body)
            pages = {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
            if not pages:
                raise RuntimeError(f"{citekey}: the converted text has no page markers; read it whole")
            body = pages.get(page, "")
        return body, info
    if shutil.which("pdftotext") is None:
        raise RuntimeError(f"{citekey}: not converted yet and pdftotext is not installed (sb papers status)")
    args = ["pdftotext", "-layout", *(["-f", str(page), "-l", str(page)] if page else []), str(d / "paper.pdf"), "-"]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout, info
