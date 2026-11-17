"""Numbers that appear in a deliverable, each with provenance.

    from sourcebound import results
    results.record("h1.kurtosis", k, fmt="{:.1f}", hypothesis="H1")
    results.record("h1.share_tail", 0.031, fmt="pct1")            # 3.1 % (de: 3,1 %)
    results.record("data.n_days", n, fmt="int")                   # 6,512 (de: 6.512)

Writes <project>/results/results.json (value + provenance) and results.tex:
    \\sbsetresult{h1.kurtosis}{4.2}[]          ->   in LaTeX:  \\result{h1.kurtosis}
Provenance per key: script, git commit (dirty flag), lake snapshots read by this process,
timestamp. Never type a number into the paper by hand -- record it here.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, lake


CODE = ["analysis", "pipelines", "contracts", "figures/make_figures.py"]    # what determines a result


def _git(root: Path) -> str | None:
    """Commit of the project's own repository; `+dirty` when its analysis code has uncommitted changes.

    None without a repository, without a commit, or when the folder is only an ignored
    folder inside another repository (that commit says nothing about this project).
    """
    run = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
    try:
        head = run("rev-parse", "--short", "HEAD")
        if head.returncode != 0 or run("check-ignore", "-q", ".").returncode == 0:
            return None
        dirty = run("status", "--porcelain", "--", *[c for c in CODE if (root / c).exists()]).stdout.strip()
        return head.stdout.strip() + ("+dirty" if dirty else "")
    except FileNotFoundError:
        return None


def format_value(value, fmt: str | None, german: bool) -> str:
    """Plain-text display; German uses decimal comma and dot thousands separator.

    fmt: None (3 significant digits) | "int" | "pct<d>" (share -> percent) |
         "sci<d>" (1.9e-26 style) | any str.format pattern such as "{:.2f}"
    """
    if isinstance(value, str):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    suffix = ""
    if fmt == "int":
        s = f"{int(round(value)):,}"
    elif fmt and fmt.startswith("pct"):
        d = int(fmt[3:] or 0)
        s, suffix = f"{100 * value:,.{d}f}", " %"
    elif fmt and fmt.startswith("sci"):
        s = f"{value:.{int(fmt[3:] or 1)}e}"
    elif fmt:
        s = fmt.format(value)
    else:
        s = f"{value:,.3g}" if isinstance(value, float) else f"{value:,}"
    if german:
        s = s.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return s + suffix


def to_tex(value, display: str) -> str:
    """LaTeX for a display string: math minus, {,} for commas, x 10^n, escaped text."""
    if isinstance(value, str) or value is None:
        return (display.replace("\\", "\\textbackslash{}").replace("&", "\\&").replace("%", "\\%")
                .replace("_", "\\_").replace("#", "\\#"))
    m = re.fullmatch(r"(-?[\d.,]+)e([+-]\d+)", display)
    if m:
        mant = m.group(1).replace(",", "{,}")
        return f"\\ensuremath{{{mant}\\times 10^{{{int(m.group(2))}}}}}"
    return (display.replace("-", "\\ensuremath{-}").replace(",", "{,}")
                   .replace(" %", "\\,\\%"))


def _paths(project: config.Project) -> tuple[Path, Path]:
    d = project.root / "results"
    d.mkdir(exist_ok=True)
    return d / "results.json", d / "results.tex"


def load(project: config.Project | None = None) -> dict:
    project = project or config.project()
    jf, _ = _paths(project)
    return json.loads(jf.read_text(encoding="utf-8")) if jf.exists() else {}


def problems(project: config.Project | None = None, *, strict: bool = False) -> tuple[list[str], list[str]]:
    """(errors, warnings) about the provenance of the recorded results.

    `strict` (the publication gate) turns results without a clean commit, and results that
    mix snapshots of one table, into errors.
    """
    p = project or config.project()
    errs, warns = [], []
    no_commit, dirty, no_data = [], [], []
    snaps: dict[str, set] = {}
    known: dict = {}
    for k, v in load(p).items():
        prov = v.get("provenance") or {}
        script = prov.get("script")
        if not script or not (p.root / str(script)).is_file():
            errs.append(f"result {k}: recorded by {script!r}, which is not a script of this project "
                        "(stale, or recorded by hand); `sb run analysis` rebuilds the results")
        git = prov.get("git")
        (no_commit if not git else dirty if str(git).endswith("+dirty") else []).append(k)
        if not prov.get("data") and not prov.get("sources"):
            no_data.append(k)
        for s in unknown_sources(prov.get("sources") or [], p, known):
            warns.append(f"result {k} rests on source {s}, which is not registered in this project")
        for t, s in (prov.get("data") or {}).items():
            snaps.setdefault(t, set()).add(s)
    short = lambda ks: ", ".join(ks[:4]) + (f" and {len(ks) - 4} more" if len(ks) > 4 else "")
    hard = errs if strict else warns
    if no_commit:
        hard.append(f"{len(no_commit)} results are not tied to a commit ({short(no_commit)}): commit the project, then `sb run analysis`")
    if dirty:
        hard.append(f"{len(dirty)} results were recorded with uncommitted analysis code ({short(dirty)}): commit, then `sb run analysis`")
    for t, s in sorted(snaps.items()):
        if len(s) > 1:
            hard.append(f"results use different snapshots of {t} ({sorted(map(str, s))}): `sb run analysis`")
    if no_data:
        warns.append(f"{len(no_data)} results name no lake table ({short(no_data)}) and no source: read data with lake.read so the "
                     "snapshot is recorded, or name the registered source with results.record(..., sources=[\"W-0001\"])")
    return errs, warns


def unknown_sources(ids: list[str], project: config.Project, known: dict | None = None) -> list[str]:
    """The ids that are neither a source in evidence/sources.yaml nor a citation key of the project.
    `known` (a dict) keeps the project's evidence between calls."""
    if not ids:
        return []
    known = {} if known is None else known
    if not known:
        from . import render
        known["refs"], known["web"] = render.evidence(project)
    return [s for s in ids if s not in known["web"] and s not in known["refs"]]


