# Development guide

For people and coding agents working on Sourcebound itself. If you are doing research *with*
Sourcebound, read [`AGENTS.md`](AGENTS.md) (the rules for research agents) and the playbooks
in `skills/` instead. Note that `CLAUDE.md` in this folder imports `AGENTS.md`: an agent
started here follows the research rules too.

## Setup

```sh
make install         # uv sync; `sb` on PATH; playbooks and subagents for Claude Code
make test            # the core, offline
uv sync --extra word --extra linkedin && uv run pytest -q     # with the format plugins
```

Python 3.12 through [uv](https://docs.astral.sh/uv/). Windows: `uv sync`, `uv run sb install`,
`uv run pytest -q`.

| Path | Package | Notes |
| --- | --- | --- |
| `src/sourcebound` | `sourcebound` | the core and the `sb` command; no dependency on a plugin or the frontend |
| `plugins/word` | `sourcebound-word` | python-docx; installed by `uv sync --extra word` |
| `plugins/linkedin` | `sourcebound-linkedin` | Jinja2; a Chromium on the machine for PNG and PDF |
| `frontend/` | the web view | TypeScript and React on Werkbank; its own `AGENTS.md` |

## Commands

| Command | What it does |
| --- | --- |
| `make test` | core tests and the offline pipeline tests (`pytest tests pipelines`) |
| `uv run pytest -q` | everything that is installed; plugin tests skip when their extra is missing |
| `sb doctor` | the resolved configuration; `--json` gives the full report |
| `cd frontend && npm run typecheck && npm run build` | the web view |
| `cd frontend && npm run dev` | the web view with live reload, the data service and the agent bridge |

A change is done when the tests pass and, for anything on screen, you opened the web view and
used it. Tests never touch a real data root: the `isolated` fixture in `tests/test_core.py`
points every test at temporary folders. Do the same in trials by hand:

```sh
export XDG_CONFIG_HOME=/tmp/sb-trial/config
sb init --data-root /tmp/sb-trial/data --projects-dir /tmp/sb-trial/research
```

## How the code is laid out

```
src/sourcebound
  config        which configuration applies, the data root, the current project; file locks
  lake          the data lake: DuckLake catalog over Parquet, read / write / export, lineage
  contracts     YAML data contracts: validation on write, datapackage export
  fetch         the fetcher: pacing, robots.txt, stop markers, the immutable raw archive
  sources       custom and private sources: register entries, archived documentation, files, databases
  ledger        hypotheses, claims, web sources; cross-reference checks; freeze
  results       recorded numbers with script, commit and snapshot
  deliverable   LaTeX deliverable folders: sync, build, review of edits by a person
  handover      the format-neutral export; LaTeX to Markdown
  desk, pieces  desk projects and their pieces
  render        one Document for pieces and deliverables; dispatch to renderers; staleness
  plugins       discovery of plugins (entry points) and what they may register
  assets        designs, templates and packs in the registry
  jobs          scheduled pipelines
  connections   read-only SQL; the MCP register
  system        what is installed and configured, as data
  ui            the web view's local data service
  notes, activity   the deliverables manager; the log of what agents do
  publish       the publication bundle
  cli, cli_more the `sb` command
```

Imports go from `cli` and `ui` down to the modules; a module never imports `cli`. The core
never imports a plugin.

## Rules that are enforced by tests

- **A refused robots.txt allows nothing.** 401, 403, 5xx and an unreachable host mean "do not
  fetch"; only a missing file (other 4xx) allows everything.
- **A refusal stops the host.** 401/403/429/451/503 or a challenge page writes a stop marker;
  nothing reaches that host again until a person clears it at a terminal.
- **A token goes to its own host only.**
- **A frozen hypothesis cannot change silently.** `sb check` compares hashes.
- **Decisions belong to a person.** `sb unblock`, `sb publish --push` and setting a piece to
  `approved`, `scheduled` or `published` refuse to run without a terminal and a typed word.
- **SQL from the command line and the web view only reads.**
- **The web view's service answers this machine only** and serves files from a short list of
  folders.

Do not weaken one of these to make a task easier. If a rule is wrong, change the rule, its
test and `AGENTS.md` together.

## Core or plugin?

A change belongs in the core only if every user would want it and it adds no dependency.
A format is a plugin. An organisation's look is a pack and never enters this repository: no
logo, no corporate colour, no company name in tracked files.

### Writing a plugin

A plugin is a package with an entry point in the group `sourcebound.plugins` and a function
`register(api)`. It may register a renderer for a template kind, checks, a starting template,
commands and a pack of designs and templates; see [`docs/desks-and-formats.md`](docs/desks-and-formats.md) and the two
existing plugins. A renderer writes only below the output folder it is given and returns the
files, or `(files, notes)` when it adjusted something or could not do something.

Add the package under `plugins/`, an extra and a `[tool.uv.sources]` entry in the root
`pyproject.toml`, and tests under `plugins/<name>/tests/` that start with
`pytest.importorskip("<package>")`.

## The web view

Rules and layout are in [`frontend/AGENTS.md`](frontend/AGENTS.md). In short: the frontend
has no data of its own; every action is a command that does what an `sb` command does; display
elements that do not know Sourcebound live in `frontend/src/kit/`.

Werkbank is a dependency (`@werkbank/framework`, `@werkbank/bridge`) and is never edited
here. It had not published a release when this was written, so the two packages are in
`frontend/vendor/` as the tarballs that Werkbank's `npm run pack` writes (version 0.6.0, MIT).
Once a release exists, `npm run werkbank:update` in `frontend/` moves to it and the folder
can go.

## Known limits

- **Windows.** The tests of the core and of both format plugins run on Windows, macOS and Linux
  in CI, including the layout of slides in a real browser. Not yet tried on a Windows machine
  by hand: LaTeX (MiKTeX/TeX Live), Zotero and the paper store, a converter, SQL Server with
  Windows authentication, Word for Windows (opening and editing a rendered file), the web view.
- **Databases.** `sources.query` is tested against SQLite only.
- **Word.** Mathematics stays text, footnotes stay as written, macros of a `.dotm` are
  dropped, tracked changes are read as accepted. Layout was checked by script and preview,
  not by eye in Word.
- **Slides.** The line chart does not check lines against labels; two block types have no
  remedy of their own. There is no posting through an API: publishing is manual by decision.
- **Web view.** Tried in Chromium only. Running a job, a database SQL target and MCP server
  details were built without data to try them with. No static export.
- **Jobs.** No run under a real scheduler yet; `sb job schedule` prints the line to add.
- **Literature.** `sb bib import` writes into the Zotero library and is untested. The
  bibliography is BibLaTeX, not CSL JSON.
- **Working together.** Colleagues on one study, a shared registry and gates with several
  people are not designed yet.
- **Evaluation.** The workflow has run on few real studies. Treat the agent prompts and the
  hand-offs between phases as the least tested part.

## Conventions

- Commit messages: one short imperative line; a body where the reason is not obvious.
- Plain language in code comments, messages and documentation: short sentences, units with
  every number, dates as YYYY-MM-DD, no marketing words. Errors say what happened and what to do.
- No secrets, tokens or personal paths in tracked files. Tokens live in environment variables
  that a register entry names.
- Text files are UTF-8 with LF line endings; paths go through `pathlib`.
