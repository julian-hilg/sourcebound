"""sb -- command line of the research hub.

  sb init [--data-root PATH] [--projects-dir PATH]   where data and projects live (once per machine); asks in a terminal
  sb install [path|skill|agents]             `sb` on PATH, lead playbook and subagents for Claude Code
  sb install shortcut                        a desktop icon that starts the web view (`sb init` offers it)
  sb update [--extra NAME] [--no-pull]       pull the checkout, reinstall with the extras you have, rebuild
  sb doctor                                  resolved configuration and access checks
  sb run [analysis|figures|bib|lineage|paper|check ...]   project build steps in order (default: all)
  sb run analysis/h1_x.py                    one analysis script (its results are merged)
  sb which python|home|config|data-root|registry|template   one resolved path (for Makefiles)
  sb new SLUG --title "..." [--lang de|en] [--dir PATH] [--deliverable NAME|PATH]
                                             new project from the template (copy + rename)
  sb status                                  phase, hypotheses, claims (current project)
  sb check                                   ledger + citations + results + contracts
  sb freeze [--amend]                        pre-register hypotheses (date, hashes, commit + tag)
  sb snap URL --title "..." [--publisher ..] archive a web page, register W-xxxx (same bytes: the id it has)
  sb source W-xxxx [--grep W] [--chars N|0] [--out FILE]   read an archived source (verification)
  sb source set W-xxxx --title "..." [--publisher ..]      correct how a source is named
  sb lake tables | snapshots | sql "..." | export TABLE PATH
  sb bib sync | search "words" | add DOI | import
  sb datasource add ID --name "..." [--url U] [--access api|database|manual|...] [--auth-env VAR]
                [--connection-env VAR] [--mcp NAME]   register entry for a custom or private source
  sb datasource add ID --name "..." --driver mssql|postgresql|mysql|sqlite|duckdb --server H --database D
                [--auth sql|windows|none --user U --password-env VAR | --path FILE]   a database connection
  sb datasource set|test|rm ID [--server ...]   change, test (asks for the password) or remove one
  sb datasource docs ID FILE|URL ...         archive its API documentation / MCP tool list for good
  sb datasource list                         sources in the registry
  sb ingest FILE --source ID [--note "..."]   manual file (CSV, XLSX, PDF) into the raw archive
  sb bib link                                the project's Zotero collections: do they exist, how many items
  sb papers sync|convert|status              paper store: copy PDFs from Zotero, convert them (optional, background)
  sb source CITEKEY [--grep W] [--page N]    text of a stored paper (like an archived web source)
  sb lineage                                 tables/data_lineage.tex from results provenance
  sb sync                                    fill deliverables/*/generated (results, tables, figures, style files)
  sb build                                   sb sync + compile LaTeX deliverables (skipped without LaTeX)
  sb handover                                dist/handover: Markdown, results, tables, figures (no LaTeX needed)
  sb review-edits [REF]                      sections changed by a person since the last agent commit
  sb flatten                                 one .tex file per deliverable (latexpand)
  sb publish [--push]                        production bundle (+ push to GitHub)
  sb unblock SOURCE [HOST]                   clear a fetcher stop after manual inspection (user only)
  sb ui [--build] [--port N] [--no-open]     local web view of all projects (http://127.0.0.1:5210)
  sb note list | add "TITLE" [--kind K] [--status S] [--text T] [--prompt P] | set ID [...] | rm ID
                                             deliverables wanted for the study (deliverables/notes.yaml)
  sb workspace [PATH]                        VS Code workspace with every project, the data root and tasks
  sb install hooks                           Claude Code hooks that log what agents do (for the web view)
  sb hook                                    called by those hooks: one line per event into the activity log

Beyond one study (see `cli_more.py` for the list): sb new --kind desk, sb doc, sb piece, sb render,
sb design, sb template, sb pack, sb plugin, sb job, sb sql, sb mcp, sb doctor --json.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".tex", ".py", ".toml", ".cff", ".txt", "", ".json"}
SKIP = shutil.ignore_patterns("*.aux", "*.log", "*.fls", "*.fdb_latexmk", "*.out", "*.bbl", "*.bcf",
                              "*.blg", "*.run.xml", "*.synctex.gz", "*.toc", "*.pdf", "layout.json",
                              "__pycache__", ".DS_Store", "dist", ".venv", "results.json", "results.tex",
                              ".stamp")


def cmd_new(a):
    from . import config, deliverable
    h = config.hub()
    if "-" in a.slug:                   # the slug names the lake schema proj_<slug>: underscores only
        a.slug = a.slug.replace("-", "_")
        print(f"slug {a.slug} (hyphens become underscores)")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", a.slug):
        sys.exit("slug: lowercase letters, digits, _ (e.g. fuel_passthrough)")
    if a.kind == "desk":
        from . import desk
        parent = Path(a.dir).expanduser() if a.dir else h.projects_dir or (h.root if h.source == "hub" else Path.cwd())
        dest = parent.resolve() / a.slug
        if dest.exists():
            sys.exit(f"{dest} exists -- refusing to overwrite")
        desk.create(dest, a.slug, a.title, a.lang)
        rules = (config.home() or h.root) / "AGENTS.md"
        if find_rules(dest.parent) is None and rules.exists():
            (dest / "CLAUDE.md").write_text(f"@AGENTS.md\n@{_tilde(rules)}\n", encoding="utf-8")
        print(f"created desk {dest}\nnext: cd {dest}, fill in the topic in project.yaml and AGENTS.md; then `sb piece add \"...\"`")
        return
    latex = a.deliverable or h.deliverable_template
    markdown = latex == "markdown"
    try:
        latex = deliverable.resolve_template(latex, h) if latex and not markdown else None
    except FileNotFoundError as e:
        sys.exit(str(e))
    # --dir, else the configured projects folder, else next to the other projects of a hub, else here
    parent = Path(a.dir).expanduser() if a.dir else h.projects_dir or (h.root if h.source == "hub" else Path.cwd())
    dest = parent.resolve() / a.slug
    if dest.exists():
        sys.exit(f"{dest} exists -- refusing to overwrite")
    src = h.project_template
    if not (src / "project.yaml").exists():
        sys.exit(f"project template not found: {src} ([templates] project in {h.config_file})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=SKIP)
    old_slug, old_title = "example_study", "Example Study: Fat Tails in Daily EUR/USD Returns"
    for f in dest.rglob("*"):
        if f.is_file() and f.suffix in TEXT_SUFFIXES:
            t = f.read_text(encoding="utf-8")
            t2 = (t.replace(old_title, a.title).replace(old_slug, a.slug)
                  .replace("example-study", a.slug.replace("_", "-"))).replace("2026-11-09", date.today().isoformat())
            if a.lang == "de":
                t2 = (t2.replace("lang: en", "lang: de").replace("lang=en-GB", "lang=de-DE")
                        .replace("[cite=authoryear]", "[cite=authoryear, lang=ngerman]"))
            if t2 != t:
                f.write_text(t2, encoding="utf-8")
    for f in sorted(dest.rglob(f"*{old_slug}*"), reverse=True):
        f.rename(f.with_name(f.name.replace(old_slug, a.slug)))
    if a.empty:
        _empty(dest, a)
    if latex:
        deliverable.adopt(dest / "deliverables" / "paper", latex, a.title)
    if markdown:
        deliverable.to_markdown(dest / "deliverables" / "paper")
        card = dest / "project.yaml"
        card.write_text(re.sub(r"(?m)^  - \{kind: paper, path: [^}]*\}$",
                               "  - {kind: paper, path: deliverables/paper/sections, format: markdown}",
                               card.read_text(encoding="utf-8")), encoding="utf-8")
    import subprocess

    from . import ledger
    proj = config.project(dest)
    if (ledger.load(proj)["hdoc"].get("frozen") or {}).get("date"):         # the worked example is frozen
        f = dest / "hypotheses.yaml"
        f.write_text(re.sub(r"(?ms)^frozen:.*?(?=^amendments:)", "frozen: null\n", f.read_text(encoding="utf-8")), encoding="utf-8")
        ledger.freeze(proj, commit=False)
    git = lambda *x: subprocess.run(["git", *x], cwd=dest, capture_output=True)
    inside = git("rev-parse", "--is-inside-work-tree").returncode == 0
    if not inside or git("check-ignore", "-q", ".").returncode == 0:
        # a repository of its own (also inside a checkout that ignores it): results record its
        # commits, `sb review-edits` reads its history
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "Project created (sb new)")
    rules = (config.home() or h.root) / "AGENTS.md"
    if find_rules(dest.parent) is None and rules.exists():
        # outside a hub nothing above the project carries the research rules: import them
        (dest / "CLAUDE.md").write_text(f"@AGENTS.md\n@{_tilde(rules)}\n", encoding="utf-8")
    print(f"created {dest}\nnext: cd {dest} && open AGENTS.md (brief) -- then run the research-study skill")


def find_rules(start: Path) -> Path | None:
    """Folder at or above `start` whose CLAUDE.md/AGENTS.md already applies (a hub)."""
    from . import config
    return config.find_up("hub.toml", start)


def _tilde(p: Path) -> str:
    try:
        return "~/" + p.resolve().relative_to(Path.home()).as_posix()
    except ValueError:
        return p.as_posix()


EMPTY = {
    "hypotheses.yaml": None,           # keep the explanatory header, drop the examples
    "evidence/claims.yaml": None,
    "evidence/sources.yaml": "# Web sources outside Zotero. Add with `sb snap URL --title ...` (archives the page).\nsources: []\n",
    "evidence/inbox.bib": "",
    "research/landscape.md": "# Landscape\n\nSynthesis by the lead from `research/notes/`. Every statement points to a claim.\n",
    "research/brief.md": ("# Brief (Gate G1)\n\n**Question.**\n\n**Why it matters.**\n\n**Deliverables.**\n\n"
                          "**Constraints.** (time, money, data access, legal)\n\n**Out of scope.**\n\n"
                          "**Success criterion.**\n\nApproved by: (user, date)\n"),
}
REMOVE = ["analysis/h1_fat_tails.py", "research/notes/stylised_facts.md", "reviews/verification_2026-11-09.md",
          "reviews/referee_draft_2026-11-09.md", "figures/make_figures.py"]


def _empty(dest: Path, a) -> None:
    """Blank project: keep structure, formats and comments; drop the worked example."""
    for rel, text in EMPTY.items():
        f = dest / rel
        if text is None:
            head = f.read_text(encoding="utf-8").split("\nfrozen:")[0].split("\nclaims:")[0]
            key = "hypotheses" if "hypotheses" in rel else "claims"
            extra = "frozen: null\namendments: []\n" if key == "hypotheses" else ""
            text = head.rstrip() + "\n" + extra + f"{key}: []\n"
        f.write_text(text, encoding="utf-8")
    for rel in REMOVE:
        for f in dest.glob(rel.replace("2026-11-09", "*")):
            f.unlink()
    (dest / "figures" / "make_figures.py").write_text(
        '"""Figures for the deliverable (sourcebound.plot). Draw only what analysis scripts recorded in results/."""\n'
        "from pathlib import Path\n\nfrom sourcebound import plot as jp\n\nROOT = Path(__file__).resolve().parents[1]\n"
        "jp.setup()\n",
        encoding="utf-8")
    pj = dest / "project.yaml"
    t = pj.read_text(encoding="utf-8").replace("phase: deliverables", "phase: brief")
    t = t.replace("reads: [market.ecb_fx_daily]", "reads: []").replace("  data: [market.ecb_fx_daily]", "  data: []")
    pj.write_text(t, encoding="utf-8")
    log = dest / "log.md"
    log.write_text(log.read_text(encoding="utf-8").split("\n- ")[0] + f"\n- {date.today()} lead: project created (`sb new --empty`).\n",
                   encoding="utf-8")
    ag = dest / "AGENTS.md"
    ag.write_text(f"# {a.title}\n\nProject brief for agents. The Sourcebound rules (hub `AGENTS.md`) apply; the lead keeps this "
                  "file current.\n\n- **Question:** (from research/brief.md)\n- **Deliverable:**\n- **Phase:** see "
                  "`project.yaml`; decisions in `log.md`.\n- **Data:** shared tables used / project tables owned\n"
                  "- **Scope limits:**\n" f"- **Zotero collection:** `research/{a.slug}`\n\n"
                  + "## Map" + ag.read_text(encoding="utf-8").split("## Map", 1)[1], encoding="utf-8")
    paper = dest / "deliverables" / "paper"
    for f in (paper / "sections").glob("*.tex"):
        f.unlink()
    (paper / "sections" / "00_abstract.tex").write_text("\\begin{abstract}\n\\end{abstract}\n", encoding="utf-8")
    (paper / "sections" / "01_introduction.tex").write_text("\\section{Introduction}\n", encoding="utf-8")
    tex = (paper / "main.tex").read_text(encoding="utf-8")
    body = ("\\begin{document}\n\\maketitle\n\n\\input{sections/00_abstract}\n\n"
            "\\input{sections/01_introduction}\n\n\\printbibliography\n\n\\end{document}\n")
    (paper / "main.tex").write_text(tex.split("\\begin{document}")[0] + body, encoding="utf-8")


USER_CONFIG = """# Sourcebound user configuration (written by `sb init`). Same keys as a hub.toml.
# Resolution: SB_CONFIG -> nearest hub.toml above the working directory -> this file.
# Data root:  SB_LAKE_ROOT -> project.yaml `data_root:` -> lake.root below.

