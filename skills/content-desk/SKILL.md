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
- Read what you registered: `sb source W-xxxx --grep word`. Quote from the archived copy only.
- Findings go into `research/notes/<topic>.md`, one statement per line with its source id.
- More than one sub-question: one `scout` per sub-question, in parallel; each writes one note.
- A fetch that is refused stops that host. Report it; use another source.

## 2. Numbers

- Computed from data: a script in `analysis/` records it (`sourcebound.results.record`), you
  commit, `sb run analysis`, and the text uses `{{result:key}}`.
- Quoted from a source: write the number and cite the source in the same sentence. Take it from
  the archived text, with the unit and the date it refers to. Never round beyond the source.

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

## 4. Check, render, look

```sh
sb piece check <id>                       # fix every error; read every warning
sb render <id> --template <id>            # writes pieces/<id>/render/<template>/
```

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
