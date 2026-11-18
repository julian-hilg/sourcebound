"""Toolkits: an organisation's own code, used beside Sourcebound without mixing environments.

Many organisations already have a code base with its own Python environment, database access
and agent skills (`<checkout>/.../skills/<id>/SKILL.md`): chart engines in the house style,
report builders, data extracts.  Sourcebound does not copy that code or its skills.  A plugin
names the checkout as a *toolkit*, and Sourcebound

* finds it on this machine (`find`), and its environment (`<checkout>/.venv` unless said otherwise),
* checks it (`sb toolkit check NAME`, `sb doctor`): checkout, environment, the plugin's own checks,
* runs its scripts in *its* environment (`sb toolkit run NAME SCRIPT ...`), never in Sourcebound's:
  `UV_PROJECT_ENVIRONMENT` and `VIRTUAL_ENV` point at the toolkit's environment while the script
  runs, so a `uv run` inside the script cannot install the toolkit's packages into Sourcebound's,
* lists its skills (`sb toolkit skills NAME`), so an agent reads the skill where it lives, in the
  version that matches the code it runs.

A plugin registers one:

    def register(api):
        api.toolkit("firm-lib", title="Firm library: charts and reports",
                    find=lambda: Path("C:/repos/firm-lib"),          # None when it is not on this machine
                    skills="plugins/firm/skills",                      # where skills/<id>/SKILL.md live, relative
                    env=lambda root: {"FIRM_ENV_FILE": str(root / ".env")},
                    checks=lambda root: [("warning", "no .env: database scripts will fail")] if ... else [])

Packs say what they need in pack.yaml, and `sb pack install` and `sb doctor` report it:

    requires:
      plugins: [firm]                       # Sourcebound plugins (sb plugin list)
      toolkits: [firm-lib]                  # registered by a plugin, found on this machine
      skills: [firm:charts]                 # Claude Code plugin skills, as <plugin>:<skill>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Toolkit:
    name: str
    title: str = ""
    find: Callable[[], Path | None] | None = None          # the checkout on this machine
    skills: str = "skills"                                 # folder of skills/<id>/SKILL.md, relative to the checkout
    env: Callable[[Path], dict] | None = None              # further environment variables for its scripts
    python: Callable[[Path], Path | None] | None = None    # its interpreter (default: <checkout>/.venv)
    checks: Callable[[Path], list] | None = None           # [(level, text)], level "error" | "warning"
    plugin: str = ""


@dataclass
class Status:
    name: str
    title: str
    root: Path | None = None
    python: Path | None = None
    skills: dict = field(default_factory=dict)             # id -> SKILL.md
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def registered() -> dict[str, Toolkit]:
    from . import plugins
    return plugins.load().toolkits


def get(name: str) -> Toolkit:
    tk = registered().get(name)
    if tk is None:
        known = ", ".join(sorted(registered())) or "none"
        raise KeyError(f"no toolkit {name!r} (registered by plugins: {known}; `sb plugin list`)")
    return tk


def _venv_python(root: Path) -> Path | None:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (root / rel).is_file():
            return root / rel
    return None


def status(name: str) -> Status:
    tk = get(name)
    st = Status(tk.name, tk.title)
    try:
        st.root = tk.find() if tk.find else None
    except Exception as e:  # noqa: BLE001 -- a plugin's finder must not take `sb` down
        st.errors.append(f"finding the checkout failed: {type(e).__name__}: {e}")
        return st
    if st.root is None or not Path(st.root).is_dir():
        st.errors.append("checkout not found on this machine (see the plugin's README for where it is looked for)")
        return st
    st.root = Path(st.root)
    st.python = (tk.python(st.root) if tk.python else None) or _venv_python(st.root)
    if st.python is None:
        st.errors.append(f"no Python environment in {st.root / '.venv'} (create it there with the toolkit's own setup, e.g. `uv sync`)")
    base = st.root / tk.skills
    if base.is_dir():
        st.skills = {d.name: d / "SKILL.md" for d in sorted(base.iterdir()) if (d / "SKILL.md").is_file()}
    else:
        st.warnings.append(f"no skills folder {base}")
    if tk.checks:
        try:
            for level, text in tk.checks(st.root) or []:
                (st.errors if level == "error" else st.warnings).append(text)
        except Exception as e:  # noqa: BLE001
            st.warnings.append(f"the plugin's checks failed: {type(e).__name__}: {e}")
    return st


def environment(name: str) -> tuple[Status, dict]:
    """(status, the environment variables its scripts run with)."""
    st = status(name)
    if not st.ok:
        raise RuntimeError(f"toolkit {name}: " + "; ".join(st.errors))
    tk = get(name)
    venv = st.python.parent.parent
    env = dict(os.environ)
    # The toolkit's scripts (and any `uv run` inside them) use the toolkit's environment, never Sourcebound's.
    env.update({"UV_PROJECT_ENVIRONMENT": str(venv), "VIRTUAL_ENV": str(venv), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env["PATH"] = str(st.python.parent) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    if tk.env:
        env.update({k: str(v) for k, v in (tk.env(st.root) or {}).items()})
    return st, env


def script_path(st: Status, script: str) -> Path:
    """`skill:<id>/<path>` (inside a skill's folder) or a path relative to the checkout."""
    if script.startswith("skill:"):
        sid, _, rest = script[len("skill:"):].partition("/")
        if sid not in st.skills:
            raise FileNotFoundError(f"toolkit {st.name} has no skill {sid!r} ({', '.join(st.skills) or 'none'})")
        f = st.skills[sid].parent / rest
    else:
        f = Path(script) if Path(script).is_absolute() else st.root / script
    if not f.is_file():
        raise FileNotFoundError(f"{f} does not exist")
    return f


def run(name: str, script: str, args: list[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    """Run one script of the toolkit with its own interpreter, from the checkout (or `cwd`)."""
    st, env = environment(name)
    f = script_path(st, script)
    return subprocess.run([str(st.python), str(f), *args], cwd=str(cwd or st.root), env=env,
                          capture_output=capture, text=capture, encoding="utf-8" if capture else None)


# ------------------------------------------------------------------ Claude Code plugin skills
def claude_plugin_skills() -> dict[str, Path]:
    """Skills of the Claude Code plugins installed for this user: {"<plugin>:<skill>": SKILL.md}."""
    home = Path.home() / ".claude" / "plugins"
    out: dict[str, Path] = {}
    try:
        data = json.loads((home / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for key, entries in (data.get("plugins") or {}).items():
        plugin = key.split("@", 1)[0]
        for e in sorted(entries or [], key=lambda e: e.get("scope") != "user"):     # the user-level install first
            base = Path(str(e.get("installPath") or "")) / "skills"
            if base.is_dir():
                for d in base.iterdir():
                    if (d / "SKILL.md").is_file():
                        out.setdefault(f"{plugin}:{d.name}", d / "SKILL.md")
                break
    return out


def requirements(manifest: dict) -> list[tuple[bool, str]]:
    """What a pack's `requires:` names, each with whether this machine has it."""
    req = (manifest or {}).get("requires") or {}
    out: list[tuple[bool, str]] = []
    if req.get("plugins"):
        from . import plugins
        have = {p.name: p for p in plugins.load().plugins}
        for p in req["plugins"]:
            ok = p in have and not have[p].error
            out.append((ok, f"plugin {p}" + ("" if ok else " missing (sb plugin add FOLDER, or install it)" if p not in have else f": {have[p].error}")))
    for t in req.get("toolkits") or []:
        try:
            st = status(t)
            out.append((st.ok, f"toolkit {t}" + (f" at {st.root}" if st.ok else ": " + "; ".join(st.errors))))
        except KeyError as e:
            out.append((False, f"toolkit {t}: {e.args[0]}"))
    if req.get("skills"):
        have_s = claude_plugin_skills()
        for s in req["skills"]:
            out.append((s in have_s, f"skill {s}" + ("" if s in have_s else " not installed (install the Claude Code plugin that brings it)")))
    return out


# ------------------------------------------------------------------ the command
def cmd(a) -> None:
    if a.what == "list":
        names = sorted(registered())
        if not names:
            print("no toolkits: a plugin registers one (api.toolkit); `sb plugin list`")
        for n in names:
            st = status(n)
            where = str(st.root) if st.root else "not found"
            print(f"{n:<14} {'ok ' if st.ok else 'ERR'} {where}  ({len(st.skills)} skills)  {st.title}")
        return
    if not a.name:
        sys.exit(f"usage: sb toolkit {a.what} NAME")
    try:
        if a.what == "check":
            st = status(a.name)
            print(f"{st.name}: {st.title}\n  checkout {st.root or '--'}\n  python   {st.python or '--'}\n  skills   {', '.join(st.skills) or '--'}")
            for w in st.warnings:
                print("warning:", w)
            for e in st.errors:
                print("ERROR:  ", e)
            sys.exit(1 if st.errors else 0)
        if a.what == "skills":
            st = status(a.name)
            for sid, f in st.skills.items():
                print(f"{sid:<26} {f}")
            return
        if a.what == "run":
            if not a.args:
                sys.exit("usage: sb toolkit run NAME SCRIPT [ARGS...]   (SCRIPT: skill:<id>/scripts/x.py, or a path in the checkout)")
            done = run(a.name, a.args[0], list(a.args[1:]), cwd=Path(a.cwd) if a.cwd else None)
            sys.exit(done.returncode)
    except (KeyError, RuntimeError, FileNotFoundError) as e:
        sys.exit(str(e).strip("'\""))