[lake]
# One data root per machine, shared by every project and app. {{root}} = lake.root.
root      = "{data_root}"
catalog   = "sqlite:{{root}}/catalog.sqlite"
data_path = "{{root}}/data/"
raw       = "{{root}}/raw"
registry  = "{{root}}/registry"          # shared contracts and the source register

[fetch]
# Honest identification: the tool's own name, never a browser string.
user_agent   = "sourcebound/0.1 (research)"
min_interval = 6.0
jitter       = 3.0
respect_robots = true

[zotero]
url = "http://127.0.0.1:23119"
collection_root = "research"

[github]
owner = "{owner}"                       # your GitHub user or organisation, for `sb publish --push`

# Optional: a command that converts a paper's PDF to Markdown for `sb papers` ({{pdf}}, {{out}}).
# Any tool works; formula-snip is one that runs locally.
# [library]
# converter = "formula-snip convert {{pdf}} --out {{out}}"

# Your own LaTeX templates for deliverables: a folder with a .tex document and its style
# files. `sb new --deliverable NAME` uses its preamble; `deliverable` sets the default.
# [templates]
# deliverable = "house"
# [templates.latex]
# house = "~/path/to/template-folder"
{projects}"""


def seed_registry(h) -> list[str]:
    """Create the data root layout; copy the checkout's example contracts and sources if absent."""
    from . import config
    made = []
    for d in (h.lake_root, h.raw_root, h.registry / "contracts", h.registry / "datasources",
              *([Path(h.data_path)] if "://" not in h.data_path else [])):
        if not d.exists():
            d.mkdir(parents=True)
            made.append(str(d))
    src = config.home()
    for kind in ("contracts", "datasources") if src else ():
        for f in sorted((src / kind).rglob("*.yaml")):
            dest = h.registry / kind / f.relative_to(src / kind)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                made.append(str(dest))
    return made


def _ask(question: str, default: str) -> str:
    answer = input(f"{question}\n  [{default}]: ").strip()
    return answer or default


def cmd_init(a):
    """The user configuration: where data lives and where projects go.

    In a terminal it asks for what was not given.  Without a terminal (an agent, a script) the
    two folders must be named: choosing them is the person's decision, not a default to guess.
    """
    from . import config
    path = config.user_config_path()
    if path.exists() and not a.force:
        print(f"keeping {path} (use --force to rewrite it)")
    else:
        data, projects, owner = a.data_root, a.projects_dir, a.github_owner or ""
        tty = sys.stdin.isatty() and sys.stdout.isatty()
        if a.defaults:
            data, projects = data or "~/research-lake", projects or "~/Documents/research"
        elif tty and not (data and projects):
            print("Sourcebound keeps code, research and data apart. Two folders are yours to choose.\n")
            data = data or _ask("Data root: the data lake, the archive of raw responses and the registry live here.\n"
                                "It grows large and is never in git. Choose a disk with space.", "~/research-lake")
            projects = projects or _ask("\nResearch folder: your projects go here, one folder each (studies and desks),\n"
                                        "each its own git repository.", "~/Documents/research")
            if not a.github_owner:
                owner = input("\nGitHub user or organisation for publishing a study (optional, Enter to skip)\n  []: ").strip()
            from . import shortcut
            if not a.shortcut and shortcut.available():
                a.shortcut = input("\nA desktop icon that starts the web view (sb ui)? (y/N)\n  [n]: ").strip().lower() in ("y", "yes", "j", "ja")
            print()
        elif not data:
            sys.exit('sb init: name the two folders, they are the user\'s choice:\n'
                     '  sb init --data-root PATH --projects-dir PATH\n'
                     "(the data root holds the lake, the raw archive and the registry; the research folder holds "
                     "the projects). An agent asks the user for both first. `sb init --defaults` takes "
                     "~/research-lake and ~/Documents/research.")
        root = Path(data).expanduser().resolve()
        section = ""
        if projects:
            pdir = Path(projects).expanduser().resolve()
            pdir.mkdir(parents=True, exist_ok=True)
            section = f'\n[projects]\ndir = "{_tilde(pdir)}"   # where `sb new` creates projects\n'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(USER_CONFIG.format(data_root=_tilde(root), projects=section, owner=owner), encoding="utf-8")
        print(f"wrote {path}")
    config._load_hub.cache_clear()
    h = config._load_hub(path, "user", None, (None, None, None))
    for m in seed_registry(h):
        print("created", m)
    print(f"data root:       {h.lake_root}\nresearch folder: {h.projects_dir or '-- (none set; sb new creates projects in the current folder)'}")
    if a.shortcut:
        _shortcut()
    print("next: sb doctor")


