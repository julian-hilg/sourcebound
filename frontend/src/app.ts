import { Werkbank, chatTool, type WorkspaceSeed } from "@werkbank/framework";
import { z } from "zod";
import { commands } from "./commands";
import { api, paths, type Detail, type QueryResult } from "./data/api";
import { appSettings, followSettings } from "./settings";
import { deliverableHub, evidenceHub, piecesHub, projectHub, sourcesHub, systemHub } from "./tools/hubs";
import { lakeTool } from "./tools/lake";
import { projectsTool } from "./tools/projects";
import { sqlTool } from "./tools/sql";
import { documentationTool } from "./tools/documentation";

/**
 * The Sourcebound frontend: a view over the files of research projects. It has no data of its
 * own. Every panel reads what the local service (`sb ui`) reads from the project folders, and
 * every action is a command that does what the `sb` command line does.
 */

// ---- workspaces -----------------------------------------------------------------

const split = (id: string, orientation: "horizontal" | "vertical", size: number, children: WorkspaceSeed["layout"]["root"][]) =>
  ({ type: "split" as const, id, orientation, size, children });
const tabs = (id: string, size: number, panels: string[], selectedId = panels[0]) =>
  ({ type: "tabset" as const, id, size, selectedId, tabs: panels.map((p) => ({ id: p })) });
/** Panels of one workspace share the selected project, hypothesis, claim, result, piece and lake table. */
const links = { "1": { project: null, hypothesis: null, claim: null, result: null, piece: null, table: null } };
const linked = (...toolIds: string[]) => toolIds.map((toolId) => ({ id: `${toolId}-1`, toolId, link: "1" }));
/** Every preset starts with the roomier rows; the person can switch to compact (Settings, Appearance). */
const shell = { density: "comfortable" as const };

/** One study: the list of projects, where the chosen one stands, its evidence and its paper. */
const study: WorkspaceSeed = {
  name: "default",
  links,
  shell,
  instances: [...linked("projects", "project", "deliverable", "evidence"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 27, [tabs("left-top", 30, ["projects-1"]), tabs("left-bottom", 70, ["project-1"])]),
      tabs("centre", 50, ["deliverable-1"]),
      tabs("right", 23, ["evidence-1", "chat-1"]),
    ]),
  },
};

/** All projects, and what the agents are doing. */
const overview: WorkspaceSeed = {
  name: "Overview",
  links,
  shell,
  instances: [...linked("projects", "project"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [tabs("left", 55, ["projects-1"]), tabs("right", 45, ["project-1", "chat-1"])]),
  },
};

/** The ledger: hypotheses, claims, results and reviews beside the project's documents. */
const evidence: WorkspaceSeed = {
  name: "Evidence",
  links,
  shell,
  instances: linked("projects", "evidence", "project"),
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 30, [tabs("left-top", 30, ["projects-1"]), tabs("left-bottom", 70, ["project-1"])]),
      tabs("right", 70, ["evidence-1"]),
    ]),
  },
};

/** A deliverable to read, with the numbers and reviews behind it. */
const reading: WorkspaceSeed = {
  name: "Reading",
  links,
  shell,
  instances: [...linked("deliverable", "evidence"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [tabs("left", 60, ["deliverable-1"]), tabs("right", 40, ["evidence-1", "chat-1"])]),
  },
};

/** A desk: its pieces with the one being written, its preview and the schedule. */
const desk: WorkspaceSeed = {
  name: "Desk",
  links,
  shell,
  instances: [...linked("projects", "pieces", "project"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 22, [tabs("left-top", 35, ["projects-1"]), tabs("left-bottom", 65, ["project-1"])]),
      tabs("right", 78, ["pieces-1", "chat-1"]),
    ]),
  },
};

/** Posts with the assistant beside them: the slides large, the text and preview as tabs, the assistant to change them. */
const studio: WorkspaceSeed = {
  name: "Post studio",
  links,
  shell,
  instances: [{ id: "pieces-1", toolId: "pieces", link: "1", state: { tab: "slides" } }, ...linked("projects"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [tabs("left", 66, ["pieces-1"]), tabs("right", 34, ["chat-1", "projects-1"])]),
  },
};

