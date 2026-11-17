# Desks, pieces and formats

Sourcebound began as a workflow for one study that ends in a paper. This page describes the
part that reaches further: ongoing research on a topic, small outputs without a paper first,
and output formats beyond LaTeX in an organisation's own design.

## The layers

```
Evidence     sources (archived pages, documents, literature), the claim ledger,
             recorded results, the data lake                                   -- always
Content      deliverables (a paper, a report) and pieces (a post, a note)      -- text + references to evidence
Formats      renderers (plugins) x templates x designs                         -- optional packages
Channels     the person publishes; Sourcebound prepares and keeps the schedule
```

Evidence is the same for everything. A LinkedIn post and a working paper cite the same
archived source and use the same recorded number; neither holds a copy. Content is written
once, in Markdown with the handover notation. A format is a way to render content, and no
format is privileged: LaTeX is built in for historical reasons, Word and slides are plugins.

## Two kinds of project

| | Study | Desk |
| --- | --- | --- |
| Create | `sb new SLUG --title "..."` | `sb new SLUG --title "..." --kind desk` |
| For | one question, tested | a topic, followed for as long as it matters |
| Outputs | deliverables (`deliverables/<name>/`) | pieces (`pieces/<id>/`) |
| Discipline | brief, hypotheses frozen before analysis, review, gates G1 to G3 | every statement has a registered source; publishing is the person's decision |

A study can have pieces too (the post about the paper), and a desk can grow a study when a
question needs testing. The evidence carries over because it has the same form in both.

## Sources for lighter work

```sh
sb snap URL --title "..." --publisher "..."     # a web page: archived, id W-0007
sb doc FILE --title "..." --publisher "..."     # a report, a PDF, a Word file: archived, id W-0008
sb source W-0008                                # read the archived copy (the first 4,000 characters)
sb source W-0008 --grep word                    # every passage with "word", numbered, with a count
sb source W-0008 --out /tmp/w0008.txt           # the whole text in a file, for a long report
sb source set W-0008 --publisher "..."          # correct the title or publisher afterwards
```

Both commands record when the source was published: `--date YYYY-MM-DD`, or else the date the
file itself declares (a page's publication metadata, a PDF's creation date) or a date written in
the title. A source without one is cited as "n.d."; `sb source dates [--write]` reads the dates
of sources registered earlier, and `sb source set W-0008 --date ...` corrects one.

`sb doc` is how a folder of existing reports becomes material for a piece: each file used is
archived unchanged (by its hash) and gets an id to cite. The same file registered again keeps
its id (`already registered as W-0008`); `--new` forces a second entry. PDF needs `pdftotext`
(or `pypdf`) to be read back; Word, PowerPoint, HTML and text files are read directly.

`sb source` says when it cuts: the last line gives how many characters were shown of how many
(`--chars N` for more, `--chars 0` for all). Overlapping `--grep` passages are merged.
From a Word file it reads the body, then footnotes and endnotes under a `Footnotes` /
`Endnotes` line, numbered as in the text (`[^1]`); table cells are separated by ` | `, one row
per line; field codes and the second copy of a text box are left out. Images and charts are
not text: the header says how many a document holds, so a number in a figure is quoted only
from a source that states it in words.

## Pieces

```
pieces/<id>/
  piece.yaml     title, kind, template, design, status, channel, scheduled_at
  text.md        the text: {{result:key}}, [@W-0007], [@W-0007, p. 3]
  slides.yaml    structured content a template needs (optional; depends on the template)
  render/<template>/   what `sb render` wrote, with render.json (template, design, values shown)
```

```sh
sb piece add "Title" --kind post --template ID     # idea -> draft -> review (agents stop here)
sb piece check [ID]                                # sources registered, results recorded, typed numbers, stale renders
sb render ID --template ID [--design ID]
sb piece set ID --status approved                  # the person, in a terminal, typed confirmation
sb piece set ID --at "2026-11-20 08:30"            # scheduled; `sb piece due` lists what is due
sb piece set ID --status published --url URL
```

`sb piece check` fails on a cited source that is not registered and on a result that was not
recorded. It warns about a text with no citation at all and about a render that shows an older
value of a result.

