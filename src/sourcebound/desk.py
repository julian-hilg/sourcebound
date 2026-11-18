"""Desk projects: ongoing research on a topic, without a final deliverable.

    sb new SLUG --title "..." --kind desk

A study answers one question and ends with a paper.  A desk follows a topic for as long as it
matters and produces pieces along the way: posts, notes, trade ideas, briefings.  It has no
hypotheses to freeze and no gates G1 and G2; it keeps the two rules that make the work worth
anything: every statement has a registered source, and every number is a recorded result or
is quoted with its source.  Publishing stays the person's decision.

    project.yaml          kind: desk, the topic, the channels
    research/notes/       findings, one file per sub-topic or date
    evidence/             sources.yaml (archived pages, documents), claims.yaml (optional ledger)
    analysis/, results/   scripts that record numbers (the same `sourcebound.results`)
    pieces/               the outputs (`sb piece`)
    log.md                decisions
"""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

CARD = """# Project card: read by sb, the agents and the frontend.
slug: {slug}
title: {title}
lang: {lang}                       # en | de
kind: desk                     # ongoing research on a topic; outputs are pieces, not a paper
created: {today}
phase: ongoing
topic: ""                      # one sentence: what this desk follows and for whom
channels: []                   # where pieces go, e.g. [linkedin, newsletter, internal]

# Defaults for new pieces (ids from `sb template list` / `sb design list`)
piece_defaults:
  template: ""
  design: ""

# Who "we" are: with self_citation: false, `sb piece check` refuses a citation of a source by
# these publishers (one's own study or report); a piece cites the original sources instead,
# unless the person asks for it (`sb piece set ID --self-citation true`).
# own:
#   publishers: []
# self_citation: false

# Where `sb piece export ID` copies a piece's files (render, post text, alt texts), e.g. a shared
# marketing folder; each export is a folder named after `name` ({{date}}: the planned posting day,
# else today, as YYYYMMDD; {{slug}}: the piece id without its date; {{id}}: the id).
# export:
#   dir: ""
#   name: "{{date}}_{{slug}}"

# Who posts the pieces, as the post preview of the web view shows it (e.g. an organisation's page);
# without it the preview uses the name under Settings -> Post preview.
# preview:
#   author: ""
#   headline: ""

# Lake tables this desk reads (shared domains) and owns (proj_<slug>)
reads: []
owns: []
"""

AGENTS = """# {title}

A **desk**: ongoing research on one topic. The Sourcebound rules apply (hub `AGENTS.md`), with
the lighter paradigm for desks (section 1 there): no hypotheses to freeze, no paper to write.

- **Topic:** (from `project.yaml`)
- **Audience and channels:**
- **What a good piece looks like here:** (length, tone, what to avoid)

## How work runs here

1. **Collect.** Findings go into `research/notes/<topic>.md`, each with its source. Archive a web
   page with `sb snap URL --title "..."`; bring in a report or any local file with
   `sb doc FILE --title "..."`. Both give an id (`W-0001`) to cite.
2. **Count.** A number that comes from data is recorded by a script in `analysis/` with
   `sourcebound.results.record(...)` and used as `{{{{result:key}}}}`; computed from figures of a
   registered document, it names it: `record(..., sources=["W-0001"])`. A number quoted from a
   source is written out with its citation in the same sentence.
3. **Write a piece.** `sb piece add "Title" --kind post --template ID`; the text goes into
   `pieces/<id>/text.md`, structured content a template needs (e.g. `slides.yaml`) next to it.
4. **Check.** `sb piece check <id>`: every cited source registered, every result recorded.
5. **Render.** `sb render <id> --template ID` writes `pieces/<id>/render/<template>/`.
6. **Hand to the person.** Status `review`. Approving, scheduling and publishing are the person's
   decisions; an agent never sets them and never posts.

## Map

| Path | Content |
| --- | --- |
| `research/notes/` | findings with sources |
| `evidence/sources.yaml` | archived pages and documents (`W-xxxx`) |
| `evidence/claims.yaml` | optional claim ledger for statements used again and again |
| `analysis/`, `results/` | scripts and the numbers they recorded |
| `pieces/` | the outputs |
| `log.md` | decisions, newest at the bottom |
"""

# Rendered files are large and are made again by `sb render`; every render would add a copy to
# git. The manifests stay tracked: render.json (what was shown), preview.json, layout.json.
RENDER_IGNORE = ("# renders: sb render makes them again; the manifests (render.json, preview.json, layout.json) stay tracked\n"
                 + "".join(f"pieces/*/render/**/*.{x}\n" for x in ("png", "pdf", "html", "docx", "pptx")))

FILES = {
    "evidence/sources.yaml": "# Sources outside Zotero. Add with `sb snap URL --title ...` (a web page) or `sb doc FILE --title ...` (a document).\nsources: []\n",
    "evidence/claims.yaml": "# Optional claim ledger: statements this desk uses again and again, each with its evidence.\nclaims: []\n",
    "evidence/inbox.bib": "",
    "research/notes/README.md": "Findings, one file per sub-topic or date. Every statement names its source (`W-0001`, a citation key, `R:key`).\n",
    "analysis/README.md": "Scripts that record numbers with `sourcebound.results.record`. Run them with `sb run analysis`.\n",
    "pieces/README.md": "One folder per piece (`sb piece add`). `render/` inside a piece is written by `sb render`.\n",
    ".gitignore": "__pycache__/\n*.pyc\n.DS_Store\nThumbs.db\n~$*\ndist/\npieces/.removed/\npieces/.ids.lock\n" + RENDER_IGNORE,
}


def create(dest: Path, slug: str, title: str, lang: str = "en") -> None:
    import json
    today = date.today().isoformat()
    dest.mkdir(parents=True)
    (dest / "project.yaml").write_text(CARD.format(slug=slug, title=json.dumps(title, ensure_ascii=False), lang=lang, today=today), encoding="utf-8")
    (dest / "AGENTS.md").write_text(AGENTS.format(title=title), encoding="utf-8")
    (dest / "log.md").write_text("# Log\n\nOne line per decision: date, who, what, why. Newest at the bottom.\n\n"
                                 f"- {today} lead: desk created (`sb new --kind desk`).\n", encoding="utf-8")
    for rel, text in FILES.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    (dest / "results").mkdir()
    (dest / "results" / ".gitkeep").write_text("", encoding="utf-8")
    git = lambda *x: subprocess.run(["git", *x], cwd=dest, capture_output=True)
    if git("rev-parse", "--is-inside-work-tree").returncode != 0 or git("check-ignore", "-q", ".").returncode == 0:
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "Desk created (sb new --kind desk)")
