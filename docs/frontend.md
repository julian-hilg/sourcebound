# The frontend

A local web view over the files of all projects: where each study stands, its hypotheses,
claims, results and reviews, its deliverables, the fetch log and what the agents are doing.
It is optional. Nothing in Sourcebound depends on it.

```sh
sb ui --build        # once, and after an update of the checkout: installs and builds the frontend
sb ui                # http://127.0.0.1:5210
```

`--build` needs Node.js 22 or newer. Without a build, `sb ui` still serves the data and says
how to build the page. On Windows without Node.js on the `PATH`, `sb ui` uses the Node.js
inside WSL for the build and the agent bridge (the checkout must be on a drive WSL can reach).

## No second source of truth

The frontend has no data of its own. `sb ui` starts a small service on this machine that
reads the project files at every request and answers in JSON; the page shows the answers
and reloads them every few seconds. The browser stores the layout of the panels, nothing
else. The service writes three things, each the same way the command line does:

| In the frontend | Command line | File |
| --- | --- | --- |
| Deliverable notes | `sb note add \| set \| rm \| list` | `deliverables/notes.yaml` |
| Rebuild the handover | `sb handover` | `dist/handover/` |
| Write the VS Code workspace | `sb workspace [PATH]` | `research.code-workspace` |

It also runs `sb check` and `sb review-edits` and shows what they print. It cannot freeze
hypotheses, unblock a host or publish: the gates stay in the conversation and the terminal.

## What it shows

Related views are tabs of one panel: *Project*, *Evidence*, *Deliverable*, *Pieces*, *Sources* and *System*
are such hubs. A link or a button that leads to a view opens its tab; a click in the Tools list goes to a
panel that is already open, and dragging a tool into the layout opens a second one.

| View (hub, tab) | Content | Read from |
| --- | --- | --- |
| Projects | every project: phase, gates G1 to G3, counts, last change | `project.yaml`, ledger files |
| Project, Overview | phases and gates, pre-registration, research log | `project.yaml`, `hypotheses.yaml`, `log.md` |
| Evidence, Hypotheses | registered fields, results, and whether a hypothesis changed after the freeze | `hypotheses.yaml` |
| Evidence, Claims | the claim ledger with evidence, stance, locator and quote | `evidence/claims.yaml`, `evidence/sources.yaml` |
| Evidence, Results | every recorded number with script, commit and data snapshot | `results/results.json` |
| Evidence, Reviews; Project, Documents | verification and referee reports; brief, landscape, notes, log | `reviews/`, `research/`, `log.md` |
| Deliverable, Read | a deliverable rendered from the handover (see below) | `dist/handover/` |
| Deliverable, All and planned | deliverable folders, and the notes: what is wanted, status, stored prompt | `deliverables/` |
| Project, Check | output of `sb check` and `sb review-edits` | runs the command |
| Sources, Fetch log | the fetcher's requests and the hosts it stopped | `<data root>/raw/<source>/manifest.jsonl` |
| Project, Agents | what Claude Code sessions and subagents are doing | `<data root>/activity/events.jsonl` |

Projects are found in the hub folder, in `[projects] dir` of the configuration, in each folder
listed under `[projects] also` (a folder of projects, or one project), and around the folder
`sb ui` was started in:

```toml
[projects]
dir  = "~/research"
also = ["~/work/desks", "~/work/one-project"]
```

 The gates are read from the files, not stored: G1 from the
phase and the log line that names it, G2 from the freeze record, G3 from the phase.

Panels of one link group share the selected project, hypothesis, claim and result. A number
clicked in the deliverable is selected in the Results panel; so is a result named by a
hypothesis or a claim.

## Reading a deliverable without LaTeX

The Deliverable panel renders the format-neutral handover (`sb handover`) in a layout close
to the LaTeX house style: numbered sections, figures and tables with captions, booktabs
rules, mathematics, author-year citations in blue, a reference list.

- A recorded number is marked. Hovering shows its key, the script and commit that recorded
  it, the data snapshot and the hypothesis. A key used in the text but never recorded is
  shown as `?key`.
- The panel says when the handover is older than the sections or the results, and rebuilds
  it on request.
- A section a person changed since the last agent commit is marked (what `sb review-edits`
  reports).
- LaTeX commands the converter does not know stay as written and are listed above the page.
  The converter expands the simple macros a deliverable defines in its preamble
  (`\newcommand\name[n]{...}`) and converts `description` lists, `tabular` bodies and
  listings.
- PDF figures are shown as PNG, converted by `pdftoppm` (poppler) or, on macOS, `sips`.
  Without either, the figure is offered as a file.

## Agent activity

```sh
sb install hooks     # once per machine; adds four hooks to ~/.claude/settings.json
```

Claude Code then calls `sb hook` at the start of a session, before each tool call, when a
subagent finishes and when a turn ends. Each event becomes one line: time, project, session,
subagent, tool and one short summary (a task description, a command, a path). Prompts and
file contents are never written. The hook cannot fail or delay a tool call. The log moves to
`events.1.jsonl` at 5 MB.

## Agents can use it too

The frontend is built on [Werkbank](https://github.com/julian-hilg/werkbank): every panel can
return the data behind its view, and every action is a typed command. `sb ui` also starts
Werkbank's bridge on `127.0.0.1:8787`, which serves MCP. The *Assistant setup* window in the
app gives the command that registers it with Claude Code or another agent; the Assistant
panel talks to a coding agent from inside the app.

| Command | Does | Risk class |
| --- | --- | --- |
| `sb.check`, `sb.reviewEdits`, `data.refresh`, `vscode.workspace` | read and report | read: an agent runs it freely |
| `note.create`, `note.update`, `note.delete` | change `deliverables/notes.yaml` | local: can be undone from the action history |
| `sb.handover`, `vscode.write` | write files in a project or the projects folder | external: an agent's request waits for approval |

## Safety

- The service and the bridge listen on `127.0.0.1` only.
- The service refuses a request whose `Host` is not this machine or whose `Origin` is another
  site, and accepts changes only as JSON, so a web page open in the same browser cannot
  call it.
- It serves text files from `research/`, `reviews/`, `evidence/`, `analysis/` and
  `dist/handover/` and images or PDFs from `figures/`, `deliverables/` and `dist/handover/`.
  LaTeX sources, raw data and files outside a project are not served.
- It runs exactly three commands: `sb check`, `sb review-edits`, `sb handover`.

It is meant for one person on one machine. Do not expose the ports.

## Working on the frontend

The app is in `frontend/`; `frontend/AGENTS.md` has the rules.

```sh
cd frontend
npm install
npm run dev          # http://localhost:5200 with live reload; starts the service and the bridge
npm run typecheck && npm run build
```

Werkbank is a dependency (`@werkbank/framework`, `@werkbank/bridge`), never edited here.
The two packages come from Werkbank's GitHub releases; `npm run werkbank:update` moves the
app to the newest one.

## Limits

- Tried in Chromium only.
- No static export yet: reading a deliverable needs `sb ui` on the machine that holds the
  project.
- The reference list is formatted by the frontend (author-year) and can differ in detail from
  the BibLaTeX style of the PDF.
- Agent activity shows tool calls, not reasoning, and only for sessions started after
  `sb install hooks`.
