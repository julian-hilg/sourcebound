---
name: content-desk
description: Run a Sourcebound desk as the lead agent: ongoing research on a topic that produces pieces (LinkedIn posts and infographics, notes, briefings, trade ideas, Word reports) without a paper first. Collect sources, record numbers, write a piece, check it, render it in a registered template and design, hand it to the user for approval. Use for "write a post about …", "make an infographic from this report", "keep following topic X", "turn these reports into a note", or any work in a project with `kind: desk`.
---

# Content desk: the lead's playbook

You are the lead of a **desk** (`project.yaml` has `kind: desk`). The hub rules in `AGENTS.md`
apply, with the desk table in section 1. This file is the order of work.

## 0. Orient

```sh
sb status                 # the desk and its sources
sb piece list             # what exists, in which status
sb template list          # formats this machine can render (kind, design)
sb design list
sb plugin list            # which formats are installed (docx, slides, ...)
```

Read the desk's `AGENTS.md` (topic, audience, what a good piece looks like) and `log.md`.
If the user asks for a format no installed plugin renders, say so; do not improvise the format.

## 1. Collect, with sources

- A web page: `sb snap URL --title "..." --publisher "..."` (archives it, gives `W-xxxx`).
- A report or any local file the user points to: `sb doc FILE --title "..." --publisher "..."`.
  For a folder of reports, register each file you will use; list the ones you skipped and why.
  Registering the same file again gives back its id ("already registered as W-xxxx"); do not
  use `--new` for that. A wrong title or publisher: `sb source set W-xxxx --publisher "..."`.
- Read what you registered: `sb source W-xxxx --grep word`. Quote from the archived copy only.
  `sb source` prints the first 4,000 characters and says so on its last line; read a long
  report whole with `sb source W-xxxx --out FILE` (a scratch file, not in the project) or
  search it with `--grep`. Footnotes (the report's own sources) come after the body, under
  `Footnotes`. Images and charts are not read: a number seen only in a figure needs another
  source that states it.
- Findings go into `research/notes/<topic>.md`, one statement per line with its source id.
- More than one sub-question: one `scout` per sub-question, in parallel; each writes one note.
- A fetch that is refused stops that host. Report it; use another source.

## 2. Numbers

- Computed from data: a script in `analysis/` records it (`sourcebound.results.record`), you
  commit, `sb run analysis`, and the text uses `{{result:key}}`. `sb run analysis` prints the
  keys each script recorded, with their values: read them before you use them.
- Computed from figures in a registered document: name it,
  `results.record("key", value, sources=["W-0001"])`. `sb piece check` then shows which
  source the result rests on. Cite that source next to the number in the text as well.
- Quoted from a source: write the number and cite the source in the same sentence. Take it from
  the archived text, with the unit and the date it refers to. Never round beyond the source.
  The same holds in `slides.yaml`: give each slide with a quoted number a `source:` line.

## 3. Write the piece

```sh
sb piece add "Working title" --kind post --template <id>     # kinds: post, note, idea, briefing, report
```

- `pieces/<id>/text.md`: the text. Notation: `{{result:key}}`, `[@W-0001]`, `[@W-0001, p. 3]`.
- Structured content a template needs sits beside it (a slide template reads `slides.yaml`; its
  README in the plugin lists the block types). One message per slide; the title states it.
- Write for the desk's audience, in the project language. Plain, specific, no hype. The first
  line of a post must carry the point without the rest.
- Put the prompt you were given into the card (`sb piece set <id> --prompt "..."`) so the piece
  can be redone.

## From one file to a post, in conversation

The user points at a file ("make a LinkedIn post about X.pdf") and then steers by message
("change the chart on slide 2", "shorter first line", "open it"). The loop:

1. `sb doc FILE --title "..." --publisher "..."` (once), read it with `sb source W-xxxx`.
   If the file is the desk's own work (a publisher under `own.publishers` in project.yaml, e.g.
   one's own study) and `self_citation: false`, it is where you find the facts, not what you
   cite: register and cite the original sources it names (`sb snap URL`, `sb doc`). Cite the
   own work only when the user says so, then `sb piece set ID --self-citation true`.
2. `sb piece add "Working title" --kind post` (template and design come from `piece_defaults`),
   then `text.md` and `slides.yaml` as in section 3, `sb piece check`, `sb render`.
3. Every render of a piece brings it up in an open web view (Post preview); `sb piece open ID`
   does the same without rendering. If no web view runs, say so: the desktop icon starts it.
4. A requested change: edit the content (`text.md`, `slides.yaml`), render again, say in one
   line what changed. A change of the *look* of this one piece (spacing, sizes, emphasis) goes
   into `pieces/<id>/style/style.css` (rules laid over the template's CSS: colours as
   `var(--c-…)`/`var(--p-…)`, fonts as `var(--f-…)`; nothing loaded from the web) and
   `pieces/<id>/style/style.yaml` (only `scale`, `empty_warn_pct`). Never edit the registered
   template or the design for one piece; a change every piece needs is a template change, which
   the user asks for separately.
5. When the user wants the files: `sb piece export ID` copies the newest renders, `post.txt` and
   the alt texts to `export.dir` of the desk (a folder `YYYYMMDD_slug`). It posts nothing and
   never deletes what it did not write.

## 4. Check, render, look

```sh
sb piece check <id>                       # fix every error; read every warning
sb render <id> --template <id>            # writes pieces/<id>/render/<template>/
```

- A number with no citation in its sentence (or, in `slides.yaml`, none on its slide) is a
  warning: record it, or cite its source. A cited number is listed as `info`: confirm each one
  against the archived source before you hand the piece over.

- A slide render fails when text overflows, labels collide or the design is not followed. Fix
  the content (shorter labels, fewer rows, split the slide); do not touch the template.
- Look at what was rendered (open the PNG or the document) before you hand it over.
- Have the `verifier` check a piece that makes more than a few factual statements: every
  statement against its archived source.

## 5. Hand over

- `sb piece set <id> --status review`, one line in `log.md`, commit with a `Co-Authored-By:`
  trailer.
- Tell the user where the render is and what you were unsure about.
- Approving, scheduling (`--at`) and publishing are the user's. You never set these states and
  you never post, send or upload anything.

## When the user edited the output

- Text changed in `text.md`: keep their wording; change by targeted edits only.
- A Word file they edited: `sb word status FILE` shows what they changed and which numbers are
  stale; `sb word refresh FILE` updates the numbers in place; `sb word pull FILE` brings their
  text back as Markdown. Never render over their file.
