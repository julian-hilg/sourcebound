"""Deliverables manager: what a study should produce, with status, notes and stored prompts.

    deliverables/notes.yaml      one entry per wanted deliverable (`sb note`, or the frontend)

An entry is a plan, not a deliverable: it names what is wanted (a paper, a two-page note, an
infographic), how far it is, what to keep in mind and the prompt an agent is given for it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from . import config

STATUS = ["idea", "planned", "drafting", "review", "done", "dropped"]
FIELDS = ("title", "kind", "status", "deliverable", "text", "prompt")
HEADER = "# Deliverables wanted for this study: status, notes and stored prompts (`sb note`).\n"


def path(project: config.Project) -> Path:
    return project.root / "deliverables" / "notes.yaml"


def load(project: config.Project | None = None) -> list[dict]:
    f = path(project or config.project())
    if not f.exists():
        return []
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("notes") or []


def _save(project: config.Project, notes: list[dict]) -> None:
    f = path(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(f, HEADER + yaml.safe_dump({"notes": notes}, sort_keys=False, allow_unicode=True, width=100))


def _clean(fields: dict) -> dict:
    out = {k: str(v).strip() for k, v in fields.items() if k in FIELDS and v is not None}
    if "status" in out and out["status"] not in STATUS:
        raise ValueError(f"status must be one of {', '.join(STATUS)}")
    if "title" in out and not out["title"]:
        raise ValueError("a note needs a title")
    return out


def add(project: config.Project | None = None, **fields) -> dict:
    """New entry; returns it with its id (N001, N002, ...)."""
    p = project or config.project()
    new = _clean(fields)
    if not new.get("title"):
        raise ValueError("a note needs a title")
    with config.locked(path(p)):
        notes = load(p)
        n = max([int(x["id"][1:]) for x in notes if str(x.get("id", ""))[1:].isdigit()] or [0]) + 1
        today = date.today().isoformat()
        entry = {"id": f"N{n:03d}", "title": new["title"], "kind": new.get("kind") or "note",
                 "status": new.get("status") or "idea", "deliverable": new.get("deliverable", ""),
                 "text": new.get("text", ""), "prompt": new.get("prompt", ""), "created": today, "updated": today}
        _save(p, [*notes, entry])
    return entry


def update(note_id: str, project: config.Project | None = None, **fields) -> tuple[dict, dict]:
    """Change fields of an entry; returns (before, after)."""
    p = project or config.project()
    new = _clean(fields)
    with config.locked(path(p)):
        notes = load(p)
        for i, x in enumerate(notes):
            if x.get("id") == note_id:
                after = {**x, **new, "updated": date.today().isoformat()}
                notes[i] = after
                _save(p, notes)
                return x, after
    raise KeyError(f"no note {note_id}")


def remove(note_id: str, project: config.Project | None = None) -> dict:
    p = project or config.project()
    with config.locked(path(p)):
        notes = load(p)
        for x in notes:
            if x.get("id") == note_id:
                _save(p, [y for y in notes if y is not x])
                return x
    raise KeyError(f"no note {note_id}")


def put(entry: dict, project: config.Project | None = None) -> dict:
    """Store an entry as given (replacing the one with its id): restores a removed or changed note."""
    p = project or config.project()
    if not str(entry.get("id", "")).startswith("N") or not str(entry.get("title", "")).strip():
        raise ValueError("an entry needs an id and a title")
    with config.locked(path(p)):
        notes = [x for x in load(p) if x.get("id") != entry["id"]]
        _save(p, sorted([*notes, entry], key=lambda x: str(x.get("id"))))
    return entry