def _shortcut() -> None:
    from . import shortcut
    if not shortcut.available():
        print("desktop icon: skipped (this installation has no web view)")
        return
    print(f"desktop icon -> {shortcut.create()} (starts `sb ui`; build the web view once with `sb ui --build`)")


def _place(src: Path, dst: Path) -> str:
    """Symlink `dst` to `src`; a copy where symlinks are not permitted (Windows without developer mode)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
        return "linked"
    except OSError:
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
        return "copied"


def cmd_install(a):
    """`sb` on PATH, the lead playbook and the subagents for Claude Code (any operating system)."""
    import os

    from . import config
    src = config.home()
    if src is None:
        sys.exit("sb install needs the Sourcebound checkout (an editable install: uv sync in the checkout)")
    what = {"path", "skill", "agents"} if a.what == "all" else {a.what}
    claude, how = Path.home() / ".claude", set()
    if "hooks" in what:
        from . import activity
        changed = activity.install(claude / "settings.json")
        print(f"hooks -> {claude / 'settings.json'} ({'added' if changed else 'already there'}); "
              f"events go to {activity.log_path()}; new Claude Code sessions use them")
    if "path" in what:
        bin_dir = Path(a.bin).expanduser() if a.bin else Path.home() / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        exe = Path(sys.executable).parent / ("sb.exe" if os.name == "nt" else "sb")
        if os.name == "nt":                         # one launcher for cmd/PowerShell, one for Git Bash
            (bin_dir / "sb.cmd").write_text(f'@"{exe}" %*\n', encoding="utf-8")
            (bin_dir / "sb").write_text(f'#!/bin/sh\nexec "{exe.as_posix()}" "$@"\n', encoding="utf-8", newline="\n")
        else:
            (bin_dir / "sb").unlink(missing_ok=True)
            (bin_dir / "sb").symlink_to(exe)
        print(f"sb -> {bin_dir}")
        if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
            print(f"note: add {bin_dir} to PATH")
    if "skill" in what:
        for d in sorted(x for x in (src / "skills").iterdir() if (x / "SKILL.md").exists()):
            how.add(_place(d, claude / "skills" / d.name))
            print(f"playbook {d.name} -> {claude / 'skills' / d.name}")
        try:                                        # and those of installed packs (an organisation's own playbooks)
            from . import assets
            for d in assets.pack_skills():
                how.add(_place(d, claude / "skills" / d.name))
                print(f"playbook {d.name} (from a pack) -> {claude / 'skills' / d.name}")
        except Exception:
            pass                                    # no configuration yet: the checkout's playbooks are enough
    if "agents" in what:
        # the file prefix avoids clashes with your own agents; the agent names stay unchanged
        for f in sorted((src / ".claude" / "agents").glob("*.md")):
            how.add(_place(f, claude / "agents" / f"sb-{f.name}"))
        print(f"subagents -> {claude / 'agents'} (sb-*.md)")
    if "shortcut" in what:
        _shortcut()
    if "copied" in how:
        print("note: copied, not linked (no permission for symlinks): run `sb install` again after updating the checkout")
    if a.what == "all":
        if not config.user_config_path().exists() and sys.stdin.isatty() and sys.stdout.isatty():
            print("\nLast step: where data and projects live.\n")
            cmd_init(argparse.Namespace(data_root=None, projects_dir=None, github_owner=None, defaults=False, force=False,
                                        shortcut=False))
        elif not config.user_config_path().exists():
            print("next: sb init --data-root PATH --projects-dir PATH (the user chooses both folders), then sb doctor")
        else:
            print(f"configuration: {config.user_config_path()} (kept); next: sb doctor")


def cmd_update(a):
    """The checkout, its packages (with the extras installed now), launcher and playbooks, the web view."""
    from . import config, update
    home = config.home()
    if home is None:
        sys.exit("sb update needs the Sourcebound checkout (an editable install: uv sync in the checkout)")
    sys.exit(update.run(home, add=a.extra or [], pull=not a.no_pull,
                        frontend=False if a.no_frontend else None, dry_run=a.dry_run))


STEPS = ["analysis", "figures", "bib", "lineage", "paper", "check"]


def cmd_run(a):
    """Project build steps in order (what `make` does, without needing make)."""
    import subprocess

    from . import config, results
    p = config.project()
    steps = STEPS if not a.steps or "all" in a.steps else a.steps
    bad = [s for s in steps if s not in STEPS and not (s.endswith(".py") and (p.root / s).is_file())]
    if bad:
        sys.exit(f"sb run: unknown step {', '.join(bad)} (steps: {', '.join(STEPS)}, or a script such as analysis/h1_x.py)")
    sb = [sys.executable, "-m", "sourcebound.cli"]
    for step in steps:
        kept = None
        if step == "analysis":
            # every script in name order, into fresh results: a key no script records any more is gone
            runs = [[sys.executable, str(f)] for f in sorted((p.root / "analysis").glob("*.py"))]
            kept = {f: f.read_bytes() for f in (p.root / "results").glob("results.*") if f.suffix in {".json", ".tex"}}
            for f in kept:
                f.unlink()
        elif step.endswith(".py"):                  # one script (an analyst's own): results are merged
            runs = [[sys.executable, str(p.root / step)]]
        elif step == "figures":
            f = p.root / "figures" / "make_figures.py"
            runs = [[sys.executable, str(f)]] if f.exists() else []
        else:
            runs = [[*sb, *{"bib": ["bib", "sync"], "paper": ["build"]}.get(step, [step])]]
        for run in runs:
            script = run[:3] != sb
            print("==", step if not script else Path(run[1]).relative_to(p.root).as_posix(), flush=True)
            before = results.load(p) if script else {}
            code = subprocess.run(run, cwd=p.root).returncode
            if code:
                for f, body in (kept or {}).items():        # a failed run leaves the earlier results in place
                    f.write_bytes(body)
                sys.exit(code)
            if script:
                _recorded(before, results.load(p))


def _recorded(before: dict, after: dict, limit: int = 20) -> None:
    """The keys a script recorded (new or written again), with their display values."""
    keys = sorted(k for k, v in after.items() if before.get(k) != v)
    if not keys:
        print("   no results recorded")
    for k in keys[:limit]:
        v = after[k]
        print(f"   {k} = {v.get('display')}" + (f" {v['unit']}" if v.get("unit") and v["unit"] not in str(v.get("display")) else ""))
    if len(keys) > limit:
        print(f"   … {len(keys) - limit} more")


def cmd_doctor(a):
    """Print the resolved configuration and check that it is usable."""
    import os
    if getattr(a, "json", False):
        import json

        from . import system
        print(json.dumps(system.report(), indent=2, ensure_ascii=False, default=str))
        return

    from . import config, contracts
    loc = config.locate()
    if loc is None:
        sys.exit(f"ERROR: no configuration (no hub.toml above {Path.cwd()}, no {config.user_config_path()}); run `sb init`")
    h = config.hub()
    p = config.project(required=False)
    rows = [("configuration", f"{h.config_file}  [{h.source}]"), ("checkout", config.home() or "-- (not an editable install)"),
            ("project", f"{p.slug}  ({p.root})" if p else "--"),
            ("data root", f"{h.lake_root}  [from {h.lake_root_from}]"), ("catalog", h.catalog),
            ("data path", h.data_path), ("raw archive", h.raw_root), ("registry", h.registry),
            ("new contracts", h.contracts_dir), ("new sources", h.datasources_dir),
            ("paper store", f"{h.library}  [converter: {h.converter or 'none (optional)'}]"),
            ("project template", h.project_template), ("user agent", h.user_agent)]
    from . import deliverable
    tools = deliverable.tex_tools()
    rows.append(("LaTeX", "installed" if tools["latexmk"] and tools["pdflatex"] else
                 "not installed (optional: only needed to build LaTeX deliverables; `sb handover` works without)"))
    for k, v in rows:
        print(f"{k:<17} {v}")
    errs, warns = [], []
    for name, d in (("data root", h.lake_root), ("raw archive", h.raw_root)):
        if not d.is_dir():
            errs.append(f"{name} {d} does not exist (run `sb init`)")
        elif not os.access(d, os.W_OK):
            errs.append(f"{name} {d} is not writable")
    if not (h.registry / "contracts").is_dir():
        warns.append(f"no registry at {h.registry} (run `sb init`); using the contracts in {h.root}")
    names: set[str] = set()
    for base in h.contract_bases:
        try:
            names |= {c.name for c in contracts.all_contracts(base)}
        except Exception as e:  # noqa: BLE001 -- report every broken contract file
            errs.append(f"contract in {base / 'contracts'}: {e}")
    n = len(names)
    if h.lake_root.is_dir() and not errs:
        try:
            from . import lake
            con = lake.connect(fresh=True)
            tabs = lake._run(con, "SELECT count(*) FROM duckdb_tables() WHERE database_name = 'lake'")[0][0]
            print(f"{'catalog check':<17} ok: {tabs} tables, snapshot {lake.snapshot_id(con)}, {n} shared contracts")
            con.close()
        except Exception as e:  # noqa: BLE001
            errs.append(f"catalog: {e}")
    if not h.project_template.is_dir():
        errs.append(f"project template missing: {h.project_template}")
    exe = shutil.which("sb")
    if exe is None:
        warns.append("`sb` is not on PATH (`sb install path` puts it into ~/.local/bin)")
    elif Path(exe).resolve() != Path(sys.argv[0]).resolve() and Path(sys.argv[0]).name == "sb":
        warns.append(f"`sb` on PATH is {Path(exe).resolve()}, not this one ({Path(sys.argv[0]).resolve()})")
    claude = Path.home() / ".claude"
    if not (claude / "skills" / "research-study").exists():
        warns.append("lead playbook not installed (sb install skill)")
    if config.find_up("hub.toml") is None and not list((claude / "agents").glob("sb-*.md")):
        warns.append("subagents not installed at user level (sb install agents); projects outside the checkout will not find them")
    from . import toolkits
    for name in sorted(toolkits.registered()):            # an organisation's code beside Sourcebound (a plugin names it)
        st = toolkits.status(name)
        print(f"{'toolkit ' + name:<17} " + (f"ok: {st.root} ({len(st.skills)} skills)" if st.ok else "not usable"))
        warns += [f"toolkit {name}: {x}" for x in st.errors + st.warnings]
    for w in warns:
        print("warning:", w)
    for e in errs:
        print("ERROR:  ", e)
    print(f"{len(errs)} errors, {len(warns)} warnings")
    sys.exit(1 if errs else 0)


WHICH = {"python": lambda h: sys.executable, "home": lambda h: _home(h), "config": lambda h: h.config_file,
         "data-root": lambda h: h.lake_root, "registry": lambda h: h.registry,
         "template": lambda h: h.project_template}


def _home(h) -> Path:
    from . import config
    return config.home() or h.root


def cmd_which(a):
    from . import config
    print(sys.executable if a.what == "python" else WHICH[a.what](config.hub()))


def cmd_status(a):
    from . import config, ledger
    p = config.project()
    print(f"{p.slug}: {p.title}  [phase: {p.meta.get('phase', '?')}, lang: {p.lang}]")
    if p.meta.get("kind") == "desk":
        print(_desk_status(p))
        return
    print(ledger.status_table(p))


def _desk_status(p) -> str:
    """A desk has no hypotheses and no claims table: its topic, sources, pieces and results."""
    from . import ledger, pieces, results
    rows = [f"topic:   {p.meta.get('topic') or '(not set: one sentence in project.yaml)'}"]
    if p.meta.get("channels"):
        rows.append(f"channels: {', '.join(map(str, p.meta['channels']))}")
    rows.append(f"sources: {len(ledger.load(p)['sources'])} registered (evidence/sources.yaml)")
    cards = pieces.load(p)
    n = {s: sum(1 for c in cards if c.get("status") == s) for s in pieces.STATUS}
    rows.append(f"pieces:  {len(cards)}" + (" (" + ", ".join(f"{k} {v}" for k, v in n.items() if v) + ")" if cards else ""))
    rows.append(f"results: {len(results.load(p))} recorded")
    return "\n".join(rows)


def cmd_check(a):
    from . import config, contracts, handover, ledger, results, zotero
    p = config.project()
    h = config.hub()
    errs, warns = ledger.check(p, resolve_citekeys=not a.offline)
    res = results.load(p)
    e, w = results.problems(p)
    errs += e
    warns += w
    from . import deliverable
    for f in sorted((p.root / "deliverables").glob("*/sections/*")):
        if f.suffix in {".tex", ".md"}:
            hits = deliverable.typed_numbers(f.read_text(encoding="utf-8", errors="replace"), markdown=f.suffix == ".md")
            if hits:
                warns.append(f"{f.relative_to(p.root).as_posix()}: {len(hits)} lines with a number typed by hand "
                             f"(lines {', '.join(str(n) for n, _ in hits[:6])}{', ...' if len(hits) > 6 else ''}): "
                             "record it and use \\result{key}, or confirm it is not a result")
    tex = "\n".join(zotero.strip_comments(f.read_text(encoding="utf-8", errors="replace"))
                    for f in (p.root / "deliverables").rglob("*.tex"))
    md = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                   for f in (p.root / "deliverables").glob("*/sections/*.md"))
    for k in sorted((set(re.findall(r"\\result\*?\{([^}]+)\}", tex)) | set(handover.MD_RESULT.findall(md))) - set(res)):
        errs.append(f"deliverable uses result {k} but it is not recorded")
    tex += md
    if re.search(r"\b(TODO|FIXME)\b", tex):
        warns.append("deliverables contain TODO/FIXME")
    keys = zotero.cited_keys(p)
    if keys and not a.offline and zotero.ready():
        for k in sorted(keys - zotero.known_keys(p, keys)):
            errs.append(f"\\cite{{{k}}}: unknown citation key")
    shared = h.contract_bases
    for base in (p.root, *shared):
        for c in contracts.all_contracts(base) if (base / "contracts").exists() else []:
            if c.sources and base in shared:
                for s in c.sources:
                    if h.datasource(s) is None:
                        warns.append(f"contract {c.name}: datasource {s} has no datasources/{s}.yaml")
    for w in warns:
        print("warning:", w)
    for e in errs:
        print("ERROR:  ", e)
    print(f"{len(errs)} errors, {len(warns)} warnings")
    sys.exit(1 if errs else 0)


def cmd_freeze(a):
    from . import ledger
    errs, _ = ledger.check(resolve_citekeys=False)
    errs = [e for e in errs if not (a.amend and "freeze of" in e)]      # what the amendment is about to settle
    if errs and not a.force:
        sys.exit("fix ledger errors first:\n  " + "\n  ".join(errs))
    try:
        stamp = ledger.freeze(amend=a.amend)
    except ValueError as e:
        sys.exit(str(e))
    print(f"hypotheses {'amended' if a.amend else 'frozen'} on {stamp} -- `sb check` now reports any change; "
          "changes need an entry under `amendments:` and `sb freeze --amend`")


def cmd_snap(a):
    from . import ledger
    from .fetch import Blocked, Fetcher
    f = Fetcher("web")
    try:
        _, ref = f.get(a.url)
    except Blocked as e:
        sys.exit(f"not archived: {e}\n(do not work around this; cite another source or ask the user)")
    entry = {"title": a.title, "url": a.url, "publisher": a.publisher or "",
             "accessed": ref.fetched_at, "sha256": ref.sha256, "raw": ref.path, "note": a.note or ""}
    dated = _published(a.date, ref.sha256, ref.path, a.title)
    if dated:
        entry["date"] = dated[0]
    sid, created = ledger.register_source(entry, new=a.new)
    if not created:
        print(already_registered(sid, ref.sha256))
        return
    print(f"{sid}  {ledger.source_label(entry)}\n      {a.url}, archived raw/{ref.path}  "
          f"(cite as \\cite{{{sid}}}, ref: {sid} in claims.yaml)\n      " + _dated_line(dated, sid))


def _published(given: str | None, sha256: str, name: str, title: str) -> tuple[str, str] | None:
    """(date, where from) of a source: what the person gave, else what the archived copy or its title says."""
    from . import srcdate
    from .fetch import read_raw
    if given:
        d = srcdate.normal(given)
        if d is None:
            sys.exit(f"--date {given}: not a date (YYYY-MM-DD, YYYY-MM or YYYY)")
        return d, "given"
    try:
        data = read_raw("web", sha256)
    except (FileNotFoundError, OSError):
        data = None
    return srcdate.find(data, name=name.removesuffix(".zst"), title=title)


def _dated_line(dated: tuple[str, str] | None, sid: str) -> str:
    if dated is None:
        return f"published: not found in the file (citations will say n.d.); set it with `sb source set {sid} --date YYYY-MM-DD`"
    return f"published {dated[0]}" + ("" if dated[1] == "given" else f" (from {dated[1]}; correct it with `sb source set {sid} --date ...`)")


def _source_dates(write: bool) -> None:
    """`sb source dates`: the publication date of every source that has none, read from its archived copy."""
    from . import ledger
    rows = [s for s in ledger.load()["sources"] if not s.get("date") and s.get("sha256")]
    found = 0
    for s in rows:
        dated = _published(None, s["sha256"], s.get("file") or s.get("raw") or "", s.get("title") or "")
        if dated:
            found += 1
            if write:
                ledger.update_source(s["id"], {"date": dated[0]})
        print(f"{s['id']}  {dated[0] if dated else '-':<10}  {('from ' + dated[1]) if dated else 'nothing in the file or the title':<32}  {str(s.get('title') or '')[:70]}")
    if not rows:
        print("every source has a date")
        return
    print(f"\n{found} of {len(rows)} sources without a date " + ("now have one" if write else "can be dated: `sb source dates --write` records them")
          + (f"; {len(rows) - found} stay undated (n.d.) until `sb source set W-xxxx --date ...`" if found < len(rows) else "")
          + ("\nrenders made before still show the old dates; render again" if write and found else ""))


def already_registered(sid: str, sha256: str) -> str:
    """The message for bytes that are already a source (`sb snap`, `sb doc`)."""
    from . import ledger
    src = next((s for s in ledger.load()["sources"] if s.get("id") == sid), {})
    return (f"already registered as {sid}  {ledger.source_label(src)}\n      same bytes (sha256 {sha256[:12]}), no new entry; "
            f"cite {sid}. Correct its title with `sb source set {sid} --title ...`; --new registers it again.")


def _show_text(text: str, a, what: str) -> None:
    """Print a source's text: a grep (merged, numbered passages), or the first --chars characters
    with a line that says how much is left out.  --out writes the whole text to a file."""
    if a.out:
        out = Path(a.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="")     # as read: no second \r on Windows
        print(f"wrote {out} ({len(text):,} characters, the whole text of {what})")
        if not a.grep:
            return
    if a.grep:
        hits = [(m.start(), m.end()) for m in re.finditer(re.escape(a.grep), text, re.I)]
        spans: list[list[int]] = []                 # [start, end, first hit, last hit]
        for i, (s, e) in enumerate(hits, 1):
            s, e = max(0, s - 200), min(len(text), e + 200)
            if spans and s <= spans[-1][1]:
                spans[-1][1], spans[-1][3] = max(spans[-1][1], e), i
            else:
                spans.append([s, e, i, i])
        print(f'{len(hits)} hit{"s" if len(hits) != 1 else ""} for "{a.grep}"' +
              (f" in {len(spans)} passage{'s' if len(spans) != 1 else ''}" if hits else ""))
        for n, (s, e, i, j) in enumerate(spans, 1):
            label = f"hit {i}" if i == j else f"hits {i}-{j}"
            passage = re.sub(r"\s+", " ", text[s:e]).strip()
            print(f"\n[{n}] {label}: {'... ' if s else ''}{passage}{' ...' if e < len(text) else ''}")
        return
    if not a.chars or a.chars >= len(text):
        print(text)
        return
    cut = text[: a.chars]
    space = max(cut.rfind(" "), cut.rfind("\n"))
    if space > a.chars - 200:                       # end on a word, not inside one
        cut = cut[:space]
    print(cut.rstrip())
    print(f"\n... ({len(cut):,} of {len(text):,} characters shown; --chars N for more, --chars 0 for all, "
          "--grep WORD to search, --out FILE for the whole text)")


def cmd_source(a):
    """Text of an archived source (for verification): sb source W-0003 [--grep word] [--out FILE];
    sb source set W-0003 --title ... --publisher ... corrects how it is named."""
    import html as htmlmod

    from . import ledger
    from .fetch import read_raw
    fields = {k: getattr(a, k) for k in ledger.SOURCE_FIELDS if getattr(a, k, None) is not None}
    if a.id == "dates":
        _source_dates(a.write)
        return
    if a.id == "set":
        if not a.sid or not fields:
            sys.exit('usage: sb source set W-xxxx [--title "..."] [--publisher "..."] [--author "..."] [--date YYYY-MM-DD]')
        try:
            before, after = ledger.update_source(a.sid, fields)
        except (KeyError, ValueError) as e:
            sys.exit(str(e).strip("'\""))
        changes = [f"{k}: {before.get(k) or '(none)'} -> {after.get(k) or '(none)'}" for k in fields if before.get(k) != after.get(k)]
        print(f"{a.sid}  {ledger.source_label(after)}\n      " + ("; ".join(changes) if changes else "nothing changed") +
              ("\n      renders made before still show the old name; render the pieces that cite it again" if changes else ""))
        return
    if a.sid or fields:
        sys.exit("--title, --publisher, --author and --date change a source: sb source set W-xxxx --title ...")
    src = {s["id"]: s for s in ledger.load()["sources"]}.get(a.id)
    if src is None and not re.fullmatch(r"W-\d+", a.id):          # a citation key: the paper store
        from . import library
        try:
            text, info = library.text(a.id, page=a.page)
        except (FileNotFoundError, RuntimeError) as e:
            sys.exit(str(e))
        print(f"{a.id}  {info['kind']}" + (f", page {a.page}" if a.page else "") + f"  (PDF sha256 {info['sha256'][:12]}; "
              "the PDF page is the authority)")
        _show_text(text, a, a.id)
        return
    if src is None or not src.get("sha256"):
        sys.exit(f"{a.id}: no archived snapshot")
    body = read_raw("web", src["sha256"])
    notice = ""
    if src.get("raw", "").endswith(".pdf.zst"):
        from . import pdftext
        text, _engine = pdftext.text(body, page=a.page)
    elif src.get("file"):                               # a document brought in with `sb doc`
        from .cli_more import document_info, document_text
        text = document_text(body, src["file"])
        info = document_info(body, src["file"])
        missing = [f"{n} {w}{'s' if n != 1 else ''}" for w, n in (("image", info["images"]), ("chart", info["charts"])) if n]
        if missing:
            notice = f"      {' and '.join(missing)} not read (charts and figures are not text)\n"
    else:
        t = body.decode("utf-8", errors="replace")
        t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", t)
        text = htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)))
    where = f"file {src['file']}" if src.get("file") else src["url"]
    print(f"{a.id}  {ledger.source_label(src)}\n      {where}  (accessed {src.get('accessed', '?')}, sha256 {src['sha256'][:12]})\n"
          + notice)
    _show_text(text, a, a.id)


def cmd_figure(a):
    """Figures for pieces. `sb figure crop W-0007 --page 4 --box 52,8,98,45 --out pieces/ID/figures/x.png`
    cuts a chart out of a registered PDF; `--grid` writes the page with a 10 % grid to read the box off."""
    from . import figures, ledger
    from .fetch import read_raw
    if a.what != "crop":
        sys.exit(f"sb figure {a.what}: unknown (sb figure crop W-xxxx --page N --box l,t,r,b --out FILE)")
    src = {s["id"]: s for s in ledger.load()["sources"]}.get(a.id)
    if src is None or not src.get("sha256"):
        sys.exit(f"{a.id}: not a registered source with an archived copy (sb doc FILE)")
    if not str(src.get("raw", "")).endswith(".pdf.zst") and not str(src.get("file", "")).lower().endswith(".pdf"):
        sys.exit(f"{a.id} is not a PDF: only a PDF page can be cropped")
    body = read_raw("web", src["sha256"])
    out = Path(a.out) if a.out else Path(f"{a.id}_p{a.page}" + ("_grid" if a.grid else "") + ".png")
    try:
        if a.grid:
            w, h = figures.grid(body, a.page, out)
            print(f"wrote {out} ({w} x {h} px): page {a.page} of {a.id} with a grid in percent of the page;\n"
                  f"read the box off it and crop: sb figure crop {a.id} --page {a.page} --box left,top,right,bottom --out FILE")
            return
        if not a.box:
            sys.exit("--box left,top,right,bottom (percent of the page) is needed; --grid shows the page with a grid to read it off")
        w, h = figures.crop(body, a.page, figures.parse_box(a.box), out, dpi=a.dpi, trim=not a.no_trim)
    except figures.CropError as e:
        sys.exit(str(e))
    print(f"wrote {out} ({w} x {h} px) from {a.id}, page {a.page}, box {a.box}")
    print("   use it in slides.yaml (src relative to the piece folder):\n"
          f"   - {{type: image, src: figures/{out.name}, alt: \"what the figure shows\", from: \"{a.id}, p. {a.page}\"}}")


def databases_error():
    from .databases import SpecError
    return SpecError


DB_FLAGS = ("driver", "server", "port", "database", "auth", "user", "password_env", "encrypt",
            "trust_server_certificate", "ssl_mode", "timeout", "path")


def _db_spec(a, partial: bool = False) -> dict | None:
    """The database fields given on the command line (`sb datasource add|set ... --driver ...`)."""
    spec = {k: getattr(a, k) for k in DB_FLAGS if getattr(a, k, None) is not None}
    if partial:
        return spec
    return spec if a.driver else None


def cmd_datasource(a):
    from . import sources
    from .fetch import Blocked
    try:
        if a.what == "list":
            for s in sources.listing():
                print(f"{s['id']:<24} {s['access']:<11} {s['status']:<10} {s['docs']} docs  {s['name']}")
        elif a.what == "add":
            if not a.id or not a.name:
                sys.exit("sb datasource add ID --name \"...\"")
            f = sources.add(a.id, name=a.name, url=a.url or "", access=a.access, auth_env=a.auth_env,
                            connection_env=a.connection_env, mcp=a.mcp, database=_db_spec(a))
            print(f"wrote {f} (status: candidate)\nnext: " + (f"sb datasource test {a.id}" if a.driver else
                  f"sb datasource docs {a.id} <API documentation or MCP tool list>"))
        elif a.what in ("set", "test", "rm"):
            from . import databases
            if not a.id:
                sys.exit(f"sb datasource {a.what} ID")
            if a.what == "set":
                old = databases.spec_of(a.id) or {}
                r = databases.save(a.id, name=a.name, spec={**old, **(_db_spec(a, partial=True) or {})})
                print(f"wrote {r['path']}\nnext: sb datasource test {a.id}")
            elif a.what == "rm":
                print(f"removed {databases.remove(a.id)['path']}")
            else:
                spec = databases.spec_of(a.id)
                pw = None
                if spec and databases.needs_password(spec) and not databases.password(a.id, spec) and sys.stdin.isatty():
                    import getpass
                    pw = getpass.getpass(f"password for {spec['user']} on {spec['server']} (not stored): ")
                r = databases.test(a.id, pw)
                print(f"{a.id}: {r['status']}: {r['message']}")
                if r["status"] != "ok":
                    sys.exit(1)
        elif a.what == "docs":
            if not a.id:
                sys.exit("sb datasource docs ID [FILE|URL ...]")
            for x in sources.archive_docs(a.id, a.items):
                print(f"{x['origin']}: " + (f"archived {x['file']}" if x["file"] else x["note"]) + f"  sha256 {x['sha256'][:12]}")
            print(f"{len(sources.docs(a.id))} documents in {sources.docs_dir(a.id)}")
    except databases_error() as e:
        sys.exit("the connection is not complete:\n" + "\n".join(f"  {k}: {v}" for k, v in e.errors.items()))
    except Blocked as e:
        sys.exit(f"not archived: {e}\n(do not work around this; save the documentation by hand and pass the file)")
    except (ValueError, OSError, RuntimeError) as e:
        sys.exit(str(e))


def cmd_ingest(a):
    from . import sources
    try:
        ref = sources.ingest(a.file, a.source, note=a.note)
    except (ValueError, OSError) as e:
        sys.exit(str(e))
    print(f"archived raw/{ref.path}\nraw_ref (sha256): {ref.sha256}\n"
          f"parse it in a pipeline with sourcebound.fetch.read_raw({a.source!r}, sha256)")


def _user_only(what: str, word: str) -> None:
    """Decisions that belong to the user: only from a terminal, confirmed by typing a word."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit(f"{what}: this is the user's decision. Run the command yourself in a terminal; "
                 "an agent must not run or work around it.")
    if input(f'{what}\nType "{word}" to confirm: ').strip() != word:
        sys.exit("not confirmed")


