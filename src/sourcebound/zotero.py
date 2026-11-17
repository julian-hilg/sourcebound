"""Zotero (Better BibTeX) bridge: the bibliography is exactly what the project cites.

    sb bib sync         deliverables/**/*.tex + evidence/claims.yaml -> cited keys
                         -> Better BibTeX export of those keys (+ inbox.bib + web sources W-*)
                         -> deliverables/paper/references.bib  (generated, never edited)
    sb bib add DOI      DOI -> BibTeX (doi.org) appended to evidence/inbox.bib
    sb bib import       push inbox.bib into Zotero (selected collection), then empty it

Zotero must be running (Better BibTeX JSON-RPC on 127.0.0.1:23119). Citation keys are
Better BibTeX keys; agents look them up with `sb bib search "<words>"`.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx
import yaml

from . import config

COMMENT_RX = re.compile(r"(?<!\\)%.*$", re.M)


VERB_RX = re.compile(r"\\verb\*?(.)(.*?)\1|\\begin\{(verbatim|lstlisting)\}.*?\\end\{\3\}", re.S)


def strip_comments(tex: str) -> str:
    """TeX without comments and verbatim material (examples of commands are not uses)."""
    return VERB_RX.sub("", COMMENT_RX.sub("", tex))


CITE_RX = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|cites)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")
BIB_KEY_RX = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
TRANSLATOR = "Better BibLaTeX"


def _rpc(method: str, params: list, *, timeout: float = 30.0):
    url = config.hub().zotero_url.rstrip("/") + "/better-bibtex/json-rpc"
    try:
        r = httpx.post(url, json={"jsonrpc": "2.0", "method": method, "params": params}, timeout=timeout)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Zotero/Better BibTeX not reachable at {url} -- is Zotero running? ({e})") from e
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"Better BibTeX {method}: {out['error'].get('message')}")
    return out["result"]


def ready() -> bool:
    try:
        _rpc("api.ready", [], timeout=3)
        return True
    except RuntimeError:
        return False


def search(terms: str) -> list[dict]:
    """[{citekey, title, year, creators}] for a free-text search of the library."""
    out = []
    for it in _rpc("item.search", [terms]):
        year = re.search(r"\d{4}", str(it.get("issued", {}).get("date-parts", [[""]])[0][0] if it.get("issued") else ""))
        out.append({"citekey": it.get("citekey") or it.get("citationKey"), "title": it.get("title", ""),
                    "year": year.group(0) if year else "",
                    "creators": ", ".join(c.get("family", "") for c in it.get("author", [])[:3])})
    return out


def collection_keys(path: str) -> list[str] | None:
    """Citation keys of the items in a Zotero collection (`research/my_study`) and all its
    sub-collections; None if the collection does not exist.  Names match without regard to case.

    Read through Better BibTeX; collections are created in Zotero, by a person.  Sub-collections
    are walked here, so the result does not depend on Zotero's "show items from subcollections".
    """
    from urllib.parse import quote
    want = path.strip("/").lower()
    keys: set[str] | None = None
    for lib in _rpc("user.groups", [True]):
        cols = {c["key"]: c for c in lib.get("collections") or []}

        def full(c: dict) -> str:
            parent = cols.get(c.get("parentCollection") or "")
            return (full(parent) + "/" if parent else "") + c["name"]
        for p in sorted(full(c) for c in cols.values()):
            if p.lower() != want and not p.lower().startswith(want + "/"):
                continue
            url = config.hub().zotero_url.rstrip("/") + f"/better-bibtex/collection?/{lib['id']}/{quote(p)}.biblatex"
            r = httpx.get(url, timeout=120)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            keys = (keys or set()) | set(BIB_KEY_RX.findall(r.text))
    return None if keys is None else sorted(keys)


def attachments(citekey: str) -> list[dict]:
    """Attachments of an item: [{path, open}] (Better BibTeX `item.attachments`)."""
    try:
        return _rpc("item.attachments", [citekey]) or []
    except RuntimeError as e:
        if "not reachable" in str(e):
            raise
        return []


def export(keys: list[str]) -> tuple[str, list[str]]:
    """BibLaTeX for the given keys; returns (bib, missing_keys)."""
    keys = sorted(set(keys))
    if not keys:
        return "", []
    try:
        return _rpc("item.export", [keys, TRANSLATOR]), []
    except RuntimeError as e:
        if "not reachable" in str(e):
            raise
    found, missing = [], []
    for k in keys:            # slow path: find which keys are unknown
        try:
            found.append(_rpc("item.export", [[k], TRANSLATOR]))
        except RuntimeError:
            missing.append(k)
    return "\n".join(found), missing


def cited_keys(project: config.Project) -> set[str]:
    keys: set[str] = set()
    for tex in (project.root / "deliverables").rglob("*.tex"):
        for m in CITE_RX.finditer(strip_comments(tex.read_text(encoding="utf-8", errors="replace"))):
            keys |= {k.strip() for k in m.group(1).split(",") if k.strip()}
    from .handover import MD_CITE, _MATH
    for md in (project.root / "deliverables").glob("*/sections/*.md"):
        keys |= set(MD_CITE.findall(_MATH.sub(" ", md.read_text(encoding="utf-8", errors="replace"))))
    claims = project.root / "evidence" / "claims.yaml"
    if claims.exists():
        for c in (yaml.safe_load(claims.read_text(encoding="utf-8")) or {}).get("claims", []) or []:
            for ev in c.get("evidence", []) or []:
                ref = str(ev.get("ref", ""))
                if ref and not ref.startswith(("R:", "data:")):
                    keys.add(ref)
    return keys


def _web_sources(project: config.Project) -> dict[str, dict]:
    f = project.root / "evidence" / "sources.yaml"
    if not f.exists():
        return {}
    return {s["id"]: s for s in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("sources", []) or []}


def _online_entry(s: dict) -> str:
    esc = lambda t: str(t).replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")
    author = esc(s["author"]) if s.get("author") else ("{" + esc(s["publisher"]) + "}" if s.get("publisher") else "")
    fields = {"author": author, "date": str(s.get("date", "")),
              "title": esc(s.get("title", s["url"])), "url": s["url"],
              "urldate": str(s.get("accessed", ""))[:10],
              "note": f"Archived copy, SHA-256 {s['sha256'][:12]}" if s.get("sha256") else ""}
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@online{{{s['id']},\n{body}\n}}\n"


def inbox_keys(project: config.Project) -> dict[str, str]:
    f = project.root / "evidence" / "inbox.bib"
    if not f.exists():
        return {}
    text = f.read_text(encoding="utf-8")
    entries = re.split(r"(?=^@)", text, flags=re.M)
    return {m.group(1): e for e in entries if (m := BIB_KEY_RX.match(e.strip()))}


def sync(project: config.Project | None = None, out: Path | None = None) -> tuple[list[Path], list[str], bool]:
    """Write references.bib with exactly the cited keys into every deliverable folder.

    Returns (files, unresolved keys, written).  When Zotero is needed but not running, the
    existing files are left as they are (written = False) and the unresolved keys are the
    cited ones they do not hold.
    """
    project = project or config.project()
    if out is None:
        from . import deliverable
        outs = [d / "references.bib" for d in deliverable.folders(project, markdown=True)] or [
            project.root / "deliverables" / "paper" / "references.bib"]
    else:
        outs = [out]
    keys = cited_keys(project)
    web = _web_sources(project)
    inbox = inbox_keys(project)
    zkeys = sorted(k for k in keys if k not in web and k not in inbox)
    if zkeys and not ready():
        have = set.intersection(*[set(BIB_KEY_RX.findall(f.read_text(encoding="utf-8"))) if f.exists() else set()
                                  for f in outs])
        return outs, sorted(keys - have), False
    bib, missing = export(zkeys) if zkeys else ("", [])
    parts = ["% generated by `sb bib sync` -- do not edit (Zotero is the source)\n", bib]
    parts += [inbox[k] for k in sorted(keys) if k in inbox]
    parts += [_online_entry(web[k]) for k in sorted(keys) if k in web]
    for f in outs:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(p for p in parts if p).rstrip() + "\n", encoding="utf-8")
    return outs, missing, True


def known_keys(project: config.Project, keys: set[str]) -> set[str]:
    """Subset of keys that resolve (Zotero, inbox or web sources)."""
    web, inbox = _web_sources(project), inbox_keys(project)
    rest = sorted(k for k in keys if k not in web and k not in inbox)
    ok = {k for k in keys if k in web or k in inbox}
    if rest and ready():
        _, missing = export(rest)
        ok |= set(rest) - set(missing)
    return ok


def add_doi(doi: str, project: config.Project | None = None) -> str:
    """Fetch BibTeX for a DOI (doi.org content negotiation) into evidence/inbox.bib."""
    project = project or config.project()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)
    from .fetch import Fetcher
    # DOI content negotiation is the registrars' documented API; the fetcher spaces the requests
    r, _ = Fetcher("doi", respect_robots=False).get(f"https://doi.org/{doi}",
                                                    headers={"Accept": "application/x-bibtex; charset=utf-8"})
    entry = r.text.strip()
    entry = re.sub(r",\s*month\s*=\s*[A-Za-z]+(?=\s*[,}])", "", entry)   # Crossref "Sept" is not a BibTeX macro
    entry = re.sub(r",\s*url\s*=\s*\{https?://(dx\.)?doi\.org/[^}]*\}", "", entry)  # the DOI is printed already
    m = BIB_KEY_RX.match(entry)
    key = make_key(entry)
    if m:
        entry = entry[:m.start(1)] + key + entry[m.end(1):]
    f = project.root / "evidence" / "inbox.bib"
    if key in inbox_keys(project):
        return key + " (already in inbox)"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(entry + "\n\n")
    return key


def make_key(entry: str) -> str:
    """Citation key in Better BibTeX style: FamilyYearFirstTitleWord (ASCII)."""
    import unicodedata

    def field(name: str) -> str:
        m = re.search(rf"\b{name}\s*=\s*[{{\"](.+?)[}}\"]\s*(,|\n|\}})", entry, re.I | re.S)
        return m.group(1) if m else ""

    author = field("author").split(" and ")[0]
    family = author.split(",")[0] if "," in author else (author.split()[-1] if author else "Anon")
    year = (re.search(r"\d{4}", field("year")) or re.search(r"\d{4}", entry))
    stop = {"a", "an", "the", "on", "of", "for", "and", "in", "to", "with", "towards"}
    words = [w for w in re.findall(r"[A-Za-z]+", field("title")) if w.lower() not in stop]
    raw = f"{family}{year.group(0) if year else ''}{words[0].capitalize() if words else ''}"
    return re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode())


def import_inbox(project: config.Project | None = None) -> int:
    """Send inbox.bib to Zotero's connector import (lands in the selected collection).

    Zotero assigns its own Better BibTeX keys; re-run `sb bib search` and update
    citations that used the provisional inbox key."""
    project = project or config.project()
    f = project.root / "evidence" / "inbox.bib"
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    if not text.strip():
        return 0
    url = config.hub().zotero_url.rstrip("/") + "/connector/import"
    r = httpx.post(url, content=text.encode("utf-8"), headers={"Content-Type": "application/x-bibtex"},
                   timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"Zotero import failed: HTTP {r.status_code} {r.text[:200]}")
    n = len(inbox_keys(project))
    f.with_suffix(".imported.bib").open("a", encoding="utf-8").write(text)
    f.write_text("", encoding="utf-8")
    return n
