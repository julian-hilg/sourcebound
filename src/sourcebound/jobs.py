"""Jobs: pipelines that run again and again (continuous collection, "pseudo-APIs").

    <registry>/jobs/<id>.yaml        what to run and how often
    <data root>/jobs/state.json      last run of every job
    <data root>/jobs/log.jsonl       one line per run

A source without an API becomes a table that stays current: a pipeline fetches the page
through `sourcebound.fetch.Fetcher` (rate limit, robots.txt, stop on refusal: all unchanged),
parses it and upserts into a lake table with a contract; a job runs that pipeline on a
schedule.  Projects and apps then read the table like any other, with snapshots: that is the
pseudo-API.  A job never retries a stopped host: the pipeline fails with the fetcher's
message, the failure is logged, and the job waits for the person to look.

Sourcebound has no daemon.  `sb job run --due` runs what is due and exits; the system's own
scheduler calls it (`sb job schedule` prints the line for cron, launchd or Task Scheduler).
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import config

EVERY = re.compile(r"(\d+)\s*(m|h|d|w)")
UNIT = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
ENTRY = """# A job: something that runs again and again (`sb job`). Edited by the person.
id: {id}
title: {title}
run: {run}                 # a pipeline script (relative to the checkout or absolute) or a command
every: {every}             # 30m | 6h | 1d | 1w
enabled: true
table: {table}             # the lake table it keeps current (for the overview; optional)
source: {source}           # the data source it reads (optional)
timeout_minutes: 30
"""


def _dir() -> Path:
    return config.hub().registry / "jobs"


def _state_file() -> Path:
    return config.hub().lake_root / "jobs" / "state.json"


def seconds(every: str) -> int:
    m = EVERY.fullmatch(str(every).strip())
    if not m:
        raise ValueError(f"every: a number and m, h, d or w (e.g. 6h), got {every!r}")
    return int(m.group(1)) * UNIT[m.group(2)]


def add(job_id: str, *, run: str, every: str, title: str = "", table: str = "", source: str = "") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", job_id):
        raise ValueError("job id: lowercase letters, digits and _")
    seconds(every)
    f = _dir() / f"{job_id}.yaml"
    if f.exists():
        raise FileExistsError(f"{f} exists -- edit it instead")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(ENTRY.format(id=job_id, title=json.dumps(title or job_id), run=json.dumps(run), every=every,
                              table=table or '""', source=source or '""'), encoding="utf-8")
    return f


def _state() -> dict:
    f = _state_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def listing() -> list[dict]:
    """Every job with its last run and when it is due next."""
    state, now, out = _state(), datetime.now(timezone.utc), []
    for f in sorted(_dir().glob("*.yaml")) if _dir().is_dir() else []:
        try:
            j = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            every = seconds(j.get("every", ""))
        except (yaml.YAMLError, ValueError) as e:
            out.append({"id": f.stem, "title": f.stem, "enabled": False, "error": str(e)})
            continue
        s = state.get(f.stem, {})
        last = datetime.fromisoformat(s["at"]) if s.get("at") else None
        nxt = last + timedelta(seconds=every) if last else now
        out.append({"id": f.stem, "title": j.get("title") or f.stem, "run": j.get("run", ""), "every": j.get("every"),
                    "enabled": bool(j.get("enabled", True)), "table": j.get("table") or "", "source": j.get("source") or "",
                    "timeout_minutes": int(j.get("timeout_minutes") or 30),
                    "last_run": s.get("at"), "last_status": s.get("status"), "last_seconds": s.get("seconds"),
                    "last_message": s.get("message", ""), "next_run": nxt.isoformat(timespec="seconds"),
                    "due": bool(j.get("enabled", True)) and nxt <= now})
    return out


def _command(run: str) -> tuple[list[str], Path]:
    home = config.home() or config.hub().root
    if sys.platform == "win32":                     # keep the backslashes of Windows paths; drop the quotes around them
        parts = [x.strip('"') for x in shlex.split(run, posix=False)]
    else:
        parts = shlex.split(run)
    first = Path(parts[0]).expanduser()
    script = first if first.is_absolute() else home / first
    if script.suffix == ".py" and script.is_file():
        return [sys.executable, str(script), *parts[1:]], home
    if parts[0] == "sb":
        return [sys.executable, "-m", "sourcebound.cli", *parts[1:]], home
    return parts, home


def run(job_id: str) -> dict:
    """Run one job now; returns its log line. A failure is recorded, not raised."""
    job = next((j for j in listing() if j["id"] == job_id), None)
    if job is None or job.get("error"):
        raise KeyError(f"no usable job {job_id}" + (f": {job['error']}" if job else ""))
    cmd, cwd = _command(job["run"])
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=job["timeout_minutes"] * 60)
        status, out = ("ok" if r.returncode == 0 else "failed"), (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    except subprocess.TimeoutExpired:
        status, out = "failed", f"did not finish within {job['timeout_minutes']} minutes"
    except OSError as e:
        status, out = "failed", str(e)
    line = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "job": job_id, "status": status,
            "seconds": round(time.monotonic() - start, 1), "message": out[-600:], "blocked": "BLOCKED" in out or "Blocked" in out}
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with config.locked(f):
        state = _state()
        state[job_id] = {k: line[k] for k in ("at", "status", "seconds", "message")}
        config.write_atomic(f, json.dumps(state, indent=2) + "\n")
        with (f.parent / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def run_due() -> list[dict]:
    return [run(j["id"]) for j in listing() if j.get("due")]


def log(limit: int = 100) -> list[dict]:
    f = _state_file().parent / "log.jsonl"
    rows = f.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:] if f.exists() else []
    out = []
    for x in rows:
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            continue
    return out[::-1]


def schedule_hint() -> str:
    """How to let the system's scheduler call `sb job run --due` every ten minutes."""
    exe = f'"{sys.executable}" -m sourcebound.cli job run --due'
    cfg = config.hub().config_file
    return (f"Sourcebound has no background service. Let the system call this every 10 minutes:\n\n"
            f"  macOS / Linux (crontab -e):\n    */10 * * * * SB_CONFIG=\"{cfg}\" {exe} >/dev/null 2>&1\n\n"
            f"  Windows (once, in a terminal):\n    schtasks /Create /SC MINUTE /MO 10 /TN sourcebound-jobs /TR \"cmd /c set SB_CONFIG={cfg}&& {exe}\"\n\n"
            "Jobs that are not due are skipped; a job whose host was stopped fails and waits for you.")
