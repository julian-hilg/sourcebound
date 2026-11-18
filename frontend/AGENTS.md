# Sourcebound frontend

A local web view over Sourcebound: research projects (studies and desks), the data lake, connections,
jobs, pieces and what is installed. Built on [Werkbank](https://github.com/julian-hilg/werkbank): dockable
workspaces that people and AI agents operate together. What it is for and how to run it: `../docs/frontend.md`.

**Before changing anything, read `node_modules/@werkbank/framework/GUIDE.md`.** It is the framework's guide for
coding agents and matches the installed version: how to add panels, commands, settings, forms, charts,
workspaces and documentation, and the rules that keep an app updatable.

## Commands

- `npm run dev`: the app at http://localhost:5200, the agent bridge on port 8787 and the data service (`sb ui`) on port 5210
- `npm run typecheck`, `npm run build`
- `npm run werkbank:update`: move to the newest framework release (`-- <version>` for a specific one)
- `sb ui` (in the checkout): serves the built app at http://127.0.0.1:5210; `sb ui --build` builds it first

A change is done when `npm run typecheck` and `npm run build` pass, the Python tests pass (`make test` in the
checkout), and you opened the app and used the feature in every theme and in a narrow panel.

## Where things are

- `src/app.ts`: the app's identity, tools, topics, documentation page, the workspaces, what custom elements may call
- `src/commands.ts`: every action; each does what an `sb` command does
- `src/settings.ts`: every setting, and `followSettings`, which carries those that code outside React needs into `src/prefs.ts`
- `src/data/api.ts`: the one data store (answers of the service, reloaded on a timer) and the types of what it returns
- `src/tools/`: one file per panel type. `lib.tsx` (which project, dates, exports), `pieces.lib.ts` (shared by the four
  piece panels). `deliverable.view.tsx` is loaded on demand (Markdown and mathematics renderers)
- `src/kit/`: display elements that do not know this app; candidates for Werkbank. Read `src/kit/README.md` first
- `src/reader/markup.ts`: turns handover Markdown into numbered blocks and links; no React
- `src/app.css`: the app's styles, prefix `sb-`; `src/kit/kit.css`: the kit's, prefix `kit-`
- `../src/sourcebound/ui.py`: the data service

## Panels: tools and hubs

The Tools list holds nine tools. Six are **hubs** (`src/tools/hubs.ts`): one panel with related views as tabs,
built by `defineHub` in `src/tools/hub.tsx` from ordinary tool definitions.

| Tool | Tabs (key: file) |
| --- | --- |
| Projects | – (`projects.tsx`) |
| Project | overview: `project.tsx`, documents: `documents.tsx`, check: `check.tsx`, agents: `activity.tsx` |
| Evidence | hypotheses, claims, results, reviews (`documents.tsx`) |
| Deliverable | read: `deliverable.tsx`, all: `deliverables.tsx` |
| Pieces | list beside the tabs: `pieces.tsx`; edit: `piece.tsx`, preview: `postpreview.tsx`, schedule: `schedule.tsx` |
| Lake, SQL console | – (`lake.tsx`, `sql.tsx`) |
| Sources | connections, jobs, fetchlog |
| System | overview: `system.tsx`, assets: `assets.tsx` |

A part reads and writes its state with `usePanelState` from `tools/lib.tsx`, never `useToolState`: inside a hub
its state lives under its key in the hub's state. A new view that belongs with an existing hub becomes a tab
there, not a new tool. The Crafter is not part of this app (the owner's decision, 2026-11-17).

Link topics: `project`, `hypothesis`, `claim`, `result`, `piece`, `table`. The preset workspaces put every panel
into link group 1; open a panel that should follow the selection with `openLinked` from `tools/lib.tsx`.
Every button or menu entry that brings up another panel uses `show` (or `openLinked`) from `tools/lib.tsx`, never
`panel.open` directly: it goes to the tool's open panel and opens a new one only when none is open. A second panel
of a tool comes only from dragging the tool into the layout (the owner's rule, 2026-11-17). Hand-offs pass
`patch`, which is merged over the panel's state (the SQL console keeps its history); for a hub it names the tab:
`show(wb, "sources", { patch: { tab: "fetchlog", fetchlog: { … } } })`.

## Rules of this app

- **Werkbank first.** Before writing a component, look for it in the framework (`Select`, `MultiSelect`,
  `SearchBox`, `Markdown`, `openContextMenu`, the `wb-*` classes) and for the pattern in its starter (the SQL
  console and the Connections panel here are the starter's, pointed at real data). Only then build something.
- **Bespoke display elements go into `src/kit/`,** not into a panel: props only, tokens only, no import from
  `../data` or `../tools`, a doc comment that says what it is and when to use it, a line in `kit/README.md`.
  A panel composes kit components and framework controls; it holds no reusable widget of its own.
- **No second source of truth.** A panel shows what the service read from the files. Do not keep project data
  in panel state, in `localStorage` or in a store of its own; panel state is for filters, selections and drafts.
  A draft (a half-written note or piece text) lives in `useToolState` and reaches a file only through a command.
- **Write nothing the command line could not.** A new action that changes a file needs an `sb` command first
  (`../src/sourcebound/cli.py`, `cli_more.py`), then an endpoint in `ui.py` that calls the same function, then a
  command here.
- **Risk classes, honestly.** `read`: changes nothing (checks, queries). `local`: only with an `undo` that puts
  the files back (notes, pieces). `external`: everything else that writes or fetches (handover, render, job run,
  workspace file) and every decision that is the person's (`piece.decide`). An agent's `external` request waits
  for approval; a person's click runs, behind a "Really?" if the Confirmations settings ask for one.
- **The person's decisions are not in the app's hands.** No command approves a brief, freezes hypotheses,
  unblocks a host or publishes; `piece.decide` records a decision, it does not post. Nothing here posts anywhere:
  keep saying so on screen where publishing is mentioned.
- **Registering is command-line work, except database connections.** Sources, MCP servers, designs, templates,
  packs and jobs are files with terms and documentation; the app shows them and the command to add one
  (`CommandLine` from the kit). Do not build forms for them. Database connections are the exception (the
  owner's decision, 2026-11-17): the Connections panel creates, changes, tests and removes them as the
  Werkbank starter does, through `connection.save|remove|test|forget`, which write the same register entry as
  `sb datasource add|set|rm`. A password is typed by the person, goes to the service directly (never through a
  command, whose input the history records) and lives only in the memory of `sb ui`.
- **Every setting does something.** A new `SettingSpec` in `settings.ts` is read by a panel (`useSetting`), a
  command, or through `prefs`. No dead switches. Settings belong to the person and the browser, never to a project.
- **Every panel returns the data behind its view from `describe`,** bounded by the person's caps
  (`prefs.rowCap`, `prefs.textCap`), with a note when it was cut. Environment variables by name and
  whether they are set; never a value.
- **The service stays local and narrow.** It answers this machine only, serves files from a short list of
  folders, runs three `sb` commands and one reading SQL statement at a time. Widen any of these only with a
  reason, and add a test in `../tests/test_core.py`.

## Rules from the framework

- This app owns `src/`. The framework lives in `node_modules/@werkbank` and is never edited here: a framework
  update must be able to replace it. If the framework lacks something, build it in the kit or propose it upstream.
- Import only from `@werkbank/framework`, `@werkbank/framework/styles.css` and `@werkbank/bridge`,
  never from a path inside those packages.
- Colours come from the `--wb-*` theme tokens; no literal colours in components, `app.css` or `kit.css`.
  A colour that is data (a design's palette in the Assets panel) is passed as a value.
- Dropdowns and search fields are the framework's `Select`, `MultiSelect` and `SearchBox`, never native ones;
  no native date pickers either.
- Do not commit unless asked.