/** The data side: what is in the lake, a console on it, where it comes from. */
const data: WorkspaceSeed = {
  name: "Data",
  links,
  shell,
  instances: linked("lake", "sql", "sources"),
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 56, [tabs("left-top", 52, ["lake-1"]), tabs("left-bottom", 48, ["sql-1"])]),
      tabs("right", 44, ["sources-1"]),
    ]),
  },
};

/** What is installed, and what runs. */
const system: WorkspaceSeed = {
  name: "System",
  links,
  shell,
  instances: linked("system", "sources"),
  layout: {
    root: split("root", "horizontal", 100, [tabs("left", 55, ["system-1"]), tabs("right", 45, ["sources-1"])]),
  },
};

// ---- documentation ---------------------------------------------------------------

const ABOUT = `# Sourcebound

This app shows the research on this machine: studies and desks, what they claim and on what evidence, the recorded results, reviews, deliverables and pieces, the data lake and where its data comes from, what was fetched, what is installed, and what the agents are doing right now.

**It has no data of its own.** Everything on screen is read from the project files, the data root and the registry by the local service that \`sb ui\` starts. The app itself keeps only your layout, your settings and the assistant's conversations: in this browser, and with the agent bridge running also on disk in \`frontend/.werkbank/\` of the checkout (private to you, never committed), so they survive clearing the browser and another browser. The app writes only what the command line writes too: deliverable notes (\`sb note\`), pieces (\`sb piece\`), renders (\`sb render\`), the handover (\`sb handover\`) and the VS Code workspace (\`sb workspace\`).

## Two kinds of project

A **study** answers one question: brief, hypotheses frozen before the analysis, a paper at the end, three gates that are yours. A **desk** follows a topic for as long as it matters and produces **pieces** along the way: posts, notes, trade ideas, briefings. A desk has no hypotheses to freeze and no paper to write first; it keeps the two rules that make the work worth anything: every statement has a registered source, and every number is a recorded result or is quoted with its source.

## Panels

Related views are tabs of one panel, so a workspace needs few panels.

| Panel | Tabs | Read from |
| --- | --- | --- |
| Projects | every project with kind, phase, gates and counts | \`project.yaml\` of each project |
| Project | *Overview*: phases and gates of a study, or topic and pieces of a desk, and the log. *Documents*: brief, landscape, notes. *Check*: what \`sb check\` and \`sb review-edits\` report. *Agents*: what Claude Code sessions and subagents are doing | \`project.yaml\`, \`log.md\`, \`research/\`, \`<data root>/activity/events.jsonl\` |
| Evidence | *Hypotheses*, *Claims*, *Results*: the ledger and the recorded numbers. *Reviews*: verification and referee reports | \`hypotheses.yaml\`, \`evidence/\`, \`results/results.json\`, \`reviews/\` |
| Deliverable | *Read*: a deliverable as *Text* (rendered from the handover), as *PDF* (the LaTeX build) or as each render, such as *Word · template* (shown as it prints; the file is one click away). *All and planned*: what is written and what is wanted | \`dist/handover/\`, \`deliverables/\`, \`dist/render/\` |
| Pieces | the list of pieces beside *Text* (text, card, checks, renders, decisions), *Post preview* (a render as a feed shows it) and *Schedule* | \`pieces/\` |
| Lake | tables with contract, columns, rows and snapshots | the catalog of the data root |
| SQL console | one read-only statement against the lake or a registered database | \`sb sql\` |
| Sources | *Connections*: data sources and what each needs, MCP servers. *Jobs*: pipelines on a schedule and their runs. *Fetch log*: every request of the fetcher and the hosts it stopped | the registry, \`<data root>/jobs/\`, \`<data root>/raw/*/manifest.jsonl\` |
| System | *Overview*: what is installed and configured, and the command for what is missing. *Assets*: designs, templates, plugins and their formats | \`sb doctor --json\`, the registry |
| Documentation | example prompts for an agent (start a study or a desk, make a post from a file, change a slide), the commands, and pages an installed pack adds | Sourcebound, the registry's \`docs/\` |

Panels in one link group follow each other: a project selected in *Projects*, a piece selected in *Pieces*, a number clicked in the *Deliverable*, a table selected in the *Lake*. A tab follows the selection like a panel does.

A click on a tool in the side bar, or a button such as *Open in SQL console*, goes to that tool's panel when one is open; a dot in the Tools list marks such tools. To have a second panel of the same tool, drag the tool from the Tools list into the layout.

## Writing a piece

1. Type a title in *Pieces* and press *Add piece*. It becomes a folder under \`pieces/\`.
2. Write under *Text*. What you type is kept as a draft in the panel until you press *Save*; a save can be undone from the action history. Notation: \`{{result:key}}\` for a recorded number, \`[@W-0001]\` or \`[@citekey]\` for a source. A source is registered on the command line: \`sb snap URL\` archives a web page, \`sb doc FILE\` a report or any local document.
3. *Check sources and numbers* reports what does not resolve.
4. Under *Output*, choose a template and *Render*. Plain text and Markdown are built in; Word, slides and infoposts come with plugins. The *Post preview* tab shows the render as a feed would: the first lines, "…more", the images.
5. Under *Card*: *Ready for review*, *Approve*, *Schedule*, *Mark as published*. **Nothing in this app posts anywhere.** Scheduling records when you intend to publish; you publish yourself and mark it.

## The data side

The *Lake* panel lists every table with its contract: what a row is, the key, the source, the licence. A table marked *restricted* is never part of a publication. *Rows* shows a preview; *Open in SQL console* starts a statement on it. The console runs one statement that reads; the service refuses everything else. Registering a source, a database connection or an MCP server is command-line work, because the entry records terms and licence and the provider's documentation is archived with it; *Sources*, *Connections* shows the commands.

*Jobs* are pipelines that run again and again, so a source without an API becomes a table that stays current. Sourcebound has no background service: the system's scheduler calls \`sb job run --due\`; the panel shows the line to install.

## The deliverable reader

The reader shows a deliverable without LaTeX, from the handover that \`sb handover\` writes. Citations are numbered, as in the Word renders (Settings, Reader: author and year as in the PDF). A number with a dotted line is a recorded result: hover for the script, commit and data snapshot behind it; click to select it under *Evidence*, *Results*. A number shown as \`?key\` is used in the text but was never recorded. A section marked *edited by a person* changed since the last agent commit.

## Agents

For the *Agents* tab of *Project*, run \`sb install hooks\` once. An agent connected to this app (*Assistant setup* in the rail) can read every panel and run the same commands. Reading, checking and querying run freely; notes and pieces can be changed and undone. Everything else waits for your approval: rendering, rebuilding the handover, running a job, and every decision about a piece (approve, schedule, published). The gates of a study stay where they are: approving a brief, freezing hypotheses, unblocking a host and publishing are done by you, never from here.

## Settings

*Settings* (the gear in the rail) has sections for this app: how often files are read again, which project and workspace open first, the reader, tables, the SQL console, dates and numbers, the Agents panel, the fetch log, pieces and usual posting days, the post preview, confirmations, and how much a panel hands to an agent. They belong to you and this browser; none is written to a project.

## Workspaces

*Study*: one study at a glance. *Overview*: all projects and activity. *Evidence*: the ledger beside the project. *Reading*: a deliverable with its numbers and reviews. *Desk*: the pieces of a desk, written, previewed and scheduled. *Post studio*: a post's slides large, with the assistant beside them: select a slide and say what to change. *Data*: lake, console and sources. *System*: what is installed and what runs. Switch under *Workspaces* in the rail; arrange panels freely and save your own. Saved workspaces from before the tabs lose the panels that became tabs: open *Workspaces* and pick a preset again.
`;

