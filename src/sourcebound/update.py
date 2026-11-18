"""`sb update`: bring the checkout and its environment up to date, keeping what is installed.

    git pull --ff-only                  the checkout (refused over uncommitted changes)
    uv sync --extra ... (as before)     `uv sync` installs exactly the extras it is given and removes
                                        the others, so the extras installed now are named again
                                        (Windows: --inexact --no-install-project, see `plan`)
    sb install                          launcher, playbooks and subagents (copies on Windows)
    frontend build                      only where the web view was built before
    sb doctor

Which extras are installed is read from the environment (an extra counts as installed when all
of its packages are), not from a file of its own.  The steps after the pull run in new processes:
this one still holds the code from before the pull.  Projects and the data root are not touched.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path


def extras(pyproject: Path) -> dict[str, list[str]]:
    """{extra: [package names]} from the checkout's pyproject.toml."""
    doc = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    out = {}
    for name, reqs in (doc.get("project", {}).get("optional-dependencies") or {}).items():
        out[name] = [re.split(r"[\s<>=!~;\[]", r.strip(), maxsplit=1)[0] for r in reqs if r.strip()]
    return out


def _installed(package: str) -> bool:
    try:
        metadata.distribution(package)
        return True
    except metadata.PackageNotFoundError:
        return False


def installed_extras(pyproject: Path) -> list[str]:
    return sorted(name for name, pkgs in extras(pyproject).items() if pkgs and all(_installed(p) for p in pkgs))


def plan(home: Path, wanted: list[str], *, pull: bool = True, frontend: bool | None = None) -> list[tuple[str, list[str]]]:
    """The steps as (what, command), in order."""
    py = sys.executable
    uv = shutil.which("uv") or "uv"
    steps: list[tuple[str, list[str]]] = []
    if pull:
        steps.append(("pull the checkout", ["git", "-C", str(home), "pull", "--ff-only"]))
    sync = [uv, "sync"]                                # run in the checkout (cwd), see `run`
    if sys.platform == "win32":
        # Windows cannot replace or rename the sb.exe running this update, and uv rewrites it whenever
        # it reinstalls Sourcebound itself.  Leave Sourcebound installed as it is (an editable install:
        # the pulled code is used anyway) and only bring its dependencies and plugins up to date.
        sync += ["--inexact", "--no-install-project"]
    for e in wanted:
        sync += ["--extra", e]
    steps.append(("install the packages" + (f" (extras: {', '.join(wanted)})" if wanted else ""), sync))
    steps.append(("install sb, playbooks and subagents", [py, "-m", "sourcebound.cli", "install"]))
    built = (home / "frontend" / "dist" / "index.html").exists()
    if frontend if frontend is not None else built:
        steps.append(("build the web view", [py, "-c", "from sourcebound import ui; ui.build_frontend()"]))
    steps.append(("check the installation", [py, "-m", "sourcebound.cli", "doctor"]))
    return steps


def dirty(home: Path) -> list[str]:
    """Tracked files with uncommitted changes (untracked files do not stop a pull)."""
    r = subprocess.run(["git", "-C", str(home), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []


def run(home: Path, *, add: list[str], pull: bool = True, frontend: bool | None = None, dry_run: bool = False) -> int:
    from .ui import _drive_path
    # a checkout on a network share as its mapped drive (Z:\...), not \\server\share\...: uv writes the
    # paths of the plugins into uv.lock relative to the project only when it sees the project that way
    home = Path(_drive_path(home))
    known = extras(home / "pyproject.toml")
    unknown = [e for e in add if e not in known]
    if unknown:
        raise SystemExit(f"sb update: no extra {', '.join(unknown)} (known: {', '.join(sorted(known))})")
    wanted = sorted(set(installed_extras(home / "pyproject.toml")) | set(add))
    if pull and not (home / ".git").exists():
        raise SystemExit(f"sb update: {home} is not a git checkout; update it by hand, or use --no-pull")
    changed = dirty(home) if pull else []
    if changed:
        raise SystemExit("sb update: the checkout has uncommitted changes; commit or stash them first:\n  "
                         + "\n  ".join(changed[:12]))
    steps = plan(home, wanted, pull=pull, frontend=frontend)
    for what, cmd in steps:
        print(f"== {what}\n   {' '.join(cmd)}", flush=True)
        if dry_run:
            continue
        r = subprocess.run(cmd, cwd=home)
        if r.returncode == 0 and cmd[1:2] == ["sync"] and pull and dirty(home):
            print("note: uv sync changed uv.lock in the checkout; check `git diff uv.lock` before committing", flush=True)
        if r.returncode:
            print(f"sb update: stopped: `{what}` failed (exit {r.returncode}); the steps after it did not run", flush=True)
            return r.returncode
    if not dry_run:
        from . import ui
        if ui.running():
            print("note: the web view is running with the old code; close it and start it again (desktop icon or sb ui)")
        print("updated. Projects and the data root were not touched.")
    return 0