def cmd_unblock(a):
    from .fetch import blocked, unblock
    for host, why in blocked(a.source).items():
        print(f"blocked: {host}  ({why})")
    _user_only(f"Clear the stop for source {a.source}" + (f", host {a.host}" if a.host else " (all hosts)"), a.source)
    hosts = unblock(a.source, a.host)
    print(f"cleared: {', '.join(hosts)}" if hosts else "was not blocked")


def cmd_lake(a):
    import polars as pl
    from . import lake
    pl.Config.set_tbl_rows(50)
    pl.Config.set_fmt_str_lengths(60)
    if a.what == "tables":
        print(lake.tables())
    elif a.what == "snapshots":
        print(lake.snapshots())
    elif a.what == "sql":
        print(lake.sql(a.args[0]))
    elif a.what == "export":
        print(lake.export(a.args[0], a.args[1]))


def cmd_bib(a):
    from . import zotero
    if a.what == "sync":
        outs, missing, written = zotero.sync()
        if written:
            for out in outs:
                print(f"wrote {out}")
        else:
            print("Zotero is not running: references.bib left as it is"
                  + ("" if missing else " (it holds every cited key)"))
        for k in missing:
            print(f"ERROR: {k} " + ("not found in Zotero (add it there or via `sb bib add DOI`)" if written else
                                    "is cited but not in references.bib: start Zotero and run `sb bib sync`"))
        sys.exit(1 if missing else 0)
    if a.what == "search":
        for it in zotero.search(" ".join(a.args)):
            print(f"{it['citekey']:<32} {it['year']:<5} {it['creators'][:28]:<28} {it['title'][:70]}")
    elif a.what == "add":
        from .fetch import Blocked
        for doi in a.args:
            try:
                print("inbox:", zotero.add_doi(doi))
            except Blocked as e:
                sys.exit(f"{doi}: {e}")
    elif a.what == "import":
        print(f"imported {zotero.import_inbox()} entries into the selected Zotero collection")
    elif a.what == "link":
        from . import library
        try:
            found = library.linked()
        except RuntimeError as e:
            sys.exit(str(e))
        if not found:
            sys.exit("project.yaml names no Zotero collection (zotero_collection: research/<slug>)")
        for path, keys in found.items():
            print(f"{path}: " + (f"{len(keys)} items" if keys is not None else
                                 "not in Zotero -- create this collection there (New Collection), then run this again"))
        if any(k is None for k in found.values()):
            sys.exit(1)


