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
sb source W-0008 --grep word                    # read the archived copy
```

`sb doc` is how a folder of existing reports becomes material for a piece: each file used is
archived unchanged (by its hash) and gets an id to cite. PDF needs `pdftotext` to be read
back; Word, PowerPoint, HTML and text files are read directly.

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
recorded. It warns about numbers typed by hand (they must come with a citation), about a text
with no citation at all, and about a render that shows an older value of a result.

Nothing in Sourcebound posts to a network. `scheduled` records the intention; the frontend
shows the schedule and a preview; a plugin may prepare a bundle to post by hand.

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
sb pack install FOLDER | export FOLDER --design ID --template ID
sb render TARGET --template ID          # TARGET: a piece id, or deliverables/<name>
```

The checkout ships one neutral design and two renderers without dependencies (`markdown`,
`text`). An organisation's design is never part of the checkout: it lives in a pack that the
organisation keeps in its own repository, and `sb pack install` copies it into the registry
of a machine. That keeps Sourcebound independent of any one organisation while every output
of that organisation agrees in colour, type and logo.

An organisation that prefers an installable package over a folder wraps its pack in a small
private plugin: `register(api)` calls `api.pack(folder)`, and its designs and templates are
found on every machine where the package is installed, with no `sb pack install`. The registry
of a machine still wins over a plugin's pack, so one machine can try a change first.

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
