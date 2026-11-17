"""Pieces: small outputs of ongoing research (a post, a note, a trade idea, a briefing).

    pieces/<id>/piece.yaml     what it is: title, kind, template, status, schedule
    pieces/<id>/text.md        the text, in the handover notation ({{result:key}}, [@W-0001])
    pieces/<id>/*.yaml         structured content a template needs (e.g. slides.yaml)
    pieces/<id>/render/        what `sb render` wrote, one folder per template

A piece needs no paper, no hypotheses and no freeze.  It still follows "no source, no claim":
every source it cites is registered in the project's ledger (an archived web page, a document
brought in with `sb doc`, a Zotero key), and every recorded number comes in as
`{{result:key}}`.  `sb piece check` reports what does not resolve.

Life of a piece:  idea -> draft -> review -> approved -> scheduled -> published  (or dropped).
`approved`, `scheduled` and `published` are the person's decisions: the command line asks for a
typed confirmation, and nothing in Sourcebound posts by itself.
"""
from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path

import yaml

from . import config, results

STATUS = ["idea", "draft", "review", "approved", "scheduled", "published", "dropped"]
USER_ONLY = {"approved", "scheduled", "published"}      # set by the person, never by an agent
FIELDS = ("title", "kind", "template", "design", "status", "lang", "channel", "scheduled_at", "published_at", "url", "note", "prompt")
ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
HEADER = "# A piece: one small output of this project (`sb piece`). The text is in text.md.\n"


def folder(project: config.Project, piece_id: str) -> Path:
    if not ID.fullmatch(piece_id):
        raise ValueError("piece id: lowercase letters, digits, - and _")
    return project.root / "pieces" / piece_id


def get(piece_id: str, project: config.Project | None = None) -> dict:
    p = project or config.project()
    f = folder(p, piece_id) / "piece.yaml"
    if not f.exists():
        raise KeyError(f"no piece {piece_id}")
    return {"id": piece_id, **(yaml.safe_load(f.read_text(encoding="utf-8")) or {})}


def load(project: config.Project | None = None) -> list[dict]:
    p = project or config.project()
    out = []
    for f in sorted((p.root / "pieces").glob("*/piece.yaml")):
        try:
            out.append({"id": f.parent.name, **(yaml.safe_load(f.read_text(encoding="utf-8")) or {})})
        except yaml.YAMLError as e:
            out.append({"id": f.parent.name, "title": f.parent.name, "status": "draft", "error": str(e)})
    return out


def _clean(fields: dict) -> dict:
    out = {k: (str(v).strip() if v is not None else "") for k, v in fields.items() if k in FIELDS and v is not None}
    if "status" in out and out["status"] not in STATUS:
        raise ValueError(f"status must be one of {', '.join(STATUS)}")
    if "title" in out and not out["title"]:
        raise ValueError("a piece needs a title")
    for k in ("scheduled_at", "published_at"):
        if out.get(k):
            out[k] = _when(out[k])
    return out


def _when(text: str) -> str:
    """A date and time as ISO 8601 with offset; a time without offset is local time."""
    try:
        d = datetime.fromisoformat(text.strip().replace(" ", "T"))
    except ValueError:
        raise ValueError(f"not a date and time: {text!r} (use 2026-11-20 08:30)")
    return (d if d.tzinfo else d.astimezone()).isoformat(timespec="minutes")


def _save(project: config.Project, piece_id: str, meta: dict) -> None:
    f = folder(project, piece_id) / "piece.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in meta.items() if k != "id" and v not in ("", None)}
    config.write_atomic(f, HEADER + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100))


