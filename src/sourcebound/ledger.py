"""Evidence ledger: hypotheses, claims and web sources of one project.

    hypotheses.yaml        what we test, how, and what would refute it (frozen before analysis)
    evidence/claims.yaml   every substantive statement -> evidence refs + stance
    evidence/sources.yaml  web pages / documents outside Zotero, with archived snapshot

Evidence references (claims.yaml `ref`):
    <citekey>              Zotero item (Better BibTeX key)            + loc: "p. 12" / quote
    W-0001                 web source in evidence/sources.yaml        + loc / quote
    R:h1.kurtosis          a recorded result (results/results.json)
    data:market.fx@42      a lake table at snapshot 42
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import yaml

from . import config, results, zotero

H_STATUS = {"proposed", "frozen", "running", "supported", "refuted", "inconclusive", "dropped"}
C_STATUS = {"open", "supported", "contested", "refuted"}
C_KIND = {"fact", "literature", "empirical", "estimate", "definition", "assumption"}
STANCE = {"supports", "contradicts", "context"}
H_REQUIRED = ("id", "statement", "prediction", "test", "data", "decision_rule", "kill", "status")
H_MUTABLE = {"status", "results"}          # everything else is registered and fixed by `sb freeze`
H_TESTED = {"running", "supported", "refuted", "inconclusive"}


def fingerprint(h: dict) -> str:
    """Hash of the registered content of a hypothesis (all fields except status and results)."""
    fixed = {k: v for k, v in h.items() if k not in H_MUTABLE}
    return hashlib.sha256(json.dumps(fixed, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _load(path: Path, key: str) -> tuple[dict, list[dict]]:
    if not path.exists():
        return {}, []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc, doc.get(key) or []


def load(project: config.Project | None = None) -> dict:
    p = project or config.project()
    hdoc, hyps = _load(p.root / "hypotheses.yaml", "hypotheses")
    _, claims = _load(p.root / "evidence" / "claims.yaml", "claims")
    _, sources = _load(p.root / "evidence" / "sources.yaml", "sources")
    return {"project": p, "hdoc": hdoc, "hypotheses": hyps, "claims": claims, "sources": sources}


def check(project: config.Project | None = None, *, resolve_citekeys: bool = True) -> tuple[list[str], list[str]]:
    """(errors, warnings) for the whole ledger."""
    L = load(project)
    p: config.Project = L["project"]
    errs, warns = [], []
    res = results.load(p)
    hids = [h.get("id") for h in L["hypotheses"]]
    cids = [c.get("id") for c in L["claims"]]
    sids = [s.get("id") for s in L["sources"]]
    for kind, ids in (("hypothesis", hids), ("claim", cids), ("source", sids)):
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errs.append(f"duplicate {kind} ids: {sorted(dup)}")

    for h in L["hypotheses"]:
        hid = h.get("id", "?")
        for f in H_REQUIRED:
            if not h.get(f):
                errs.append(f"{hid}: missing field '{f}'")
        if h.get("status") not in H_STATUS:
            errs.append(f"{hid}: status {h.get('status')!r} not in {sorted(H_STATUS)}")
        for r in h.get("results", []) or []:
            if r.removeprefix("R:") not in res:
                (errs if h.get("status") in {"supported", "refuted", "inconclusive"} else warns).append(
                    f"{hid}: result {r} not recorded yet")
        if h.get("status") in {"supported", "refuted", "inconclusive"} and not h.get("results"):
            errs.append(f"{hid}: decided ({h['status']}) without linked results")
        for c in h.get("motivated_by", []) or []:
            if c not in cids:
                errs.append(f"{hid}: motivated_by {c} is not a claim id")

    for s in L["sources"]:
        if not re.fullmatch(r"W-\d{4}", str(s.get("id", ""))):
            errs.append(f"source id {s.get('id')!r} must look like W-0001")
        for f in ("url", "title", "accessed"):
            if not s.get(f):
                errs.append(f"{s.get('id')}: missing '{f}'")
        if not s.get("sha256"):
            warns.append(f"{s.get('id')}: no archived snapshot (use `sb snap URL`)")

    citekeys: set[str] = set()
    for c in L["claims"]:
        cid = c.get("id", "?")
        if not re.fullmatch(r"C\d{3,}", str(cid)):
            errs.append(f"claim id {cid!r} must look like C001")
        if not c.get("text"):
            errs.append(f"{cid}: missing text")
        if c.get("status") not in C_STATUS:
            errs.append(f"{cid}: status {c.get('status')!r} not in {sorted(C_STATUS)}")
        if c.get("kind") and c["kind"] not in C_KIND:
            errs.append(f"{cid}: kind {c['kind']!r} not in {sorted(C_KIND)}")
        evs = c.get("evidence", []) or []
        stances = [e.get("stance", "supports") for e in evs]
        if c.get("status") == "supported" and "supports" not in stances:
            errs.append(f"{cid}: status supported but no supporting evidence")
        if c.get("status") == "contested" and not {"supports", "contradicts"} <= set(stances):
            warns.append(f"{cid}: contested should cite both supporting and contradicting evidence")
        for e in evs:
            ref = str(e.get("ref", ""))
            if e.get("stance", "supports") not in STANCE:
                errs.append(f"{cid}: stance {e.get('stance')!r} not in {sorted(STANCE)}")
            if ref.startswith("R:"):
                if ref[2:] not in res:
                    errs.append(f"{cid}: result {ref} not in results.json")
            elif ref.startswith("W-"):
                if ref not in sids:
                    errs.append(f"{cid}: {ref} not in evidence/sources.yaml")
            elif ref.startswith("data:"):
                if not re.fullmatch(r"data:[a-z0-9_]+\.[a-z0-9_]+(@\d+)?", ref):
                    errs.append(f"{cid}: data ref {ref!r} must be data:schema.table@snapshot")
            elif ref:
                citekeys.add(ref)
                if not (e.get("loc") or e.get("quote")):
                    warns.append(f"{cid}: {ref} without loc/quote (page, section or verbatim quote)")
            else:
                errs.append(f"{cid}: evidence without ref")
        for h in c.get("hypotheses", []) or []:
            if h not in hids:
                errs.append(f"{cid}: hypothesis {h} unknown")

    if resolve_citekeys and citekeys:
        if zotero.ready():
            unknown = citekeys - zotero.known_keys(p, citekeys)
            for k in sorted(unknown):
                errs.append(f"citekey {k!r} not in Zotero, inbox.bib or sources.yaml")
        else:
            warns.append("Zotero not running: citation keys not verified")

    fr = L["hdoc"].get("frozen")
    if fr is None and any(h.get("status") in H_TESTED for h in L["hypotheses"]):
        errs.append("hypotheses are being tested but were never frozen (`sb freeze`)")
    if fr and "hashes" not in fr:
        warns.append("hypotheses were frozen by an older version: run `sb freeze --amend` once to protect them")
    elif fr:
        hashes = fr["hashes"]
        fix = "record the change under `amendments:` (hypothesis, reason), then `sb freeze --amend`"
        for h in L["hypotheses"]:
            hid = h.get("id")
            if hid in hashes and fingerprint(h) != hashes[hid]:
                errs.append(f"{hid}: changed after the freeze of {fr.get('date')} -- {fix}")
            elif hid not in hashes and h.get("status") in H_TESTED and not h.get("exploratory"):
                errs.append(f"{hid}: tested but not part of the freeze of {fr.get('date')} -- mark it "
                            f"`exploratory: true`, or {fix}")
        for hid in sorted(set(hashes) - set(hids)):
            errs.append(f"{hid}: removed after the freeze of {fr.get('date')} (keep it with status dropped)")
    return errs, warns


def freeze(project: config.Project | None = None, *, amend: bool = False, commit: bool = True) -> str:
    """Pre-register: mark proposed hypotheses frozen and store date, git commit and a hash of
    every hypothesis, so `sb check` reports any later change.  In a git repository the frozen
    file is committed and tagged `prereg-<date>`.

    A second freeze is refused.  `amend=True` accepts changed or new hypotheses, each of which
    needs a new entry under `amendments:` that names it (`hypothesis: H2`) and gives a `reason`.
    """
    p = project or config.project()
    f = p.root / "hypotheses.yaml"
    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    hyps = doc.get("hypotheses", []) or []
    old = doc.get("frozen") or None
    amendments = doc.get("amendments") or []
    if old and not amend:
        raise ValueError(f"already frozen on {old.get('date')}: nothing may change now. For a change, add an entry "
                         "under `amendments:` (hypothesis, reason) and run `sb freeze --amend`")
    if amend and not old:
        raise ValueError("not frozen yet: run `sb freeze`")
    for h in hyps:
        missing = [k for k in H_REQUIRED if not h.get(k)]
        if missing:
            raise ValueError(f"{h.get('id')}: cannot freeze, missing {missing}")
    stamp = date.today().isoformat()
    if old and "hashes" in old:
        new = amendments[int(old.get("amendments", 0)):]
        named = {str(x) for a in new if isinstance(a, dict) and a.get("reason")
                 for x in ([a.get("hypothesis")] + list(a.get("hypotheses") or [])) if x}
        changed = [h["id"] for h in hyps if old["hashes"].get(h["id"]) != fingerprint(h)]
        unexplained = [i for i in changed if i not in named]
        if unexplained:
            raise ValueError(f"{', '.join(unexplained)}: changed or new since the freeze, but no new entry under "
                             "`amendments:` names it (- {date: ..., hypothesis: H2, reason: ...})")
    for h in hyps:
        if h["status"] == "proposed":
            h["status"] = "frozen"
    git = results._git(p.root)
    doc["frozen"] = {"date": old.get("date", stamp) if old else stamp, "git": old.get("git") if old else git,
                     **({"amended": stamp} if old and "hashes" in old else {}),
                     "amendments": len(amendments), "hashes": {h["id"]: fingerprint(h) for h in hyps}}
    text = f.read_text(encoding="utf-8")
    m = re.search(r"(?m)^(frozen|amendments|hypotheses):", text)
    head = text[:m.start()] if m else ""          # keep the explanatory comment block
    body = yaml.safe_dump({"frozen": doc["frozen"], "amendments": doc.get("amendments") or [],
                           "hypotheses": doc["hypotheses"]}, sort_keys=False, allow_unicode=True, width=100)
    f.write_text(head.rstrip() + ("\n" if head.strip() else "") + body, encoding="utf-8")
    if git and commit:                              # the tag points at a commit that holds the frozen file
        run = lambda *a: subprocess.run(["git", *a], cwd=p.root, capture_output=True)
        note = "amended" if old and "hashes" in old else "frozen"
        if run("commit", "-m", f"Pre-registration: hypotheses {note} (sb freeze)", "--", "hypotheses.yaml").returncode == 0:
            run("tag", "-f", f"prereg-{stamp}" + ("-amended" if note == "amended" else ""))
    return stamp


def next_source_id(project: config.Project | None = None) -> str:
    _, sources = _load((project or config.project()).root / "evidence" / "sources.yaml", "sources")
    n = max([int(s["id"][2:]) for s in sources if re.fullmatch(r"W-\d{4}", str(s.get("id")))] or [0])
    return f"W-{n + 1:04d}"


SOURCES_HEAD = "# Web sources outside Zotero. Add with `sb snap URL --title ...` (archives the page).\n"
SOURCE_FIELDS = ("title", "publisher", "author", "date")      # what `sb source set` may change


def source_label(s: dict) -> str:
    """How a source is named in messages: its title, with the publisher in brackets."""
    title = s.get("title") or s.get("file") or s.get("url") or "(no title)"
    return f"{title} ({s['publisher']})" if s.get("publisher") else str(title)


def _edit_sources(p: config.Project, change):
    """Run `change(sources) -> (result, changed)` on evidence/sources.yaml under its lock; write
    the file only when something changed, keeping its leading comment block."""
    f = p.root / "evidence" / "sources.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    with config.locked(f):
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        doc = (yaml.safe_load(text) if text.strip() else None) or {}
        doc["sources"] = list(doc.get("sources") or [])
        result, changed = change(doc["sources"])
        if changed:
            head = "".join(x for x in itertools.takewhile(lambda x: x.startswith("#"), text.splitlines(True))) or SOURCES_HEAD
            config.write_atomic(f, head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    return result


def register_source(entry: dict, project: config.Project | None = None, *, new: bool = False) -> tuple[str, bool]:
    """(id, created) for a source.  The same bytes (sha256) already registered give the existing
    id and no new entry, unless `new`.  Lookup and write happen under one lock."""
    def change(sources):
        if not new and entry.get("sha256"):
            same = next((s for s in sources if s.get("sha256") == entry["sha256"]), None)
            if same is not None:
                return (str(same.get("id")), False), False
        n = max([int(s["id"][2:]) for s in sources if re.fullmatch(r"W-\d{4}", str(s.get("id")))] or [0])
        e = {"id": entry.get("id") or f"W-{n + 1:04d}", **{k: v for k, v in entry.items() if k != "id"}}
        sources.append(e)
        return (e["id"], True), True
    return _edit_sources(project or config.project(), change)


def add_source(entry: dict, project: config.Project | None = None) -> str:
    """Register a web source and return its id.  Without an `id` the next free W-xxxx is
    taken; id and entry are written under one lock, so parallel scouts get distinct ids."""
    return register_source(entry, project, new=True)[0]


def update_source(sid: str, fields: dict, project: config.Project | None = None) -> tuple[dict, dict]:
    """Change descriptive fields (title, publisher, author, date) of one source; (before, after)."""
    bad = sorted(set(fields) - set(SOURCE_FIELDS))
    if bad:
        raise ValueError(f"cannot change {', '.join(bad)} of a source (only {', '.join(SOURCE_FIELDS)})")

    def change(sources):
        s = next((x for x in sources if x.get("id") == sid), None)
        if s is None:
            raise KeyError(f"{sid}: not in evidence/sources.yaml")
        before = dict(s)
        s.update(fields)
        return (before, dict(s)), before != s
    return _edit_sources(project or config.project(), change)


def status_table(project: config.Project | None = None) -> str:
    L = load(project)
    rows = [f"{'id':<6}{'status':<14}statement"]
    for h in L["hypotheses"]:
        rows.append(f"{h.get('id', '?'):<6}{h.get('status', '?'):<14}{str(h.get('statement', ''))[:70]}")
    n = {s: sum(1 for c in L["claims"] if c.get("status") == s) for s in sorted(C_STATUS)}
    rows.append("claims: " + ", ".join(f"{k} {v}" for k, v in n.items()) + f"; web sources: {len(L['sources'])}")
    fr = L["hdoc"].get("frozen")
    rows.append(f"pre-registration: {'frozen ' + str(fr.get('date')) if fr else 'not frozen'}")
    return "\n".join(rows)