def record(key: str, value, *, fmt: str | None = None, unit: str | None = None,
           hypothesis: str | None = None, note: str | None = None,
           ci: tuple[float, float] | None = None, sources: list[str] | str | None = None) -> str:
    """Store one result; returns the formatted display string.

    `sources`: the registered sources the inputs come from when they are not a lake table,
    e.g. `sources=["W-0001"]` (ids from evidence/sources.yaml) or citation keys.  They are
    stored in the provenance; an unknown id gives a warning, not an error.
    """
    if not key.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValueError("result keys: letters, digits, '.', '_', '-' (e.g. h1.kurtosis)")
    p = config.project()
    sources = [str(s).strip().lstrip("@") for s in ([sources] if isinstance(sources, str) else sources or [])]
    for s in unknown_sources(sources, p):
        print(f"warning: result {key}: source {s} is not registered in this project "
              "(evidence/sources.yaml, evidence/inbox.bib or a references.bib)", file=sys.stderr)
    display = format_value(value, fmt, p.german)
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    entry = {
        "value": value if not isinstance(value, float) or math.isfinite(value) else None,
        "display": display,
        "tex": to_tex(value, display),
        "unit": unit,
        "ci": list(ci) if ci else None,
        "hypothesis": hypothesis,
        "note": note,
        "provenance": {
            "script": script.relative_to(p.root).as_posix() if script and script.is_relative_to(p.root) else str(script),
            "git": _git(p.root),
            "data": dict(lake.READS),
            **({"sources": sources} if sources else {}),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }
    with config.locked(_paths(p)[0]):               # analysts run in parallel
        data = load(p)
        data[key] = entry
        save(data, p)
    return display


def save(data: dict, project: config.Project) -> None:
    jf, tf = _paths(project)
    config.write_atomic(jf, json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False, default=float) + "\n")
    lines = ["% generated by sourcebound.results -- do not edit; source: results.json"]
    for k, v in sorted(data.items()):
        # the unit is typeset as it is: a bare % would start a comment and swallow the closing brace
        unit = "[%s]" % re.sub(r"(?<!\\)([%&#])", r"\\\1", str(v["unit"])) if v.get("unit") else ""
        tex = v.get("tex") or to_tex(v.get("value"), v["display"])
        lines.append(f"\\sbsetresult{{{k}}}{{{tex}}}{unit}")
    config.write_atomic(tf, "\n".join(lines) + "\n")