// ---- the app ---------------------------------------------------------------------

export const werkbank = new Werkbank({
  appId: "sourcebound",
  title: "Sourcebound",
  logo: "/logo.svg",
  // The first is the default: the app's own reading themes (theme.css), then the framework's.
  themes: ["sourcebound", "sourcebound-dark", "light", "dark", "xp"],
  version: "0.1.0",
  docs: [{ id: "sourcebound", title: "Using Sourcebound", text: ABOUT }],
  tools: [projectsTool, projectHub, evidenceHub, deliverableHub, piecesHub, lakeTool, sqlTool, sourcesHub, systemHub, chatTool, documentationTool],
  // What linked panels share. Each is an id from the project files; null means "none chosen".
  topics: {
    project: z.string().nullable(),
    hypothesis: z.string().nullable(),
    claim: z.string().nullable(),
    result: z.string().nullable(),
    piece: z.string().nullable(),
    table: z.string().nullable(),
  },
  commands,
  settings: appSettings,
  custom: {
    // What panels people build for themselves may read. Read-only by design.
    hostFunctions: {
      project: {
        description: "project({ id }) returns one project's data: phase, gates, hypothesis_list, claim_list, result_list (key, display, value, unit, hypothesis, script, git, data, at), log, notes. Ids are listed by the Projects panel.",
        run: (args) => api.fetch<Detail>(paths.project(String((args as { id?: string } | null)?.id ?? ""))),
      },
      query: {
        description: "query({ sql, target }) runs ONE read-only statement (SELECT, WITH, SHOW, DESCRIBE) against the data lake (target 'lake', the default; tables are <schema>.<table>) or a registered database source, and returns { columns, types, rows (arrays in column order), row_count, truncated }. At most 1000 rows; aggregate in SQL. Tables and columns are listed by the Lake panel.",
        run: async (args) => {
          const { sql, target } = (args ?? {}) as { sql?: string; target?: string };
          const result = await api.post<QueryResult>(paths.sql, { target: target ?? "lake", query: String(sql ?? ""), limit: 1000 });
          return { columns: result.columns, types: result.types, rows: result.rows, row_count: result.row_count, truncated: result.truncated };
        },
      },
    },
  },
  assistant: {
    serverName: "sourcebound",
    brief:
      "It is the frontend of Sourcebound, a research and content workflow: it shows the projects on this machine (studies with pre-registered hypotheses and a paper; desks that follow a topic and produce pieces such as posts and notes), their claim ledgers, recorded results, reviews and deliverables, the data lake with its contracts, data connections, scheduled jobs, the fetch log, what is installed, and agent activity. All of it is read from files; the app holds no data of its own. Use it to inspect and cross-check: every number in a text must be a recorded result or carry its source, every claim must have evidence. You may read everything, query the lake read-only (sql.query), and write or change pieces and notes (piece.*, note.*: these can be undone). Writing a post: create it in a desk (a project of kind desk; for LinkedIn the desk whose channels name linkedin), not in a study, unless I name the project; the desk's piece_defaults give template and design. Before writing content a template needs (slides.yaml for slides and PowerPoint templates), run piece.format and follow its guide exactly, never guess field names; write the file with piece.data, then piece.check, then piece.render. A desk with own.publishers and self_citation false must not cite its own studies or reports: cite the original sources they rest on, unless I ask otherwise. Do not treat anything here as approval: gates G1 to G3, freezing hypotheses, unblocking a stopped host, and approving, scheduling or publishing a piece are mine. piece.decide, piece.render, sb.handover, job.run and vscode.write need my approval. Nothing in this app posts or publishes anywhere.",
  },
  storage: localStorage,
  defaultWorkspace: study,
  presets: { Study: study, Overview: overview, Evidence: evidence, Reading: reading, Desk: desk, "Post studio": studio, Data: data, System: system },
});

// Settings that code outside React needs (the data store, formatters, describe) are carried into `prefs`.
followSettings(werkbank);