def _slug(title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-")[:40].strip("-") or "piece"
    base = f"{date.today():%Y%m%d}-{base}"
    out, n = base, 1
    while out in taken:
        n += 1
        out = f"{base}-{n}"
    return out


def add(project: config.Project | None = None, *, piece_id: str | None = None, text: str | None = None, **fields) -> dict:
    """A new piece; returns its card. Without an id one is made from the date and the title."""
    p = project or config.project()
    new = _clean(fields)
    if not new.get("title"):
        raise ValueError("a piece needs a title")
    if new.get("status") in USER_ONLY:
        raise ValueError(f"a new piece starts as idea or draft; `{new['status']}` is set later, by the person")
    (p.root / "pieces").mkdir(exist_ok=True)
    with config.locked(p.root / "pieces" / ".ids"):
        pid = piece_id or _slug(new["title"], {x["id"] for x in load(p)})
        if (folder(p, pid) / "piece.yaml").exists():
            raise ValueError(f"piece {pid} exists")
        today = date.today().isoformat()
        meta = {"title": new["title"], "kind": new.get("kind") or "post", "template": new.get("template", ""),
                "design": new.get("design", ""), "status": new.get("status") or "idea", "lang": new.get("lang") or p.lang,
                "channel": new.get("channel", ""), "note": new.get("note", ""), "prompt": new.get("prompt", ""),
                "created": today, "updated": today}
        _save(p, pid, meta)
        tf = folder(p, pid) / "text.md"
        if not tf.exists():
            tf.write_text(text if text is not None else "", encoding="utf-8")
    return get(pid, p)


def update(piece_id: str, project: config.Project | None = None, *, text: str | None = None, **fields) -> tuple[dict, dict]:
    """Change the card and/or the text; returns (before, after), each with its `text`."""
    p = project or config.project()
    new = _clean(fields)
    f = folder(p, piece_id)
    with config.locked(f / "piece.yaml"):
        before = {**get(piece_id, p), "text": read_text(piece_id, p)}
        meta = {**{k: v for k, v in before.items() if k != "text"}, **new, "updated": date.today().isoformat()}
        if new.get("status") == "scheduled" and not meta.get("scheduled_at"):
            raise ValueError("a scheduled piece needs a date and time (scheduled_at)")
        if "scheduled_at" in new and new["scheduled_at"] == "" and meta.get("status") == "scheduled":
            meta["status"] = "approved"
        _save(p, piece_id, meta)
        if text is not None:
            config.write_atomic(f / "text.md", text)
    return before, {**get(piece_id, p), "text": read_text(piece_id, p)}


def read_text(piece_id: str, project: config.Project | None = None) -> str:
    f = folder(project or config.project(), piece_id) / "text.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def remove(piece_id: str, project: config.Project | None = None) -> dict:
    """Move a piece to pieces/.removed/ (so a removal can be undone); returns its card and text."""
    p = project or config.project()
    card = {**get(piece_id, p), "text": read_text(piece_id, p)}
    bin_ = p.root / "pieces" / ".removed"
    bin_.mkdir(exist_ok=True)
    dest = bin_ / piece_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(folder(p, piece_id)), dest)
    return card


def restore(piece_id: str, project: config.Project | None = None) -> dict:
    p = project or config.project()
    src = p.root / "pieces" / ".removed" / piece_id
    if not src.exists():
        raise KeyError(f"no removed piece {piece_id}")
    if folder(p, piece_id).exists():
        raise ValueError(f"piece {piece_id} exists")
    shutil.move(str(src), folder(p, piece_id))
    return get(piece_id, p)


def due(project: config.Project | None = None, *, now: datetime | None = None) -> list[dict]:
    """Scheduled pieces whose time has come, oldest first."""
    now = now or datetime.now().astimezone()
    rows = [x for x in load(project) if x.get("status") == "scheduled" and x.get("scheduled_at")
            and datetime.fromisoformat(str(x["scheduled_at"])) <= now]
    return sorted(rows, key=lambda x: str(x["scheduled_at"]))


def check(piece_id: str, project: config.Project | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings): sources and results the text refers to, numbers typed by hand, stale renders."""
    from . import deliverable, render
    p = project or config.project()
    doc = render.from_piece(p, piece_id)
    errs, warns = [], []
    import json
    body = doc.text + "\n" + json.dumps(doc.data, ensure_ascii=False)
    for k in sorted({k.strip() for k in render.MD_RESULT.findall(body)} - set(doc.results)):
        errs.append(f"result {k} is used but not recorded")
    for k in render.cited(body):
        if re.fullmatch(r"W-\d{4}", k):
            if k not in doc.web_sources:
                errs.append(f"source {k} is cited but not in evidence/sources.yaml (sb snap URL, or sb doc FILE)")
        elif k not in doc.references:
            warns.append(f"citation key {k} is not in evidence/inbox.bib or a references.bib of this project")
    if not render.cited(body) and doc.text.strip():
        warns.append("the text cites no source: every substantive statement needs one ([@W-0001] or [@citekey])")
    hits = deliverable.typed_numbers(doc.text, markdown=True)
    if hits:
        warns.append(f"{len(hits)} lines with a number typed by hand (lines {', '.join(str(n) for n, _ in hits[:6])}"
                     f"{', ...' if len(hits) > 6 else ''}): record it and use {{{{result:key}}}}, or make sure its source is cited")
    current = results.load(p)
    for m in render.renders(folder(p, piece_id) / "render"):
        changed = render.stale(m, current)
        if changed:
            warns.append(f"render {m['template']} shows older values of {', '.join(changed[:5])}: sb render {piece_id} --template {m['template']}")
    return errs, warns


def summary(project: config.Project | None = None) -> list[dict]:
    """Every piece with its text, renders and files, for the frontend."""
    from . import render
    p = project or config.project()
    out = []
    for card in load(p):
        f = folder(p, card["id"])
        rs = []
        for m in render.renders(f / "render"):
            rel = Path(m["folder"]).relative_to(p.root).as_posix()
            rs.append({"template": m["template"], "kind": m["kind"], "design": m["design"], "at": m["at"], "notes": m.get("notes") or [],
                       "files": [f"{rel}/{x}" for x in m["files"]], "stale": render.stale(m, results.load(p))})
        out.append({**card, "text": read_text(card["id"], p),
                    "data_files": sorted(x.name for x in f.glob("*.yaml") if x.name != "piece.yaml"), "renders": rs})
    return out
