---
title: Commands
order: 2
---

# Commands

What the agent runs, and what you can run yourself in a terminal. `sb <command> --help` shows
every option.

## Set up and keep current

| Command | Does |
| --- | --- |
| `sb init` | the two folders you choose: data root and projects folder (once per machine) |
| `sb doctor` | what is installed and configured, and what is missing |
| `sb update` | the checkout, its packages, playbooks and this web view, keeping what is installed |
| `sb ui` | this web view (the desktop icon starts it too) |
| `sb pack install FILE.zip` | an organisation's designs, templates, playbooks and pages |
| `sb plugin list` · `sb plugin add FOLDER` | installed formats; a private plugin kept in a shared folder |

## Projects

| Command | Does |
| --- | --- |
| `sb new SLUG --title "…" --kind study` | a study: one question, hypotheses, a paper |
| `sb new SLUG --title "…" --kind desk` | a desk: a topic, pieces instead of a paper |
| `sb status` | where the project stands |
| `sb check` | what is wrong or missing (sources, numbers, frozen hypotheses) |

## Sources and numbers

| Command | Does |
| --- | --- |
| `sb snap URL` | archive a web page as a source (W-xxxx) |
| `sb doc FILE` | register a local file (a report, a PDF) as a source |
| `sb source W-xxxx --grep WORD` | read what was archived |
| `sb run analysis` | record every number from the committed analysis scripts |

## Pieces and formats

| Command | Does |
| --- | --- |
| `sb piece add "Title" --kind post` | a new piece in a desk |
| `sb piece check ID` | sources and numbers of a piece |
| `sb template guide ID` | what a template needs (e.g. the format of slides.yaml) |
| `sb render ID --template ID` | render a piece (or `deliverables/NAME`) |
| `sb piece open ID --browser` | show the piece in this app |
| `sb piece export ID` | save it: post text, carousel PDF, images, PowerPoint |
| `sb figure new NAME` · `render` · `list` | a project's own figures in the design's chart style |
| `sb figure crop W-xxxx --page N --box l,t,r,b` | cut a figure out of a registered PDF |

## In this app

The command palette (Ctrl+K) holds the app's commands; the assistant uses the same ones.
Among them: `piece.create`, `piece.format` and `piece.data` (write slides.yaml), `piece.render`,
`piece.export`, `deliverable.render`, `sql.query`. A render, the handover, a job run and every
decision about a piece wait for your approval when an agent asks for them.