Numbers typed by hand are checked in `text.md` and in every string of the piece's data files
(`slides.yaml`: titles, kpis, bar texts, labels, notes). A number here is a decimal, a
percentage, an integer with a thousands separator (`41.499`), a number with a currency, unit or
scale (`1.800 €`, `1 Mio.`, `150 Mrd. €`, `10x`) or a bare integer of three or more digits.
Years, dates, times, `§ 34f`, `Art. 6`, page numbers in a citation, ids, hashtags and the levels
1, 5, 10, 90, 95 and 99 % are not counted. A number whose sentence cites a source is listed as
info ("quoted with a citation in the same sentence", to confirm against the source); one
without a citation is a warning. In `slides.yaml` a slide's `source` line counts as the
citation for everything on that slide; positions in the reported path count from 1
(`slides[3].blocks[1].items[1].n`).

A number computed in `analysis/` from figures of a registered document names that document:

```python
results.record("verm.je_dach", 16211 / 139, fmt="{:.0f}", sources=["W-0001"])
```

The ids (`W-xxxx` or citation keys) are stored in the result's provenance. An id that is not
registered gives a warning, not an error. Such a result no longer gets the "names no lake
table" warning of `sb check`, and `sb piece check` shows, for each `{{result:key}}` a piece
uses, the sources or lake tables it rests on. `sb run analysis` prints after each script the
keys it recorded, with their values (20 per script, then the count of the rest).

Rendered files (`*.png`, `*.pdf`, `*.html`, `*.docx`, `*.pptx` under `pieces/*/render/`) are
not committed in a new desk: its `.gitignore` leaves them out, because each render would add
another copy of several MB to git. `render.json`, `preview.json` and `layout.json` stay tracked;
the staleness check and the web view read files on disk, and `sb render` makes the files again.
A desk created earlier gets the same by adding those lines to its `.gitignore`
(and `git rm --cached` for files already committed).

`sb new` turns hyphens in a slug into underscores (`desk-2026` becomes `desk_2026`), because
the slug also names the project's lake schema `proj_<slug>`. `sb piece add` makes an id from
the date and the title's first words, cut at a word boundary (about 28 characters), and sets
the channel when `project.yaml` names exactly one. `sb status` on a desk shows the topic, the
sources registered, the pieces by status and the number of recorded results.

Nothing in Sourcebound posts to a network. `scheduled` records the intention; the frontend
shows the schedule and a preview; a plugin may prepare a bundle to post by hand. The preview
shows the post under the name and headline set in `project.yaml` when a desk posts for someone
else, such as an organisation's page:

```yaml
preview: {author: "Example GmbH", headline: "Asset management"}
```

Without it, the preview uses the name under Settings, Post preview.

## Formats: renderers, templates, designs, packs

| Thing | Where | What it is |
| --- | --- | --- |
| Renderer | a plugin (`sb plugin list`) | code that turns a document into files of one **kind** (`docx`, `slides`, `markdown`, `text`) |
| Template | `<registry>/templates/<id>/` | files for one kind plus `template.yaml` (`kind:`, `design:`, `for:`) |
| Design | `<registry>/designs/<id>/design.yaml` | colours, palette, fonts, logo, chart rules: data that every renderer reads |
| Pack | any folder with `designs/` and `templates/` | how an organisation carries its look between machines |

```sh
sb plugin list
sb design list | show ID | new ID --name "Organisation"
sb template list | new ID --kind KIND --design ID | add FOLDER
sb pack install FOLDER|FILE.zip | export FOLDER|FILE.zip --design ID --template ID
sb render TARGET --template ID          # TARGET: a piece id, or deliverables/<name>
```

A pack travels as a folder or as one `.zip`. A zip is checked completely before anything is
copied, and refused as a whole with every problem named:

| Rule | |
| --- | --- |
| Content | `designs/<id>/`, `templates/<id>/`; at the top `pack.yaml`, `README*`, `LICENSE*`; one folder around everything is fine |
| Paths | no absolute paths, no `..`, no links; ids in lowercase letters, digits, `-`, `_` |
| File types | data only: YAML/JSON/text, Office files and templates, images, fonts, CSS/HTML/Jinja, LaTeX styles; `layout.js` inside a template (the slide layout check). No programs, no Python |
| Size | at most 2,000 files, 200 MB unpacked, 50 MB per file, no file that unpacks to more than 100 times its size |
| Completeness | each design folder has `design.yaml`, each template folder `template.yaml` |

