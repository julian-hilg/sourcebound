# Installing Sourcebound

Sourcebound has a small core and three optional parts. Install the core first; add the rest
when you need it.

| Part | What it adds | Needs |
| --- | --- | --- |
| **Core** | the `sb` command, the agents and playbooks for Claude Code, studies and desks, the data lake, LaTeX deliverables, the format-neutral handover | [uv](https://docs.astral.sh/uv/), git |
| **Word** (optional) | Word documents from `.docx`, `.dotx` and `.dotm` templates, with a round trip for files edited in Word | `uv sync --extra word` |
| **Slides and posts** (optional) | slides, infographics and post text from HTML templates, with a layout check | `uv sync --extra linkedin`, and Chrome, Edge or Chromium for PNG and PDF |
| **Web view** (optional) | a local frontend over all projects, the data lake and what is installed | Node.js 22 or newer (on Windows also inside WSL) |

## Requirements

| | |
| --- | --- |
| Operating system | macOS, Linux or Windows |
| [uv](https://docs.astral.sh/uv/) | installs Python 3.12 and the packages |
| git | every project is a git repository; results record the commit that produced them |
| A coding agent | [Claude Code](https://claude.com/claude-code) for the agent workflow. The `sb` command works without it. |
| Optional | a TeX distribution with `latexmk` and `biber` (only to compile LaTeX deliverables), Zotero 7 or newer with Better BibTeX (literature), poppler (`pdftotext`, `pdftoppm`) |

## Two folders you choose

Sourcebound keeps code, research and data apart. Decide on two folders before installing:

| Folder | What lives there | Typical place |
| --- | --- | --- |
| **Data root** | the data lake (Parquet files and their catalog), the archive of raw responses, the registry (data contracts, sources, designs, templates, jobs), the paper store. Large, never in git. | a folder on a disk with space, for example `~/research-lake` or `D:\research-lake` |
| **Research folder** | your projects, one folder each: studies and desks. Each is its own git repository. | for example `~/Documents/research` |

The installation asks you for both and records them in the user configuration
(`~/.config/sourcebound/config.toml`). The checkout, every project and every app then use the
same data. `sb doctor` prints what was resolved. To set them without being asked (a script, a
coding agent): `sb init --data-root PATH --projects-dir PATH`. To change them later:
`sb init --force`.

The same questions offer a desktop icon that starts the web view (`sb ui`). It is not made
unless you say yes; without asking: `sb init ... --shortcut`, or later `sb install shortcut`.

## Install the core

macOS and Linux:

```sh
git clone https://github.com/julian-hilg/sourcebound.git
cd sourcebound
make install          # uv sync, `sb` in ~/.local/bin, playbooks and subagents for Claude Code;
                      # then it asks for the data root and the research folder
sb doctor             # resolved configuration; 0 errors expected
make test             # unit tests, offline
```

Windows (PowerShell; no `make` needed):

```powershell
git clone https://github.com/julian-hilg/sourcebound.git; cd sourcebound
uv sync
uv run sb install     # `sb` in %USERPROFILE%\.local\bin, playbooks and subagents;
                      # then it asks for the data root and the research folder
sb doctor
uv run pytest -q
```

If `sb` is not found afterwards, add the folder `sb install` printed to your `PATH`.

## First steps

```sh
# shared example data: ECB reference exchange rates into the lake
cd sourcebound && uv run python pipelines/ecb_fx/pipeline.py --start 1999-01-01

# the worked example study, end to end
sb new demo --title "Fat Tails Demo"        # created in your research folder
cd ~/Documents/research/demo && sb run       # analysis, figures, bibliography, data appendix, PDF, checks

# a real study, or a desk for ongoing work
sb new my_study --title "..." --empty
sb new my_desk --title "..." --kind desk
```

Then open Claude Code in the project folder and say *use the research-study skill* (a study)
or *use the content-desk skill* (a desk).

## Add the optional parts

```sh
uv sync --extra word --extra linkedin     # formats: Word; slides, infographics and posts
sb plugin list                            # must list them
sb ui --build                             # the web view: builds once, then serves http://127.0.0.1:5210
sb install hooks                          # lets the web view show what agents are doing
```

On Windows without Node.js on the `PATH`, `sb ui --build` and the agent bridge use the Node.js
inside WSL; the checkout must then be on a drive WSL can reach. A desktop icon that runs
`sb ui`: `sb install shortcut` (or answer yes in `sb init`).

`uv sync` installs exactly the extras you name and removes the others, so name all you use
(`--extra sql` for database sources, `--extra browser` for pages that need a browser).

An organisation's own look (colours, fonts, logo, Word and slide templates) is a **pack**: a
folder the organisation keeps for itself. Install one with `sb pack install FOLDER`; see
[docs/desks-and-formats.md](docs/desks-and-formats.md).

## Install with a coding agent

Paste one of these into your coding agent. Replace nothing: the agent asks you for what it
needs.

**To install Sourcebound, step by step:**

> Please install Sourcebound on this machine, one step at a time, and stop if a step fails.
>
> 1. **Ask me three questions first, and wait for my answers:** (a) which folder should be the
>    *data root* (the data lake, the raw archive and the registry live there; it grows large and
>    is never in git), (b) which folder should be the *research folder* (my projects go
>    there, one folder each), and (c) whether I want a desktop icon that starts the web view
>    (default no). Suggest `~/research-lake` and `~/Documents/research` (on Windows
>    `D:\research-lake` and `Documents\research`) and tell me what each is for. Do not create
>    or choose them yourself.
> 2. Check the requirements: `uv --version` and `git --version`. If uv is missing, install it
>    from https://docs.astral.sh/uv/ and tell me what you did.
> 3. Clone `https://github.com/julian-hilg/sourcebound.git` into a folder for tools (not into
>    the research folder) and change into it.
> 4. Install: on macOS or Linux `make install`; on Windows `uv sync` and then
>    `uv run sb install`. Run from you, it cannot ask me anything and will say that `sb init`
>    is still to do. If `sb` is not on the PATH afterwards, tell me which folder to add.
> 5. Run `sb init --data-root <my data root> --projects-dir <my research folder>` with the two
>    folders from step 1, and `--shortcut` only if I said yes to the icon. It refuses to run
>    without the folders; never use `--defaults` unless I said so.
> 6. Run `sb doctor` and show me the lines "data root" and "registry". It must report 0
>    errors. Explain every warning in one sentence.
> 7. Run the tests (`make test`, or `uv run pytest -q` on Windows) and tell me the result.
> 8. Read `AGENTS.md` and `README.md` in the checkout. Then tell me in five lines what I can do
>    next, and ask whether I want the optional parts (Word, slides and posts, the web view)
>    before installing any of them.
>
> Do not fetch any data, do not create a project and do not change files outside the checkout
> and the two folders I named.

**To add Word, slides and the web view:**

> In the Sourcebound checkout, please add the optional parts. Run
> `uv sync --extra word --extra linkedin` and show me `sb plugin list`. For the web view, check
> that Node.js 22 or newer is installed (`node --version`); if it is, run `sb ui --build`,
> confirm that http://127.0.0.1:5210 answers and tell me the address; if it is not, tell me
> how to install it and stop. Then run `sb install hooks` only if I say yes, after explaining
> that it adds four entries to my Claude Code settings so the web view can show agent
> activity. For slides the machine needs Chrome, Edge or Chromium: tell me whether one was
> found.

**To start a study:**

> Please start a new Sourcebound study. Ask me for a short name (lowercase, underscores) and a
> title, then run `sb new <name> --title "<title>" --empty` and open the new folder. Read
> `AGENTS.md` there and use the research-study skill. Begin with the brief
> (`research/brief.md`): ask me for the question, why it matters, the deliverable and the
> constraints, write the brief, and wait for my approval (gate G1) before any research.

**To start a desk for ongoing research and content:**

> Please start a new Sourcebound desk. Ask me for a short name, a title, the topic in one
> sentence, the audience and the channels (for example LinkedIn, a newsletter, internal
> notes). Run `sb new <name> --title "<title>" --kind desk`, fill in `project.yaml` and the
> desk's `AGENTS.md` with my answers, and show me `sb template list` so I can choose the
> default format for new pieces. Then use the content-desk skill. Never approve, schedule or
> publish a piece: those are my decisions.

**To set up our organisation's design:**

> We have a Sourcebound pack with our corporate design at `<folder>`. Please run
> `sb pack install <folder>`, then show me `sb design list` and `sb template list`. If the
> pack's README lists fonts or other files to add, tell me exactly which are missing on this
> machine. Do not copy anything from the pack into the Sourcebound checkout.

## Updating

```sh
sb update                          # git pull, uv sync with the extras you have, sb install, web view, sb doctor
sb update --extra sql              # and add an extra
sb update --dry-run                # the steps, without running them
```

`sb update` keeps the extras that are installed (it names them to `uv sync` again), rebuilds
the web view only if it was built before, and refuses to pull over uncommitted changes in the
checkout. A running web view keeps the old code until it is started again. By hand, the same is
`git pull`, `uv sync --extra ...` (every extra you use), `uv run sb install`, `sb ui --build`,
`sb doctor`.

Projects and the data root are not touched by an update.

## Uninstalling

Delete the checkout, the launcher `sb` in `~/.local/bin`, the playbooks under
`~/.claude/skills/` (`research-study`, `content-desk`), the subagents
`~/.claude/agents/sb-*.md` and `~/.config/sourcebound/`. Your projects and the data root are
yours: delete them only if you no longer need the research.