def cmd_papers(a):
    from . import library
    try:
        if a.what == "sync":
            rep = library.sync()
            print(f"paper store {library.root()}: {len(rep['added'])} added, {len(rep['present'])} already there")
            for k in rep["no_pdf"]:
                print(f"no PDF in Zotero: {k}")
            if not a.no_convert:
                pid = library.convert_in_background()
                print(f"conversion started in the background (process {pid}, log {library.root() / 'convert.log'})" if pid else
                      "conversion: nothing to do" if library.converter() and not library.running() else
                      "conversion: already running" if library.running() else
                      "conversion: no converter configured (optional); text comes from pdftotext")
        elif a.what == "convert":
            if a.background:
                pid = library.convert_in_background(retry=a.retry)
                print(f"started (process {pid}, log {library.root() / 'convert.log'})" if pid else "nothing started "
                      "(nothing to do, no converter, or one is running): sb papers status")
            else:
                rep = library.convert(retry=a.retry)
                print(f"{len(rep['converted'])} converted, {len(rep['failed'])} failed")
        else:
            rows = library.status()
            for r in rows:
                print(f"{r['state']:<10} {r['sha256'][:12]}  {', '.join(r['citekeys'])}")
            n = {s: sum(r["state"] == s for r in rows) for s in ("converted", "pending", "failed")}
            run = library.running()
            print(f"{len(rows)} papers: {n['converted']} converted, {n['pending']} pending, {n['failed']} failed; "
                  + (f"conversion running (process {run})" if run else "no conversion running")
                  + ("" if library.converter() else "; no converter configured (optional)"))
    except RuntimeError as e:
        sys.exit(str(e))