`pack.yaml` (optional) gives `name`, `version` and `description`; `sb pack export NAME.zip`
writes one. An install from a folder reads the folder's `pack.yaml` (else the folder's name).
It records the pack in `<registry>/packs/<name>.yaml`: name, version, the path it came from,
the sha256 of the source (the zip file, or the folder's files) and of its designs and templates,
the date and the ids. Ids that were already installed are replaced; the install lists which of
them differ from what was installed (and where that came from) and which are the same, and says
when the pack's content differs from its last install.

The checkout ships one neutral design and two renderers without dependencies (`markdown`,
`text`). An organisation's design is never part of the checkout: it lives in a pack that the
organisation keeps in its own repository, and `sb pack install` copies it into the registry
of a machine. That keeps Sourcebound independent of any one organisation while every output
of that organisation agrees in colour, type and logo.

An organisation that prefers an installable package over a folder wraps its pack in a small
private plugin: `register(api)` calls `api.pack(folder)`, and its designs and templates are
found on every machine where the package is installed, with no `sb pack install`. The registry
of a machine still wins over a plugin's pack, so one machine can try a change first.

A Word template can say `sources: {word: store}` in its `template.yaml` (the default): the cited
sources are then also in Word's own store (References > Manage Sources), so a person can cite
them with Word's commands. `word: fields` also turns the rendered citations into Word's citation
fields; Word then formats them in its own citation style when it updates fields, which may differ
from the template's (seen in Word for Mac: numbered citations became author and year). `word: off`
writes neither.

Templates are made at the desk, not in the frontend: `sb template new` asks the plugin for a
starting template built from a design, and the files are then edited with the tool the
format belongs to (Word, an HTML editor).

### Installing a format

Plugins are separate packages with their own dependencies, in `plugins/` of the checkout:

```sh
uv sync --extra word            # Word documents (python-docx)
uv sync --extra linkedin        # slides, infographics and posts (Jinja2; a Chromium for PNG and PDF)
uv sync --all-extras
```

The standard installation (`uv sync`) has neither, nor the frontend.

### Writing a plugin

```toml
[project.entry-points."sourcebound.plugins"]
video = "sourcebound_video:register"
```

```python
def register(api):
    api.renderer("video", render, title="Explainer video", outputs=(".mp4",))
    api.check("video", check)                 # check(doc, template, design) -> list of problems
    api.scaffold("video", scaffold)           # scaffold(folder, design): a starting template
    api.command("video", setup_parser, run)   # adds `sb video ...`
    api.pack(Path(__file__).parent / "pack")  # designs/ and templates/ the plugin brings
    api.converter(".mp4", ".gif", to_gif)     # convert(path, out) -> Path: used by `sb deliver`

def render(doc, template, design, out):       # -> list of files written below `out`
    ...
```

`doc` is a `sourcebound.render.Document`: sections of Markdown, `results`, `tables`,
`figures`, `references`, `web_sources`, `data` (the YAML files beside a piece's text), `meta`.
Helpers: `render.fill` (numbers in, citations formatted by a callback), `render.cited`,
`render.source_line`, `render.cite_label`, `render.plain_text`. A renderer writes only below
`out`; the core adds `render.json` with the values shown, so staleness can be detected later.

### Delivering

```sh
sb deliver p1 --template firm-report --template firm-post --pdf --email --zip
```

renders the piece (or `deliverables/NAME`) with each template, adds converted formats (`--pdf`:
each `.docx` also as `.pdf`, through the Word plugin), and collects everything in
`dist/deliver/<name>-<date>/` with `MANIFEST.json` (files with sha256, templates, commit, the
numbers shown) and `README.txt`. `--email [ADDRESS]` adds an unsent e-mail (`.eml`, `X-Unsent:
1`): subject, the text as plain text and the PDFs attached; Outlook opens it as a draft. Without
`--template` the piece's own template is used.

Nothing is sent, posted or uploaded. A piece that is not `approved` is delivered for review
only, and the manifest and README say so.

## For an organisation

What a team shares, and where it lives:

| Shared | How |
| --- | --- |
| Design and templates | a pack in the organisation's repository; `sb pack install` on each machine |
| Contracts, source register, jobs, MCP servers | the registry (`<data root>/registry/`), which can itself be a git repository |
| Projects (studies and desks) | one git repository each |
| Data | each machine's lake, rebuilt from the raw archive, or a shared catalog (see `data-access.md`) |

What stays personal: tokens (environment variables), the Zotero library, the browser layout
of the frontend.
