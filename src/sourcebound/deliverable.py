"""Deliverable folders: self-contained LaTeX that people and agents edit side by side.

    deliverables/<name>/
      main.tex              preamble + \\input{sections/NN_*.tex}      people and agents
      sections/*.tex        the prose                                  people and agents
      generated/            results.tex, tables/, figures/, tikz/      `sb sync` only
      references.bib        exactly the cited keys                     `sb bib sync` only
      *.cls, *.sty          the style files the preamble uses          `sb sync` / the template

The folder has no paths that leave it, so it compiles on its own, on Overleaf, and as a git
repository of its own.  Generated files are never edited by hand; section files are never
regenerated wholesale once a person has touched them (`sb review-edits`).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import config

STYLE_SUFFIXES = {".cls", ".sty", ".bst", ".bbx", ".cbx", ".def", ".lco"}
AGENT_TRAILER = "Co-Authored-By:"
# project folder -> folder inside generated/ (patterns are copied flat)
MIRROR = [("results", ["results.tex"], ""), ("tables", ["*.tex"], "tables"),
          ("figures", ["*.pdf", "*.png"], "figures"), ("figures/tikz", ["*.tex"], "tikz")]


def main_tex(folder: Path) -> Path | None:
    """The document of a deliverable folder: main.tex, else the one file with \\documentclass."""
    if (folder / "main.tex").exists():
        return folder / "main.tex"
    for f in sorted(folder.glob("*.tex")):
        if "\\documentclass" in f.read_text(encoding="utf-8", errors="replace"):
            return f
    return None


def is_markdown(folder: Path) -> bool:
    """A deliverable written in Markdown: sections/*.md and no LaTeX document."""
    return main_tex(folder) is None and any((folder / "sections").glob("*.md"))


def folders(project: config.Project, *, markdown: bool = False) -> list[Path]:
    """Deliverable folders: the LaTeX ones, with `markdown=True` also those written in Markdown."""
    base = project.root / "deliverables"
    return [d for d in sorted(base.iterdir())
            if d.is_dir() and (main_tex(d) or (markdown and is_markdown(d)))] if base.is_dir() else []


def tex_tools() -> dict[str, bool]:
    """Which LaTeX tools are installed. None is required: without them only the PDF is not built."""
    return {t: shutil.which(t) is not None for t in ("latexmk", "pdflatex", "latexpand")}


def build(project: config.Project | None = None) -> dict[str, str]:
    """`sb sync`, then compile every LaTeX deliverable if LaTeX is installed.

    Returns {folder: outcome}; a missing TeX installation is an outcome, not an error.
    """
    p = project or config.project()
    sync(p)
    report: dict[str, str] = {}
    for d in folders(p):
        name = d.relative_to(p.root).as_posix()
        if not tex_tools()["latexmk"]:
            report[name] = "not built: LaTeX (latexmk) is not installed; `sb handover` works without it"
            continue
        main = main_tex(d)
        mode = [] if (d / "latexmkrc").exists() or (d / ".latexmkrc").exists() else ["-pdf"]   # latexmk's default is DVI
        r = subprocess.run(["latexmk", "-silent", *mode, main.name], cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            log = main.with_suffix(".log")
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
            hits = [ln for ln in lines if ln.startswith("!") or ":" in ln and "error" in ln.lower()][:8]
            raise RuntimeError(f"{name}: LaTeX failed\n  " + "\n  ".join(hits or (r.stdout + r.stderr).splitlines()[-8:]))
        pdf = main.with_suffix(".pdf")
        if pdf.exists():
            want = next((x.get("pdf") for x in p.meta.get("deliverables", []) or []
                         if x.get("path") == main.relative_to(p.root).as_posix()), None)
            dest = p.root / (want or f"deliverables/{p.slug if d.name == 'paper' else p.slug + '_' + d.name}.pdf")
            shutil.copy2(pdf, dest)
            report[name] = f"built {dest.relative_to(p.root)}"
        else:
            report[name] = "built"
    for d in folders(p, markdown=True):
        if is_markdown(d):
            report[d.relative_to(p.root).as_posix()] = "Markdown: nothing to compile; `sb handover` exports it"
    return report


STANDALONE = """\\documentclass[10pt, tikz, border=1pt]{standalone}
\\usepackage[T1]{fontenc}
\\usepackage{amsmath}
\\usepackage{newtxtext, newtxmath}
\\usepackage{sbtikz}
%s\\begin{document}
\\input{%s}
\\end{document}
"""


def diagrams(project: config.Project | None = None) -> dict[str, str]:
    """Standalone PDFs of the TikZ diagrams: figures/tikz/<name>.tex -> figures/tikz/<name>.pdf.

    For renderers other than LaTeX (`sb handover`).  Built only when LaTeX is installed and the
    source is newer than the PDF; a PDF built earlier (and committed) is used as it is.
    Returns {name: outcome}.
    """
    import os
    import tempfile
    p = project or config.project()
    h = config.hub(p.root, required=False)
    latex = ((config.home() or h.root) / "latex") if (config.home() or h) else None
    res = p.root / "results" / "results.tex"
    report: dict[str, str] = {}
    for src in sorted((p.root / "figures" / "tikz").glob("*.tex")):
        code = src.read_text(encoding="utf-8", errors="replace")
        if "\\begin{tikzpicture}" not in code:
            continue
        plots = "\\usepackage{pgfplots}\n\\pgfplotsset{compat=1.18}\n" if re.search(r"\\begin\{(?:semilog[xy]|loglog)?axis\}|\\addplot", code) else ""
        pdf = src.with_suffix(".pdf")
        if pdf.exists() and pdf.stat().st_mtime >= src.stat().st_mtime:
            report[src.stem] = "up to date"
        elif not tex_tools()["pdflatex"]:
            report[src.stem] = "kept the older PDF (LaTeX is not installed)" if pdf.exists() else "no PDF: LaTeX is not installed"
        else:
            with tempfile.TemporaryDirectory() as tmp:
                # files by name, found through TEXINPUTS: no absolute path inside a .tex file, so a TeX
                # that sees the disk under other names (TeX Live in WSL, a container) reads them too
                extra = plots + ("\\usepackage{sbresults}\n\\sbresults{%s}\n" % res.name if res.exists() else "")
                main = Path(tmp) / "sb-standalone-diagram.tex"
                main.write_text(STANDALONE % (extra, src.name), encoding="utf-8")
                search = [str(x) for x in (latex, src.parent, res.parent if res.exists() else None) if x]
                env = {**os.environ, "TEXINPUTS": os.pathsep.join(search) + os.pathsep}
                r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", main.name],
                                   cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode == 0 and main.with_suffix(".pdf").exists():
                    shutil.copy2(main.with_suffix(".pdf"), pdf)
                    report[src.stem] = "built"
                else:
                    err = next((ln for ln in r.stdout.splitlines() if ln.startswith("!")), "pdflatex failed")
                    report[src.stem] = f"no PDF: {err}"
    return report


def to_markdown(folder: Path) -> None:
    """Turn a LaTeX deliverable folder into one written in Markdown (sections/*.md only)."""
    from . import handover
    _, files = handover._sections(folder)
    texts = [(f.stem, handover.to_markdown(f.read_text(encoding="utf-8"))[0]) for f, _ in files]
    for f in sorted(folder.rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    (folder / "sections").mkdir()
    for stem, text in texts:
        (folder / "sections" / f"{stem}.md").write_text(text, encoding="utf-8")


def _copy(src: Path, dest: Path) -> bool:
    """Copy when the content differs (unchanged files keep their time stamp, so latexmk rests)."""
    if dest.exists() and dest.read_bytes() == src.read_bytes():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def sync(project: config.Project | None = None) -> dict[str, list[str]]:
    """Mirror results, tables, figures and diagrams into every deliverable's generated/ folder
    and copy the Sourcebound style files its preamble uses.  Returns {folder: changed files}."""
    p = project or config.project()
    h = config.hub(p.root, required=False)
    latex = ((config.home() or h.root) / "latex") if (config.home() or h) else None
    report: dict[str, list[str]] = {}
    for d in folders(p):
        main = main_tex(d)
        text = main.read_text(encoding="utf-8", errors="replace")
        if "generated/" not in text:
            continue                                # older layout with ../../ paths: leave it alone
        changed: list[str] = []
        gen = d / "generated"
        for src_dir, patterns, sub in MIRROR:
            wanted = {f.name: f for pat in patterns for f in (p.root / src_dir).glob(pat)}
            target = gen / sub if sub else gen
            for name, f in sorted(wanted.items()):
                if _copy(f, target / name):
                    changed.append((target / name).relative_to(d).as_posix())
            if sub and target.is_dir():             # drop what the project no longer produces
                for old in target.iterdir():
                    if old.is_file() and old.name not in wanted:
                        old.unlink()
                        changed.append(f"-{old.relative_to(d).as_posix()}")
        preamble = text.split("\\begin{document}")[0]
        for f in sorted(latex.glob("*")) if latex and latex.is_dir() else []:
            if f.suffix in STYLE_SUFFIXES and re.search(r"\{[^}]*\b%s\b[^}]*\}" % re.escape(f.stem), preamble):
                if _copy(f, d / f.name):
                    changed.append(f.name)
        report[d.relative_to(p.root).as_posix()] = changed
    return report


def flatten(project: config.Project | None = None) -> list[Path]:
    """One .tex file per deliverable (latexpand), for journals that want a single file."""
    p = project or config.project()
    if not tex_tools()["latexpand"]:
        raise RuntimeError("latexpand not found (it ships with TeX Live: tlmgr install latexpand)")
    out = []
    for d in folders(p):
        main = main_tex(d)
        flat = d / f"{p.slug}_flat.tex"
        r = subprocess.run(["latexpand", main.name, "-o", flat.name], cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "latexpand failed")
        out.append(flat)
    return out


# ---------------------------------------------------------------------------- templates
def resolve_template(name_or_path: str, h: config.Hub) -> Path:
    """A LaTeX template folder: a name from [templates.latex] in the configuration, or a path."""
    known = dict(h.latex_templates)
    folder = Path(known.get(name_or_path, name_or_path)).expanduser()
    if not folder.is_dir() or main_tex(folder) is None:
        names = ", ".join(sorted(known)) or "none configured"
        raise FileNotFoundError(f"LaTeX template {name_or_path!r}: no folder with a .tex document at {folder} "
                                f"(names in [templates.latex]: {names})")
    return folder.resolve()


def adopt(folder: Path, template: Path, title: str) -> None:
    """Use `template`'s preamble and style files for the deliverable in `folder`.

    Sections and the document body stay as they are; the preamble gains the lines that connect
    it to recorded results and generated figures.
    """
    tmain = main_tex(template)
    pre = tmain.read_text(encoding="utf-8").split("\\begin{document}")[0]
    ours = (folder / "main.tex").read_text(encoding="utf-8")
    head = ours.split("\\DocumentMetadata")[0] if "\\DocumentMetadata" in ours else ""
    body = "\\begin{document}" + ours.split("\\begin{document}", 1)[1]
    pre = re.sub(r"\A(?:%[^\n]*\n)+", "", pre)                       # the template's own header comment
    wiring = []
    if not re.search(r"\\usepackage(\[[^]]*\])?\{[^}]*results\}", pre):
        wiring += ["\\usepackage{sbresults}", "\\sbresults{generated/results.tex}"]
    if "tikz}" not in pre:
        wiring.append("\\usepackage{sbtikz}")
    if "\\graphicspath" not in pre:
        wiring.append("\\graphicspath{{generated/figures/}}")
    pre = re.sub(r"(?m)^(\\documentclass.*)$", lambda m: m.group(1) + "\n" + "\n".join(wiring), pre, count=1)
    pre = re.sub(r"(?m)^\\title\{.*\}\s*$", lambda m: "\\title{%s}" % title, pre, count=1)
    (folder / "main.tex").write_text(head + pre.rstrip() + "\n\n" + body, encoding="utf-8")
    for f in sorted(template.iterdir()):
        if f.is_file() and f.suffix in STYLE_SUFFIXES:
            shutil.copy2(f, folder / f.name)
    for f in folder.glob("sbpaper.cls"):                             # the built-in class is not used
        f.unlink()


# ---------------------------------------------------------------------------- review of edits
def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


_REFS = re.compile(r"\\(?:result\*?|[a-zA-Z]*cite[a-zA-Z]*|[cC]?ref|label|input|includegraphics|eqref|autoref)"
                   r"(?:\[[^]]*\])*\{[^}]*\}")
_NUMBER = re.compile(r"(?<![\w.])\d+[.,]\d+|\d+(?:\\,|\s)?\\%")


_LAYOUT = re.compile(r"\\[a-zA-Z]+(?:\[[^]]*\])?\{[^{}]*\}|\d+(?:[.,]\d+)?\s*(?:\\(?:line|text|column)width|\\baselineskip|em|ex|pt|cm|mm)\b")
_LEVELS = {"1", "5", "10", "90", "95", "99"}
_MD_NUMBER = re.compile(r"(?<![\w.])\d+[.,]\d+|\d+\s?%")
_MD_REFS = re.compile(r"\{\{[^}]*\}\}|\]\([^)]*\)|<[^>]*>|`[^`]*`")


def typed_numbers(text: str, *, markdown: bool = False) -> list[tuple[int, str]]:
    """Lines of a section that hold a decimal number or a percentage typed by hand
    (numbers belong in results: `\\result{key}` / `{{result:key}}`).  [(line number, line)]

    Conventional test and confidence levels (1, 5, 10, 90, 95, 99 per cent) are not reported.
    """
    out = []
    for n, ln in enumerate(text.split("\n"), 1):
        if markdown:
            hits = _MD_NUMBER.findall(_MD_REFS.sub("", ln))
        else:
            ln_ = re.sub(r"(?<!\\)%.*$", "", ln)
            hits = _NUMBER.findall(_LAYOUT.sub("", _REFS.sub("", ln_)))
        if [h for h in hits if re.match(r"[\d.,]+", h).group().rstrip(".,") not in _LEVELS]:
            out.append((n, ln.strip()))
    return out


def review(project: config.Project | None = None, since: str | None = None) -> dict:
    """Section files changed since the last agent commit (or `since`), with what needs checking.

    Agents commit their edits with a `Co-Authored-By:` trailer; everything after the last such
    commit, committed or not, counts as edited by a person.
    """
    p = project or config.project()
    try:
        _git(p.root, "rev-parse", "--is-inside-work-tree")
    except (RuntimeError, FileNotFoundError):
        raise RuntimeError(f"{p.root} is not a git repository (git init, then commit after every agent task)")
    if since is None:
        since = _git(p.root, "log", "-1", "--format=%H", f"--grep=^{AGENT_TRAILER}", "--", "deliverables").strip()
        if not since:                               # no agent commit yet: measure from the first commit
            since = _git(p.root, "rev-list", "--max-parents=0", "HEAD").split("\n")[0].strip()
    names = set(_git(p.root, "diff", "--name-only", since, "--", "deliverables").split("\n"))
    names |= set(_git(p.root, "ls-files", "-o", "--exclude-standard", "--", "deliverables").split("\n"))
    files = {}
    from .handover import MD_CITE, MD_RESULT
    for name in sorted(n for n in names if n.endswith((".tex", ".md")) and "/generated/" not in n):
        f = p.root / name
        if not f.exists():
            files[name] = {"deleted": True}
            continue
        diff = _git(p.root, "diff", "-U0", since, "--", name)
        added = ([ln[1:] for ln in diff.split("\n") if ln.startswith("+") and not ln.startswith("+++")]
                 if diff else f.read_text(encoding="utf-8").split("\n"))
        added = [ln for ln in added if ln.strip() and not ln.lstrip().startswith("%")]
        text = "\n".join(added)
        if name.endswith(".md"):
            files[name] = {"added_lines": len(added), "cites": sorted(set(MD_CITE.findall(text))),
                           "results": sorted(set(MD_RESULT.findall(text))),
                           "typed_numbers": [ln for _, ln in typed_numbers(text, markdown=True)]}
            continue
        files[name] = {
            "added_lines": len(added),
            "cites": sorted(set(k.strip() for m in re.findall(r"\\[a-zA-Z]*cite[a-zA-Z]*(?:\[[^]]*\])*\{([^}]*)\}", text)
                                for k in m.split(","))),
            "results": sorted(set(re.findall(r"\\result\*?\{([^}]+)\}", text))),
            "typed_numbers": [ln for _, ln in typed_numbers(text)],
        }
    return {"since": since, "files": files}