def cmd_lineage(a):
    """Data appendix: every table behind a recorded result, with contract metadata."""
    from . import config, contracts, results, tables
    p, h = config.project(), config.hub()
    used: dict[str, set] = {}
    for v in results.load(p).values():
        for t, snap in (v.get("provenance", {}).get("data") or {}).items():
            used.setdefault(t, set()).add(snap)
    rows = []
    for t in sorted(used):
        c = contracts.find(t, hub_root=h.root, registry=h.registry, project_root=p.root)
        snaps = ", ".join(str(s) for s in sorted(x for x in used[t] if x is not None)) or "--"
        rows.append([f"\\texttt{{{t.replace('_', chr(92) + '_').replace('.', '.' + chr(92) + 'allowbreak ')}}}", c.title if c else "--",
                     ", ".join(c.sources) if c else "--", c.license if c else "--", snaps])
    path = p.root / "tables" / "data_lineage.tex"
    tables._write(path, ["Table", "Content", "Source", "Licence", "Snapshot"],
                  [[r[0]] + [tables._esc(x).replace("\\_", "\\_\\allowbreak ") for x in r[1:]] for r in rows],
                  ">{\\raggedright}p{0.25\\linewidth}>{\\raggedright}p{0.25\\linewidth}>{\\raggedright}p{0.12\\linewidth}>{\\raggedright\\arraybackslash}p{0.16\\linewidth}r", None, set(), rows)
    print(f"wrote {path} ({len(rows)} tables)")


