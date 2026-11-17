"""What the agents are doing: Claude Code hook events, one line each.

    <data root>/activity/events.jsonl

Claude Code calls `sb hook` for the events configured by `sb install hooks`; the frontend
shows the lines.  A line holds the event, the tool, the subagent and one short summary (a
description, a command, a path): never a prompt, never file contents.  The hook never
blocks or fails a tool call: on any problem it writes nothing and exits 0.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config

MAX_BYTES = 5_000_000            # then the file is moved to events.1.jsonl (one generation is kept)
EVENTS = ["SessionStart", "PreToolUse", "SubagentStop", "Stop"]
SUMMARY = ("description", "command", "file_path", "path", "pattern", "url", "query", "skill")


def log_path(start: str | Path | None = None) -> Path | None:
    h = config.hub(start, required=False)
    return h.lake_root / "activity" / "events.jsonl" if h else None


def _project(cwd: str) -> str | None:
    root = config.find_up("project.yaml", cwd) if cwd and Path(cwd).is_dir() else None
    if root is None:
        return None
    try:
        return (yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8")) or {}).get("slug")
    except (OSError, yaml.YAMLError):
        return None


def line(event: dict) -> dict:
    """The line kept for one hook event (the JSON Claude Code passes on stdin)."""
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    summary = next((str(tool_input[k]) for k in SUMMARY if tool_input.get(k)), "")
    cwd = str(event.get("cwd") or "")
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": str(event.get("hook_event_name") or ""),
        "session": str(event.get("session_id") or "")[:8],
        "project": _project(cwd),
        "cwd": cwd,
        "agent": event.get("agent_type") or tool_input.get("subagent_type"),
        "tool": event.get("tool_name"),
        "summary": " ".join(summary.split())[:200],
    }


def record(event: dict) -> dict | None:
    if not isinstance(event, dict) or not event.get("hook_event_name"):
        return None
    f = log_path(event.get("cwd") or None) or log_path()
    if f is None:
        return None
    entry = line(event)
    f.parent.mkdir(parents=True, exist_ok=True)
    with config.locked(f, timeout=2.0):
        if f.exists() and f.stat().st_size > MAX_BYTES:
            os.replace(f, f.with_name("events.1.jsonl"))
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def tail(limit: int = 300) -> list[dict]:
    """The newest events, newest first."""
    f = log_path()
    if f is None or not f.exists():
        return []
    with f.open("rb") as fh:
        fh.seek(max(0, f.stat().st_size - limit * 600))
        rows = fh.read().decode("utf-8", errors="replace").splitlines()
    out = []
    for x in rows[-limit:]:
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:                # the first line of a tail may be cut
            continue
    return out[::-1]


def hook_settings() -> dict:
    """The `hooks` block for a Claude Code settings file."""
    call = [{"type": "command", "command": "sb hook"}]
    return {e: [{"matcher": "*", "hooks": call}] if e == "PreToolUse" else [{"hooks": call}] for e in EVENTS}


def install(settings: Path) -> bool:
    """Add the hooks to a Claude Code settings file (kept otherwise as it is). True if it changed."""
    doc = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    hooks = doc.setdefault("hooks", {})
    changed = False
    for name, block in hook_settings().items():
        present = any(h.get("command") == "sb hook" for group in hooks.get(name, []) for h in group.get("hooks", []))
        if not present:
            hooks.setdefault(name, []).extend(block)
            changed = True
    if changed:
        settings.parent.mkdir(parents=True, exist_ok=True)
        config.write_atomic(settings, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return changed
