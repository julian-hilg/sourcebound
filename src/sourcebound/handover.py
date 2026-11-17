"""Format-neutral handover: what any renderer needs from a project, without LaTeX.

    sb handover   ->   dist/handover/
      handover.json            metadata, section order, what is used, what is missing
      <deliverable>/*.md       the prose as Markdown (see README.md there for the notation)
      results.json             recorded results (value, display, unit, provenance)
      tables/*.csv             tables (exact values; *.display.csv: the cells as printed)
      figures/*                figures and diagrams (PDF/PNG)
      references.bib           cited sources     evidence/*.yaml  claims ledger, web sources

Sourcebound itself renders LaTeX only.  Word, HTML, slides or posts are produced elsewhere
from this folder; the frontend reads it too.  Notation in the Markdown files:

    {{result:key}}     a recorded number        [@key; @other, p. 3]  citations (pandoc style)
    {{table:name}}     tables/name.csv          ![caption](figures/name.pdf){#label}
    {{ref:label}}      a cross-reference        (TikZ diagrams are standalone PDFs in figures/)
    $...$, $$...$$     mathematics in LaTeX notation

Sections written in LaTeX are converted for the constructs of the house style; commands the
converter does not know are left in place and listed under "unconverted" (nothing is dropped).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config, deliverable, results
from .zotero import strip_comments

FORMAT = {"format": "sourcebound-handover", "version": 1}
MD_RESULT = re.compile(r"\{\{result:([^}]+)\}\}")
MD_CITE = re.compile(r"(?<![\w@])@([A-Za-z][\w:.-]*[\w])")
_MATH = re.compile(r"(?s)\$\$.*?\$\$|(?<!\\)\$[^$]*?(?<!\\)\$|`[^`\n]*`")


# ------------------------------------------------------------------ LaTeX -> Markdown
def _group(s: str, i: int, open_: str = "{", close: str = "}") -> tuple[str, int] | None:
    """Balanced group starting at s[i]; returns (inner text, index after it)."""
    if i >= len(s) or s[i] != open_:
        return None
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "\\":
            continue
        if s[j] == open_ and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == close and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None


def _commands(s: str, names: str, fn, nargs: int = 1) -> str:
    """Replace \\name[opt]...{arg}... (balanced braces) by fn(name, [opts], [args])."""
    rx = re.compile(r"\\(%s)\*?(?![a-zA-Z])" % names)
    pos, out = 0, []
    while (m := rx.search(s, pos)):
        i, opts, args = m.end(), [], []
        while (g := _group(s, i, "[", "]")):
            opts.append(g[0])
            i = g[1]
        for _ in range(nargs):
            g = _group(s, i)
            if g is None:
                break
            args.append(g[0])
            i = g[1]
        if len(args) < nargs:                       # not the form we know: leave it
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        out.append(s[pos:m.start()] + fn(m.group(1), opts, args))
        pos = i
    return "".join(out) + s[pos:]


def _cite(name: str, opts: list[str], args: list[str]) -> str:
    keys = [k.strip() for k in args[0].split(",") if k.strip()]
    post = f", {opts[-1]}" if opts and opts[-1] else ""
    if name.lower().startswith("textcite") and len(keys) == 1:
        return f"@{keys[0]}" + (f" [{opts[-1]}]" if post else "")
    return "[" + "; ".join(f"@{k}" for k in keys) + post + "]"


def _float(kind: str, body: str) -> str:
    """A figure or table environment -> one Markdown block."""
    found: dict[str, str] = {}

    def take(name, opts, args):
        found[name] = args[0].strip()
        return ""
    body = _commands(body, "caption|label|tablenote|includegraphics|input", take)
    body = _layout(body).strip()
    caption, label = re.sub(r"\s+", " ", found.get("caption", "")), found.get("label", "")
    anchor = f"{{#{label}}}" if label else ""
    src = found.get("input", "")
    if "includegraphics" in found:
        block = f"![{caption}](figures/{Path(found['includegraphics']).name}){anchor}"
    elif "/tikz/" in src:
        block = f"![{caption}](figures/{Path(src).stem}.pdf){anchor}"
    elif src:
        block = f"{{{{table:{Path(src).stem}}}}}\n\n: {caption} {anchor}".rstrip()
    else:
        block = f": {caption} {anchor}".rstrip() if caption or anchor else ""
    note = f"\n\n*{re.sub(r'\s+', ' ', _layout(found['tablenote'])).strip()}*" if found.get("tablenote") else ""
    return "\n\n" + block + ("\n\n" + body if body else "") + note + "\n\n"


# Commands that only set size, spacing or alignment: the text stays, the command goes.
_DECLARATIONS = ("tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge|raggedright|raggedleft|"
                 "centering|arraybackslash|normalfont|rmfamily|sffamily|ttfamily|upshape|mdseries|selectfont")
_SHAPES = {"bfseries": "**{}**", "itshape": "*{}*", "em": "*{}*", "slshape": "*{}*"}
# Commands without arguments: a group after one of them is not its argument (\par{\small x}).
_NO_ARGS = re.compile(r"par|smallskip|medskip|bigskip|noindent|newline|linebreak|indent|%s|%s"
                      % (_DECLARATIONS, "|".join(_SHAPES)))


def _layout(s: str) -> str:
    """Drop layout commands: {\\small text} -> text, {\\bfseries text} -> **text**, \\vspace{3pt} -> nothing."""
    rx = re.compile(r"\{\s*\\(%s|%s)(?![a-zA-Z])\s*" % (_DECLARATIONS, "|".join(_SHAPES)))
    for _ in range(4):                              # nested groups
        pos, out = 0, []
        while (m := rx.search(s, pos)):
            g = _group(s, m.start())
            if g is None:
                out.append(s[pos:m.end()])
                pos = m.end()
                continue
            inner = g[0][m.end() - m.start() - 1:].strip()
            before = re.search(r"(?:\\([a-zA-Z]+)\*?|[}\]])\s*$", s[:m.start()])
            if before and not (before.group(1) and _NO_ARGS.fullmatch(before.group(1))):
                inner = "{" + inner + "}"                 # an argument, \textbf{\large x}: keep its braces
            elif m.group(1) in _SHAPES and inner:
                inner = _SHAPES[m.group(1)].format(inner)
            out.append(s[pos:m.start()] + inner)
            pos = g[1]
        s = "".join(out) + s[pos:]
    s = _commands(s, "vspace|hspace|addvspace|vskip|hskip", lambda n, o, a: "")
    s = re.sub(r"\\(?:%s|%s)(?![a-zA-Z])\s*" % (_DECLARATIONS, "|".join(_SHAPES)), "", s)
    return re.sub(r"\\(?:smallskip|medskip|bigskip|noindent)(?![a-zA-Z])\s*", "", s)


def _list(kind: str, body: str) -> str:
    items = [x.strip() for x in re.split(r"\\item\b", body)[1:]]
    mark = (lambda n: f"{n}.") if kind == "enumerate" else (lambda n: "-")
    return "\n\n" + "\n".join(f"{mark(n)} " + re.sub(r"\s*\n\s*", " ", it) for n, it in enumerate(items, 1)) + "\n\n"


def _description(kind: str, body: str) -> str:
    out = []
    for it in re.split(r"\\item\b", body)[1:]:
        g = _group(it.lstrip(), 0, "[", "]")
        term, rest = (g[0].strip(), it.lstrip()[g[1]:]) if g else ("", it)
        out.append("- " + (f"**{term}** " if term else "") + re.sub(r"\s*\n\s*", " ", rest.strip()))
    return "\n\n" + "\n".join(out) + "\n\n"


# Table environments and how many {arguments} come before the rows (tabularx: width and columns).
_TABULARS = {"tabular": 1, "tabular*": 2, "tabularx": 2, "tabulary": 2, "longtable": 1, "xltabular": 2}


def _tabulars(s: str, keep) -> str:
    """A table written out in a section -> a pipe table (the first row is the header)."""
    rx = re.compile(r"\\begin\{(%s)\}" % "|".join(re.escape(k) for k in _TABULARS))
    pos, out = 0, []
    while (m := rx.search(s, pos)):
        env, i = m.group(1), m.end()
        while (g := _group(s, i, "[", "]")):        # position, e.g. tabular[t]
            i = g[1]
        for _ in range(_TABULARS[env]):
            g = _group(s, i)
            if g is None:
                break
            i = g[1]
        end = s.find("\\end{%s}" % env, i)
        if g is None or end == -1:
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        body = re.sub(r"\\(?:toprule|midrule|bottomrule|hline|endhead|endfirsthead|endfoot|endlastfoot)(?![a-zA-Z])"
                      r"|\\(?:cmidrule|cline)(?:\([^)]*\))?\{[^}]*\}", "", s[i:end])
        # a line break inside a cell (\par, \newline) must not end the Markdown row
        body = re.sub(r"\\(?:par|newline|linebreak)(?![a-zA-Z])", " ", _layout(body))
        rows = [[re.sub(r"\s+", " ", c).strip().replace("|", "\\|") for c in re.split(r"(?<!\\)&", r)]
                for r in re.split(r"\\\\(?:\[[^\]]*\])?", body) if r.strip()]
        table = ""
        if rows:
            width = max(len(r) for r in rows)
            line = lambda r: "| " + " | ".join(r + [""] * (width - len(r))) + " |"
            table = "\n".join([line(rows[0]), keep("|" + " --- |" * width), *map(line, rows[1:])])
        out.append(s[pos:m.start()] + "\n\n" + table + "\n\n")
        pos = end + len("\\end{%s}" % env)
    return "".join(out) + s[pos:]


_NOT_TEXT = re.compile(r"tikz|pgf|axis|scope|lstlisting|verbatim|minted|tabular|array|matrix|cases|split")


def _boxes(s: str) -> str:
    """A text environment of the deliverable's own (a note box, \\begin{hinweis}{Title} ... \\end{hinweis})
    -> a quote block with the title in bold. Drawings and code stay as written (and are reported)."""
    rx = re.compile(r"\\begin\{([a-zA-Z]+)\}")
    pos, out = 0, []
    while (m := rx.search(s, pos)):
        name = m.group(1)
        end = s.find("\\end{%s}" % name, m.end())
        if _NOT_TEXT.search(name) or end == -1:
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        i, title = m.end(), ""
        while (g := _group(s, i, "[", "]")):
            i = g[1]
        if (g := _group(s, i)):
            title, i = g[0].strip(), g[1]
        body = _boxes(s[i:end]).strip()
        body = re.sub(r"\n\s*\n(\s*\n)+", "\n\n", body)
        lines = ([f"**{title}**", ""] if title else []) + body.splitlines()
        out.append(s[pos:m.start()] + "\n\n" + "\n".join(("> " + ln).rstrip() for ln in lines) + "\n\n")
        pos = end + len("\\end{%s}" % name)
    return "".join(out) + s[pos:]


def macros(preamble: str) -> dict[str, tuple[int, str]]:
    """Macros a deliverable defines for itself: \\newcommand\\name[n]{body}, without optional arguments."""
    pre, out = strip_comments(preamble), {}
    for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([a-zA-Z]+)\}?\s*(?:\[(\d)\])?\s*(?=\{)", pre):
        g = _group(pre, m.end())
        if g is not None:
            out[m.group(1)] = (int(m.group(2) or 0), g[0])
    return out


def _expand(s: str, defs: dict[str, tuple[int, str]]) -> str:
    for _ in range(3):                              # a macro may use another one
        for name, (n, body) in defs.items():
            if n:
                s = _commands(s, re.escape(name), lambda _n, _o, a, body=body: re.sub(
                    r"#(\d)", lambda m: a[int(m.group(1)) - 1], body), nargs=n)
            else:
                s = re.sub(r"\\%s(?![a-zA-Z])" % re.escape(name), lambda m, body=body: body, s)
    return s


def to_markdown(tex: str, defs: dict[str, tuple[int, str]] | None = None) -> tuple[str, list[str]]:
    """Markdown for a section written in the LaTeX house style, plus the commands left over.

    `defs` are the deliverable's own macros (see `macros`); they are expanded first.
    """
    held: list[str] = []                            # code and mathematics stay as they are

    def keep(text: str) -> str:
        held.append(text)
        return f"\0{len(held) - 1}\0"
    s = re.sub(r"(?s)\\begin\{(lstlisting|verbatim)\}(?:\[[^\]]*\])?\n?(.*?)\\end\{\1\}",
               lambda m: "\n\n" + keep("```\n" + m.group(2).rstrip() + "\n```") + "\n\n", tex)
    s = _expand(strip_comments(s), defs or {})
    for env, fn in (("figure", _float), ("table", _float), ("itemize", _list), ("enumerate", _list),
                    ("description", _description)):
        s = re.sub(r"(?s)\\begin\{(%s)\*?\}(?:\[[^\]]*\])?(.*?)\\end\{\1\*?\}" % env,
                   lambda m, fn=fn: fn(m.group(1), m.group(2)), s)
    s = _layout(_tabulars(s, keep))
    s = re.sub(r"(?s)\\begin\{(?:center|flushleft|flushright|minipage)\}(?:\[[^\]]*\])*(?:\{[^}]*\})?|\\end\{(?:center|flushleft|flushright|minipage)\}", "", s)
    s = re.sub(r"(?s)\\begin\{abstract\}(.*?)\\end\{abstract\}", lambda m: "# Abstract\n\n" + m.group(1).strip() + "\n", s)
    s = re.sub(r"(?s)\\begin\{(?:equation|align|gather)\*?\}(.*?)\\end\{(?:equation|align|gather)\*?\}",
               lambda m: "\n\n$$" + m.group(1).strip() + "$$\n\n", s)
    s = re.sub(r"(?s)\\\[(.*?)\\\]", lambda m: "\n\n$$" + m.group(1).strip() + "$$\n\n", s)
    s = _boxes(s)
    s = _commands(s, "result", lambda n, o, a: "{{result:%s}}" % a[0].strip())
    s = s.replace("``", "\u201c")                   # an opening quote, not an empty code span
    s = _MATH.sub(lambda m: keep(m.group(0)), s)
    level = {"section": "#", "subsection": "##", "subsubsection": "###"}

    def heading(m):
        lab = re.match(r"\s*\\label\{([^}]*)\}", s[m.end():])
        return f"\n{level[m.group(1)]} {m.group(2).strip()}" + (f" {{#{lab.group(1)}}}" if lab else "") + "\n"
    s = re.sub(r"\\(section|subsection|subsubsection)\*?\{([^{}]*)\}", heading, s)
    s = re.sub(r"(?m)^(#+ .*\{#([^}]*)\}\n)\s*\\label\{\2\}", r"\1", s)
    s = _commands(s, "[a-zA-Z]*cite[a-zA-Z]*", _cite)
    s = _commands(s, "[cC]ref|ref|autoref|eqref|pageref", lambda n, o, a: "{{ref:%s}}" % a[0].strip())
    s = _commands(s, "href", lambda n, o, a: f"[{a[1]}]({a[0]})", nargs=2)
    wrap = {"emph": "*{}*", "textit": "*{}*", "textbf": "**{}**", "texttt": "`{}`", "url": "<{}>",
            "enquote": "\u201c{}\u201d", "footnote": "^[{}]", "paragraph": "**{}.**", "textsc": "{}", "mbox": "{}"}
    for _ in range(3):                              # nested markup
        s = _commands(s, "|".join(wrap), lambda n, o, a: wrap[n].format(
            a[0].strip().rstrip(".") if n == "paragraph" else a[0].strip()))
    s = re.sub(r"\\label\{[^}]*\}", "", s)
    for a, b in (("\\-", ""), ("\\texttimes", "×"), ("\\textendash", "–"), ("\\textemdash", "—"),
                 ("\\LaTeX", "LaTeX"), ("\\TeX", "TeX"), ("\\ldots", "\u2026"), ("\\dots", "\u2026"), ("\\,", "\u202f"), ("\\%", "%"), ("\\&", "&"), ("\\_", "_"), ("\\#", "#"), ("\\$", "$"),
                 ("\\ ", " "), ("\\@", ""), ("~", "\u00a0"), ("---", "\u2014"), ("--", "\u2013"),
                 ("``", "\u201c"), ("''", "\u201d"), ("\\\\", "  \n"), ("\\par", "\n\n"),
                 ("\\noindent", ""), ("\\clearpage", ""), ("\\newpage", ""), ("\\medskip", ""),
                 ("\\smallskip", ""), ("\\bigskip", ""), ("\\centering", "")):
        s = s.replace(a, b)
    s = re.sub(r"(?<![\\{])\{\}", "", s)              # \texttimes{}, \LaTeX{}: the empty group ends a command
    left = sorted(set(re.findall(r"\\[a-zA-Z]+", s)))
    s = re.sub(r"\0(\d+)\0", lambda m: held[int(m.group(1))], s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip() + "\n", left


# ------------------------------------------------------------------ the handover folder
def _meta(main_text: str) -> dict:
    pre = strip_comments(main_text.split("\\begin{document}")[0])
    out = {}
    for name in ("title", "subtitle", "author", "date", "keywords"):
        m = re.search(r"\\%s(?![a-zA-Z])" % name, pre)
        g = _group(pre, m.end()) if m else None
        if g and g[0].strip():
            out[name] = to_markdown(g[0])[0].strip()
    return out


def _inline(text: str, folder: Path) -> str:
    """Put a listing that a section reads with \\input into the text (tables stay references)."""
    def one(m):
        rel = m.group(1) if Path(m.group(1)).suffix else m.group(1) + ".tex"
        for f in (folder / rel, folder.parents[1] / "tables" / Path(rel).name):
            if f.is_file():
                body = f.read_text(encoding="utf-8", errors="replace")
                return body if re.search(r"\\begin\{(lstlisting|verbatim)\}", body) else m.group(0)
        return m.group(0)
    return re.sub(r"\\input\{([^}]+)\}", one, text)


def _section_markdown(f: Path, folder: Path) -> tuple[str, list[str]]:
    """Markdown of one section file of a deliverable folder, and the LaTeX commands left over."""
    text = f.read_text(encoding="utf-8")
    if f.suffix != ".tex":
        return text, []
    main = deliverable.main_tex(folder)
    defs = macros(main.read_text(encoding="utf-8").split("\\begin{document}")[0]) if main else {}
    return to_markdown(_inline(text, folder), defs)


def _sections(folder: Path) -> tuple[dict, list[tuple[Path, bool]]]:
    """(metadata, [(section file, in appendix)]) of a deliverable folder, in document order."""
    main = deliverable.main_tex(folder)
    if main is None:
        return {}, [(f, False) for f in sorted((folder / "sections").glob("*.md"))]
    text = strip_comments(main.read_text(encoding="utf-8"))
    cut = text.find("\\appendix")
    files = []
    for m in re.finditer(r"\\(?:input|include)\{(sections/[^}]+)\}", text):
        f = folder / m.group(1)
        f = f if f.suffix else f.with_suffix(".tex")
        if f.exists():
            files.append((f, cut != -1 and m.start() > cut))
    return _meta(main.read_text(encoding="utf-8")), files


def used(text: str) -> dict[str, list[str]]:
    """What a Markdown section refers to (results, citations, tables, figures)."""
    plain = _MATH.sub(" ", text)                    # no citations inside mathematics or code
    return {"results": sorted(set(MD_RESULT.findall(text))),
            "citations": sorted(set(MD_CITE.findall(plain))),
            "tables": sorted(set(re.findall(r"\{\{table:([^}]+)\}\}", text))),
            "figures": sorted(set(re.findall(r"\]\(figures/([^)\s]+)\)", text)))}


def rendered(project: config.Project, folder: Path) -> str:
    """One Markdown document of a deliverable with the recorded numbers filled in (for the
    publication bundle of a project without a PDF).  Citations stay as `[@key]`."""
    res = results.load(project)
    meta, files = _sections(folder)
    parts = [f"# {meta.get('title') or project.title}\n"]
    for f, _ in files:
        parts.append(_section_markdown(f, folder)[0])
    doc = "\n".join(parts)
    doc = MD_RESULT.sub(lambda m: str(res[m.group(1)]["display"]) if m.group(1) in res else m.group(0), doc)
    doc = re.sub(r"\{\{table:([^}]+)\}\}", r"[Table: \1](tables/\1.csv)", doc)
    return re.sub(r"\{\{ref:([^}]+)\}\}", r"\1", doc)


def _commit(root: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() or None if r.returncode == 0 else None


def build(project: config.Project | None = None) -> dict:
    """Write dist/handover and return its handover.json content."""
    p = project or config.project()
    out = p.root / "dist" / "handover"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    res = results.load(p)
    built = deliverable.diagrams(p)                 # TikZ -> figures/tikz/<name>.pdf where possible
    figures = {f.stem: f for pat in ("tikz/*.pdf", "*.png", "*.pdf") for f in sorted((p.root / "figures").glob(pat))}
    tables = {f.stem: f for f in sorted((p.root / "tables").glob("*.csv"))}
    doc: dict = {**FORMAT, "slug": p.slug, "title": p.title, "lang": p.lang,
                 "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "commit": _commit(p.root), "deliverables": [], "problems": []}
    seen = {k: set() for k in ("results", "citations", "tables", "figures")}
    for d in deliverable.folders(p, markdown=True):
        meta, files = _sections(d)
        entry = {"name": d.name, **meta, "sections": [], "unconverted": []}
        for f, appendix in files:
            text, left = _section_markdown(f, d)
            text = re.sub(r"\]\(figures/([^)\s.]+)\)", lambda m: "](figures/%s)" % (
                figures[m.group(1)].name if m.group(1) in figures else m.group(1)), text)
            rel = f"{d.name}/{f.stem}.md"
            (out / rel).parent.mkdir(exist_ok=True)
            (out / rel).write_text(text, encoding="utf-8")
            u = used(text)
            for k in seen:
                seen[k] |= set(u[k])
            entry["sections"].append({"file": rel, "source": f.relative_to(p.root).as_posix(), "appendix": appendix, **u})
            entry["unconverted"] += [c for c in left if c not in entry["unconverted"]]
        bib = d / "references.bib"
        if bib.exists():
            shutil.copy2(bib, out / "references.bib")
        doc["deliverables"].append(entry)
    (out / "results.json").write_text(json.dumps(
        {k: {x: v.get(x) for x in ("value", "display", "unit", "ci", "hypothesis", "note", "provenance")}
         for k, v in sorted(res.items())}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for sub, items in (("tables", tables), ("figures", figures)):
        for f in ([*items.values()] if sub == "tables" else
                  sorted(x for pat in ("tikz/*.pdf", "*.png", "*.pdf") for x in (p.root / "figures").glob(pat))):
            (out / sub).mkdir(exist_ok=True)
            shutil.copy2(f, out / sub / f.name)
    from . import tables as _tables
    for stem in tables:                             # the cells as printed, next to the exact values
        shown = _tables.displayed(p.root / "tables" / f"{stem}.tex")
        if shown:
            with (out / "tables" / f"{stem}.display.csv").open("w", newline="", encoding="utf-8") as fh:
                import csv
                csv.writer(fh, lineterminator="\n").writerows([shown[0], *shown[1]])
    for name in ("claims.yaml", "sources.yaml"):
        if (p.root / "evidence" / name).exists():
            (out / "evidence").mkdir(exist_ok=True)
            shutil.copy2(p.root / "evidence" / name, out / "evidence" / name)
    doc["problems"] += [f"result {k} is used but not recorded" for k in sorted(seen["results"] - set(res))]
    doc["problems"] += [f"table {k} is used but tables/{k}.csv does not exist" for k in sorted(seen["tables"] - set(tables))]
    doc["problems"] += [f"figure {k} is used but not in figures/" + (f" (diagram: {built[Path(k).stem]})" if Path(k).stem in built else "")
                        for k in sorted(seen["figures"]) if not (out / "figures" / k).exists()]
    if seen["citations"] and not (out / "references.bib").exists():
        doc["problems"].append("citations are used but there is no references.bib (run `sb bib sync`)")
    doc["files"] = sorted(f.relative_to(out).as_posix() for f in out.rglob("*") if f.is_file())
    (out / "handover.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "README.md").write_text("# Handover of `%s`\n\n```\n%s```\n\nNot a publication bundle: it may hold "
                                   "restricted material. Publish only through `sb publish`.\n"
                                   % (p.slug, __doc__.split("\n\n", 1)[1]), encoding="utf-8")
    return doc