def cmd_sync(a):
    from . import deliverable
    rep = deliverable.sync()
    for folder, changed in rep.items():
        print(f"{folder}: {len(changed)} files updated" + (f" ({', '.join(changed[:8])}{', ...' if len(changed) > 8 else ''})" if changed else ""))
    if not rep:
        print("nothing to sync (no deliverable that reads generated/)")


def cmd_build(a):
    from . import deliverable
    try:
        rep = deliverable.build()
    except RuntimeError as e:
        sys.exit(str(e))
    for folder, outcome in rep.items():
        print(f"{folder}: {outcome}")
    if not rep:
        print("no deliverable to build")


def cmd_handover(a):
    from . import handover
    doc = handover.build()
    n = sum(len(d["sections"]) for d in doc["deliverables"])
    print(f"wrote dist/handover: {n} sections, {len(doc['files'])} files")
    for d in doc["deliverables"]:
        if d["unconverted"]:
            print(f"warning: {d['name']}: LaTeX commands left as they are: {' '.join(d['unconverted'])}")
    for x in doc["problems"]:
        print("warning:", x)


def cmd_flatten(a):
    from . import deliverable
    try:
        for f in deliverable.flatten():
            print("wrote", f)
    except RuntimeError as e:
        sys.exit(str(e))


def cmd_review_edits(a):
    from . import deliverable
    try:
        rep = deliverable.review(since=a.since)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"changes since {rep['since'][:12]} (the last agent commit, or the given reference)")
    if not rep["files"]:
        print("no section was edited")
        return
    for name, info in rep["files"].items():
        if info.get("deleted"):
            print(f"\n{name}: deleted")
            continue
        print(f"\n{name}: {info['added_lines']} new or changed lines")
        if info["cites"]:
            print("  citations to verify:", ", ".join(info["cites"]))
        if info["results"]:
            print("  results used:", ", ".join(info["results"]))
        for ln in info["typed_numbers"]:
            print("  number typed by hand?  ", ln[:110])
    print("\nnext: sb check; then the verifier on the files above (changed statements only). "
          "Edit these sections by diff; do not regenerate them.")


def cmd_ui(a):
    from . import ui
    if a.build:
        try:
            ui.build_frontend()
        except RuntimeError as e:
            sys.exit(f"sb ui: {e}")
    try:
        ui.serve(a.port, open_browser=not a.no_open, bridge=not a.no_bridge)
    except OSError as e:
        sys.exit(f"sb ui: cannot listen on 127.0.0.1:{a.port} ({e}); is it running already? Try --port")


def cmd_note(a):
    from . import notes
    fields = {k: getattr(a, k) for k in ("kind", "status", "text", "prompt", "deliverable") if getattr(a, k) is not None}
    try:
        if a.what == "list":
            rows = notes.load()
            for n in rows:
                print(f"{n['id']}  {n.get('status', ''):<9}{n.get('kind', ''):<13}{n.get('title', '')}")
            print(f"{len(rows)} notes")
        elif a.what == "add":
            if not a.args:
                sys.exit('usage: sb note add "TITLE" [--kind K] [--status S] [--text T] [--prompt P]')
            print("added", notes.add(title=" ".join(a.args), **fields)["id"])
        elif a.what == "set":
            if not a.args:
                sys.exit("usage: sb note set ID [--title T] [--kind K] [--status S] [--text T] [--prompt P]")
            if a.title is not None:
                fields["title"] = a.title
            print("updated", notes.update(a.args[0], **fields)[1]["id"])
        else:
            if not a.args:
                sys.exit("usage: sb note rm ID")
            print("removed", notes.remove(a.args[0])["id"])
    except (KeyError, ValueError) as e:
        sys.exit(str(e).strip("'\""))


def cmd_workspace(a):
    from . import ui
    print("wrote", ui.write_workspace(a.path))


def cmd_hook(a):
    """Never fails and never blocks: a hook that exits non-zero would disturb the agent it observes."""
    import json
    try:
        from . import activity
        activity.record(json.loads(sys.stdin.read() or "{}"))
    except Exception:
        pass


