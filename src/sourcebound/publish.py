"""Production bundle: what goes to GitHub is built, checked and pushed -- never the working tree.

    sb publish            build dist/public + dist/data, run all gates, print the report
    sb publish --push     ... and commit + push dist/public to github.com/<owner>/<repo>

dist/public  (git repo of its own, the only thing that reaches GitHub)
    README.md, LICENSE, CITATION.cff     from public/
    <slug>.pdf                           the deliverable (PDF only -- no .tex, no .bib)
    code + outputs                       project.yaml publish.include (allowlist)
    src/sourcebound/                      vendored copy, so analyses run without the hub
    data/README.md, data/manifest.json   where to download each table + sha256
dist/data    Parquet + datapackage.json  -> upload to Zenodo (DOI) / R2 / Hugging Face,
                                            never into git
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from . import config, contracts, deliverable, handover, lake, ledger, results

NEVER = ["*.tex", "*.bib", "*.sty", "*.cls", "*.aux", "*.log", ".env", ".env.*", "*.sqlite",
         "*.duckdb", "*.zst", "**/raw/**", "**/.venv/**", "**/__pycache__/**", "*.pyc", ".DS_Store",
         "**/node_modules/**", "**/.git/**", "*.fdb_latexmk", "*.fls", "*.synctex.gz", "layout.json"]
SECRET_RX = re.compile(r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|"
                       r"sk-[A-Za-z0-9_-]{20,}|xox[bap]-[A-Za-z0-9-]{10,}|(?i:password|secret|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,})")
MAX_FILE_MB = 20


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _excluded(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in NEVER)


def _collect(root: Path, patterns: list[str]) -> list[Path]:
    files: set[Path] = set()
    for pat in patterns:
        hits = [root / pat] if (root / pat).is_file() else list(root.glob(pat.rstrip("/") + ("/**/*" if pat.endswith("/") else "")))
        files |= {f for f in hits if f.is_file()}
    return sorted(files)


def gates(p: config.Project, files: list[Path]) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    e, w = ledger.check(p)
    errs += [f"ledger: {x}" for x in e]
    warns += [f"ledger: {x}" for x in w]
    L = ledger.load(p)
    open_h = [h["id"] for h in L["hypotheses"] if h.get("status") in {"proposed", "frozen", "running"}]
    if open_h:
        errs.append(f"hypotheses not decided: {open_h} (decide or mark dropped)")
    open_c = [c["id"] for c in L["claims"] if c.get("status") == "open"]
    if open_c:
        warns.append(f"claims still open: {open_c}")
    e, w = results.problems(p, strict=True)
    errs += [f"results: {x}" for x in e]
    warns += [f"results: {x}" for x in w]
    reviews = list((p.root / "reviews").glob("*.md"))
    verif = [r for r in reviews if "verif" in r.name]
    if not verif:
        errs.append("no verification report in reviews/ (run the verifier agent)")
    else:
        last = max(r.stat().st_mtime for r in verif)
        newer = [f.relative_to(p.root).as_posix() for f in
                 (p.root / "deliverables").glob("*/sections/*") if f.is_file() and f.stat().st_mtime > last]
        if newer:
            warns.append(f"sections changed after the last verification report: {', '.join(newer[:5])}"
                         f"{', ...' if len(newer) > 5 else ''} (verifier on the changes: sb review-edits)")
    if not any("referee" in r.name for r in reviews):
        warns.append("no referee report in reviews/")
    for f in files:
        rel = f.relative_to(p.root).as_posix()
        if f.stat().st_size > MAX_FILE_MB * 1e6:
            errs.append(f"{rel}: larger than {MAX_FILE_MB} MB -- belongs in dist/data, not git")
        if f.suffix in {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".csv", ".cff"}:
            text = f.read_text(encoding="utf-8", errors="replace")
            if SECRET_RX.search(text):
                errs.append(f"{rel}: looks like it contains a secret")
            if f.suffix in {".py", ".md"} and re.search(r"\b(TODO|FIXME|XXX)\b", text):
                warns.append(f"{rel}: contains TODO/FIXME")
    return errs, warns


def build(project: config.Project | None = None) -> dict:
    p = project or config.project()
    h = config.hub()
    pub = p.meta.get("publish", {}) or {}
    dist = p.root / "dist"
    out, data_out = dist / "public", dist / "data"
    report: dict = {"errors": [], "warnings": [], "files": [], "data": []}

    files = [f for f in _collect(p.root, pub.get("include", [])) if not _excluded(f.relative_to(p.root).as_posix())]
    pdf = p.root / pub.get("pdf", f"deliverables/{p.slug}.pdf")
    written = [d for d in deliverable.folders(p, markdown=True) if deliverable.is_markdown(d)]
    if not pdf.exists() and written:
        report["warnings"].append("no PDF: the Markdown deliverable is published as text with the numbers filled in; "
                                  "citations appear as [@key]")
    elif not pdf.exists():
        report["errors"].append(f"deliverable PDF missing: {pdf.relative_to(p.root)} (sb build; needs LaTeX)")
    else:
        newest_src = max((f.stat().st_mtime for f in (p.root / "deliverables").rglob("*.tex")), default=0)
        if newest_src > pdf.stat().st_mtime:
            report["warnings"].append("PDF is older than its .tex sources -- rebuild")
    e, w = gates(p, files)
    report["errors"] += e
    report["warnings"] += w

    # ---- assemble dist/public (keep its .git) ----
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    for f in files:
        dest = out / f.relative_to(p.root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        report["files"].append(f.relative_to(p.root).as_posix())
    # results.record needs a project card; only its public part leaves the machine
    card = {k: p.meta[k] for k in ("slug", "title", "lang", "created", "reads", "owns") if k in p.meta}
    (out / "project.yaml").write_text("# Project card (public part)\n" + yaml.safe_dump(card, sort_keys=False, allow_unicode=True),
                                      encoding="utf-8")
    for f in (p.root / "public").glob("*"):
        if f.is_file():
            shutil.copy2(f, out / f.name)
    if pdf.exists():
        shutil.copy2(pdf, out / f"{p.slug}.pdf")
    else:
        for d in written:
            name = p.slug if d.name == "paper" else f"{p.slug}_{d.name}"
            (out / f"{name}.md").write_text(handover.rendered(p, d), encoding="utf-8")
    pkg = Path(__file__).resolve().parent
    shutil.copytree(pkg, out / "src" / "sourcebound", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "uv.lock"):                    # uv.lock pins the environment
        if ((config.home() or h.root) / name).exists():
            shutil.copy2((config.home() or h.root) / name, out / name)
    (out / ".gitignore").write_text("data/*.parquet\n.venv/\n__pycache__/\n", encoding="utf-8")

    # ---- data: Parquet + datapackage.json outside git, manifest inside ----
    tables = pub.get("data", []) or []
    base_url = (pub.get("data_url") or "").rstrip("/")
    resources, manifest = [], []
    if tables:
        data_out.mkdir(parents=True, exist_ok=True)
    for t in tables:
        c = contracts.find(t, hub_root=h.root, registry=h.registry, project_root=p.root)
        if c is None:
            report["errors"].append(f"data {t}: no contract -- cannot publish undocumented data")
            continue
        if not c.license.strip():
            report["errors"].append(f"data {t}: the contract states no licence -- clarify it before publishing the table")
            continue
        if c.license.lower().startswith(("restricted", "proprietary", "no redistribution")):
            report["errors"].append(f"data {t}: license '{c.license}' forbids redistribution")
            continue
        path = lake.export(t, data_out / f"{t}.parquet")
        sha, rows = _sha(path), len(lake.read(t))
        resources.append(c.datapackage_resource(path.name, sha, rows))
        manifest.append({"table": t, "file": path.name, "sha256": sha, "rows": rows,
                         "snapshot": lake.READS.get(t), "url": f"{base_url}/{path.name}" if base_url else None})
        report["data"].append(t)
    if tables:
        (data_out / "datapackage.json").write_text(json.dumps({
            "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
            "name": p.slug.replace("_", "-"), "title": p.title, "resources": resources}, indent=2), encoding="utf-8")
        (out / "data").mkdir(exist_ok=True)
        (out / "data" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (out / "data" / "README.md").write_text(
            "# Data\n\nThe tables are not stored in git. Download them into this folder "
            "(file names as below) and verify the sha256; the analysis scripts then read "
            "`data/<schema>.<table>.parquet` automatically.\n\n| Table | File | Rows | sha256 | URL |\n"
            "| --- | --- | --- | --- | --- |\n" + "".join(
                f"| {m['table']} | {m['file']} | {m['rows']} | `{m['sha256'][:16]}` | {m['url'] or 'tbd'} |\n"
                for m in manifest), encoding="utf-8")
        if not base_url:
            report["warnings"].append("publish.data_url empty: upload dist/data (Zenodo/R2) and set it")
    leftovers = [f.relative_to(out).as_posix() for f in out.rglob("*") if f.is_file()
                 and ".git/" not in f.relative_to(out).as_posix() and _excluded(f.relative_to(out).as_posix())]
    if leftovers:
        report["errors"].append(f"forbidden files in bundle: {leftovers[:5]}")
    return report


def push(project: config.Project | None = None, message: str = "Release") -> str:
    p = project or config.project()
    h = config.hub()
    out = p.root / "dist" / "public"
    repo = (p.meta.get("publish", {}) or {}).get("repo") or p.slug.replace("_", "-")
    full = f"{h.github_owner}/{repo}"
    vis = "--" + (p.meta.get("publish", {}) or {}).get("visibility", "private")
    run = lambda *a: subprocess.run(a, cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not (out / ".git").exists():
        run("git", "init", "-b", "main")
    run("git", "add", "-A")
    run("git", "commit", "-m", message)
    if run("gh", "repo", "view", full).returncode != 0:
        r = run("gh", "repo", "create", full, vis, "--source", ".", "--push")
    else:
        if run("git", "remote", "get-url", "origin").returncode != 0:
            run("git", "remote", "add", "origin", f"https://github.com/{full}.git")
        r = run("git", "push", "-u", "origin", "main")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return f"https://github.com/{full}"