def cmd_publish(a):
    from . import publish
    rep = publish.build()
    for w in rep["warnings"]:
        print("warning:", w)
    for e in rep["errors"]:
        print("ERROR:  ", e)
    print(f"bundle: dist/public ({len(rep['files'])} files), data: {rep['data'] or 'none'}")
    if rep["errors"]:
        sys.exit("not publishable -- fix the errors above")
    if a.push:
        from . import config
        p, h = config.project(), config.hub()
        pub = p.meta.get("publish", {}) or {}
        repo = pub.get("repo") or p.slug.replace("_", "-")
        _user_only(f"Push dist/public to github.com/{h.github_owner}/{repo} ({pub.get('visibility', 'private')})", repo)
        print("pushed:", publish.push(message=a.message or f"Release {datetime.now(timezone.utc):%Y-%m-%d}"))
    else:
        print("ready. Inspect dist/public, upload dist/data, then: sb publish --push")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--data-root"); s.add_argument("--projects-dir")
    s.add_argument("--github-owner", help="GitHub user or organisation for `sb publish --push`")
    s.add_argument("--defaults", action="store_true", help="take ~/research-lake and ~/Documents/research without asking")
    s.add_argument("--force", action="store_true", help="overwrite an existing user configuration")
    s.add_argument("--shortcut", action="store_true", help="also put a desktop icon that starts the web view (asked in a terminal)")
    s.set_defaults(f=cmd_init)
    s = sub.add_parser("doctor"); s.add_argument("--json", action="store_true", help="the system report as data")
    s.set_defaults(f=cmd_doctor)
    s = sub.add_parser("install"); s.add_argument("what", nargs="?", default="all", choices=["all", "path", "skill", "agents", "hooks", "shortcut"])
    s.add_argument("--bin", help="folder on PATH for the `sb` launcher (default ~/.local/bin)"); s.set_defaults(f=cmd_install)
    s = sub.add_parser("update", help="pull the checkout and reinstall, keeping the extras that are installed")
    s.add_argument("--extra", action="append", help="also install this extra (word, linkedin, sql, browser); repeatable")
    s.add_argument("--no-pull", action="store_true", help="reinstall only, without git pull")
    s.add_argument("--no-frontend", action="store_true", help="do not rebuild the web view")
    s.add_argument("--dry-run", action="store_true", help="print the steps without running them")
    s.set_defaults(f=cmd_update)
    s = sub.add_parser("run"); s.add_argument("steps", nargs="*"); s.set_defaults(f=cmd_run)
    s = sub.add_parser("which"); s.add_argument("what", choices=sorted(WHICH)); s.set_defaults(f=cmd_which)
    s = sub.add_parser("new"); s.add_argument("slug"); s.add_argument("--title", required=True)
    s.add_argument("--dir", help="parent folder (default: the hub, [projects] dir, or the current folder)")
    s.add_argument("--deliverable", help="LaTeX template (a name from [templates.latex] or a folder), or `markdown` for prose without LaTeX")
    s.add_argument("--lang", choices=["de", "en"], default="en")
    s.add_argument("--empty", action="store_true", help="drop the worked example analysis")
    s.add_argument("--kind", choices=["study", "desk"], default="study",
                   help="study: one question, hypotheses, a paper; desk: ongoing research on a topic, pieces instead of a paper")
    s.set_defaults(f=cmd_new)
    sub.add_parser("status").set_defaults(f=cmd_status)
    s = sub.add_parser("check"); s.add_argument("--offline", action="store_true"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("freeze"); s.add_argument("--force", action="store_true")
    s.add_argument("--amend", action="store_true", help="accept changes that a new entry under amendments: explains")
    s.set_defaults(f=cmd_freeze)
    s = sub.add_parser("snap"); s.add_argument("url"); s.add_argument("--title", required=True)
    s.add_argument("--publisher"); s.add_argument("--note")
    s.add_argument("--date", help="when the page was published (YYYY-MM-DD); read from the page when left out")
    s.add_argument("--new", action="store_true", help="register again even if the same bytes are already a source")
    s.set_defaults(f=cmd_snap)
    s = sub.add_parser("unblock"); s.add_argument("source"); s.add_argument("host", nargs="?")
    s.set_defaults(f=cmd_unblock)
    s = sub.add_parser("source", help="read an archived source or paper; `sb source set W-xxxx --title ...` corrects its name")
    s.add_argument("id", help="W-xxxx, a citation key, `set`, or `dates` (publication dates read from the archived copies)"); s.add_argument("sid", nargs="?", help="with `set`: the W-xxxx to change")
    s.add_argument("--grep", help="passages around each hit (overlapping ones merged), numbered, with a count")
    s.add_argument("--chars", type=int, default=4000, help="characters to print (default 4000; 0 for all)")
    s.add_argument("--page", type=int); s.add_argument("--out", help="write the whole text to this file")
    s.add_argument("--write", action="store_true", help="with `dates`: record the dates that were found")
    for opt in ("title", "publisher", "author", "date"):
        s.add_argument(f"--{opt}", help="with `set`: the new value")
    s.set_defaults(f=cmd_source)
    s = sub.add_parser("toolkit", help="an organisation's own code beside Sourcebound: list, check, skills, run (in its own environment)")
    s.add_argument("what", choices=["list", "check", "skills", "run"]); s.add_argument("name", nargs="?")
    s.add_argument("args", nargs=argparse.REMAINDER, help="with run: SCRIPT (skill:<id>/scripts/x.py, or a path in the checkout) and its arguments")
    s.add_argument("--cwd", help="with run: the folder to run in (default: the checkout)")
    s.set_defaults(f=lambda a: __import__("sourcebound.toolkits", fromlist=["cmd"]).cmd(a))
    s = sub.add_parser("figure", help="figures for pieces: `sb figure crop W-xxxx --page N --box l,t,r,b --out FILE` cuts one out of a PDF")
    fsub = s.add_subparsers(dest="what", required=True)
    c = fsub.add_parser("crop", help="cut a region of a registered PDF's page into a PNG (the archived copy is read)")
    c.add_argument("id", help="W-xxxx of a registered PDF"); c.add_argument("--page", type=int, required=True)
    c.add_argument("--box", help="left,top,right,bottom in percent of the page")
    c.add_argument("--grid", action="store_true", help="write the whole page with a 10 %% grid instead, to read the box off")
    c.add_argument("--no-trim", action="store_true", help="keep the white page margin inside the box")
    c.add_argument("--dpi", type=int, default=300); c.add_argument("--out", help="the PNG to write (e.g. pieces/ID/figures/name.png)")
    c.set_defaults(f=cmd_figure)
    s = sub.add_parser("papers"); s.add_argument("what", choices=["sync", "convert", "status"])
    s.add_argument("--background", action="store_true", help="convert detached from this session")
    s.add_argument("--retry", action="store_true", help="also retry papers whose conversion failed")
    s.add_argument("--no-convert", action="store_true", help="sync: do not start the conversion")
    s.set_defaults(f=cmd_papers)
    s = sub.add_parser("datasource"); s.add_argument("what", choices=["add", "docs", "list", "set", "test", "rm"])
    s.add_argument("id", nargs="?"); s.add_argument("items", nargs="*")
    s.add_argument("--name"); s.add_argument("--url"); s.add_argument("--access", default="api")
    s.add_argument("--auth-env"); s.add_argument("--connection-env"); s.add_argument("--mcp")
    g = s.add_argument_group("database connection (add, set)")
    g.add_argument("--driver", choices=["mssql", "postgresql", "mysql", "sqlite", "duckdb"])
    g.add_argument("--server"); g.add_argument("--port", type=int); g.add_argument("--database")
    g.add_argument("--auth", choices=["sql", "windows", "none"], help="sql: user and password; windows: SQL Server only")
    g.add_argument("--user"); g.add_argument("--password-env", help="NAME of the environment variable with the password")
    g.add_argument("--encrypt", action=argparse.BooleanOptionalAction, default=None, help="SQL Server (default on)")
    g.add_argument("--trust-server-certificate", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--ssl-mode", choices=["disable", "prefer", "require", "verify-full"], help="PostgreSQL")
    g.add_argument("--timeout", type=int, help="seconds to wait when testing (default 15)")
    g.add_argument("--path", help="sqlite and duckdb: the database file")
    s.set_defaults(f=cmd_datasource)
    s = sub.add_parser("ingest"); s.add_argument("file"); s.add_argument("--source", required=True)
    s.add_argument("--note"); s.set_defaults(f=cmd_ingest)
    s = sub.add_parser("lake"); s.add_argument("what", choices=["tables", "snapshots", "sql", "export"])
    s.add_argument("args", nargs="*"); s.set_defaults(f=cmd_lake)
    s = sub.add_parser("bib"); s.add_argument("what", choices=["sync", "search", "add", "import", "link"])
    s.add_argument("args", nargs="*"); s.set_defaults(f=cmd_bib)
    sub.add_parser("lineage").set_defaults(f=cmd_lineage)
    sub.add_parser("sync").set_defaults(f=cmd_sync)
    sub.add_parser("build").set_defaults(f=cmd_build)
    sub.add_parser("handover").set_defaults(f=cmd_handover)
    sub.add_parser("flatten").set_defaults(f=cmd_flatten)
    s = sub.add_parser("review-edits"); s.add_argument("since", nargs="?"); s.set_defaults(f=cmd_review_edits)
    s = sub.add_parser("publish"); s.add_argument("--push", action="store_true"); s.add_argument("--message")
    s.set_defaults(f=cmd_publish)
    s = sub.add_parser("ui"); s.add_argument("--port", type=int, default=5210)
    s.add_argument("--no-open", action="store_true", help="do not open the browser")
    s.add_argument("--no-bridge", action="store_true", help="do not start the agent bridge")
    s.add_argument("--build", action="store_true", help="build the frontend first (needs Node.js; once, and after an update)")
    s.set_defaults(f=cmd_ui)
    s = sub.add_parser("note"); s.add_argument("what", choices=["list", "add", "set", "rm"]); s.add_argument("args", nargs="*")
    for opt in ("title", "kind", "status", "text", "prompt", "deliverable"):
        s.add_argument(f"--{opt}")
    s.set_defaults(f=cmd_note)
    s = sub.add_parser("workspace"); s.add_argument("path", nargs="?"); s.set_defaults(f=cmd_workspace)
    sub.add_parser("hook").set_defaults(f=cmd_hook)
    if (argv if argv is not None else sys.argv[1:])[:1] != ["hook"]:      # the hook runs before every tool call: keep it light
        from . import cli_more
        cli_more.add_parsers(sub)
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):      # Windows consoles and pipes default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    a.f(a)


if __name__ == "__main__":
    main()
