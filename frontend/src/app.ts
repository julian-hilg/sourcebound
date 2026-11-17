import { Werkbank, chatTool, crafterTool, type WorkspaceSeed } from "@werkbank/framework";
import { z } from "zod";
import { commands } from "./commands";
import { api, paths, type Detail, type QueryResult } from "./data/api";
import { appSettings, followSettings } from "./settings";
import { activityTool } from "./tools/activity";
import { assetsTool } from "./tools/assets";
import { connectionsTool } from "./tools/connections";
import { jobsTool } from "./tools/jobs";
import { lakeTool } from "./tools/lake";
import { pieceTool } from "./tools/piece";
import { piecesTool } from "./tools/pieces";
import { postPreviewTool } from "./tools/postpreview";
import { scheduleTool } from "./tools/schedule";
import { sqlTool } from "./tools/sql";
import { systemTool } from "./tools/system";
import { checkTool } from "./tools/check";
import { claimsTool } from "./tools/claims";
import { deliverableTool } from "./tools/deliverable";
import { deliverablesTool } from "./tools/deliverables";
import { documentsTool, reviewsTool } from "./tools/documents";
import { fetchLogTool } from "./tools/fetchlog";
import { hypothesesTool } from "./tools/hypotheses";
import { projectTool } from "./tools/project";
import { projectsTool } from "./tools/projects";
import { resultsTool } from "./tools/results";

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

/** Everything about one study at a glance: where it stands, what the agents do, the paper. */
const study: WorkspaceSeed = {
  name: "default",
  links,
  instances: [...linked("projects", "project", "deliverable", "hypotheses", "claims", "results", "activity", "check", "fetchlog"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 30, [tabs("left-top", 34, ["projects-1"]), tabs("left-bottom", 66, ["project-1"])]),
      tabs("centre", 42, ["deliverable-1", "hypotheses-1", "claims-1", "results-1"]),
      split("right", "vertical", 28, [tabs("right-top", 55, ["activity-1", "fetchlog-1"]), tabs("right-bottom", 45, ["check-1", "chat-1"])]),
    ]),
  },
};

/** All projects, what agents are doing and what was fetched. */
const overview: WorkspaceSeed = {
  links,
  instances: [...linked("projects", "project", "activity", "fetchlog"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 60, [tabs("left-top", 45, ["projects-1"]), tabs("left-bottom", 55, ["activity-1", "fetchlog-1"])]),
      tabs("right", 40, ["project-1", "chat-1"]),
    ]),
  },
};

/** From hypothesis to number to source: the ledger side by side. */
const evidence: WorkspaceSeed = {
  links,
  instances: linked("projects", "hypotheses", "claims", "results", "reviews", "documents", "check"),
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 34, [tabs("left-top", 22, ["projects-1"]), tabs("left-bottom", 78, ["hypotheses-1", "documents-1"])]),
      split("centre", "vertical", 38, [tabs("centre-top", 55, ["claims-1"]), tabs("centre-bottom", 45, ["results-1"])]),
      tabs("right", 28, ["reviews-1", "check-1"]),
    ]),
  },
};

/** Reading a deliverable with its numbers and reviews next to it. */
const reading: WorkspaceSeed = {
  links,
  instances: [...linked("deliverable", "results", "claims", "reviews", "deliverables", "check"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      tabs("left", 58, ["deliverable-1"]),
      split("right", "vertical", 42, [tabs("right-top", 50, ["results-1", "claims-1", "deliverables-1"]), tabs("right-bottom", 50, ["reviews-1", "check-1", "chat-1"])]),
    ]),
  },
};

/** Ongoing research: the pieces of a desk, the one being written, how it will look, when it goes out. */
const desk: WorkspaceSeed = {
  links,
  instances: [...linked("projects", "pieces", "piece", "postpreview", "schedule", "claims", "documents", "check", "activity"), { id: "chat-1", toolId: "chat" }],
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 30, [tabs("left-top", 22, ["projects-1"]), tabs("left-mid", 43, ["pieces-1"]), tabs("left-bottom", 35, ["schedule-1", "activity-1"])]),
      tabs("centre", 40, ["piece-1", "documents-1", "claims-1"]),
      split("right", "vertical", 30, [tabs("right-top", 68, ["postpreview-1"]), tabs("right-bottom", 32, ["check-1", "chat-1"])]),
    ]),
  },
};

/** The data side: what is in the lake, a console on it, where it comes from and what keeps it current. */
const data: WorkspaceSeed = {
  links,
  instances: linked("lake", "sql", "connections", "jobs", "fetchlog"),
  layout: {
    root: split("root", "horizontal", 100, [
      split("left", "vertical", 56, [tabs("left-top", 52, ["lake-1"]), tabs("left-bottom", 48, ["sql-1"])]),
      split("right", "vertical", 44, [tabs("right-top", 55, ["connections-1", "jobs-1"]), tabs("right-bottom", 45, ["fetchlog-1"])]),
    ]),
  },
};

/** The machine: what is installed, which designs, templates and formats exist, what runs. */
const system: WorkspaceSeed = {
  links,
  instances: linked("system", "assets", "activity", "jobs", "projects"),
  layout: {
    root: split("root", "horizontal", 100, [
      tabs("left", 50, ["system-1"]),
      split("right", "vertical", 50, [tabs("right-top", 52, ["assets-1", "projects-1"]), tabs("right-bottom", 48, ["jobs-1", "activity-1"])]),
    ]),
  },
};

// ---- documentation ---------------------------------------------------------------

const ABOUT = `# Sourcebound

This app shows the research on this machine: studies and desks, what they claim and on what evidence, the recorded results, reviews, deliverables and pieces, the data lake and where its data comes from, what was fetched, what is installed, and what the agents are doing right now.

**It has no data of its own.** Everything on screen is read from the project files, the data root and the registry by the local service that \`sb ui\` starts. Nothing is stored in the browser except your layout and your settings. The app writes only what the command line writes too: deliverable notes (\`sb note\`), pieces (\`sb piece\`), renders (\`sb render\`), the handover (\`sb handover\`) and the VS Code workspace (\`sb workspace\`).

## Two kinds of project

A **study** answers one question: brief, hypotheses frozen before the analysis, a paper at the end, three gates that are yours. A **desk** follows a topic for as long as it matters and produces **pieces** along the way: posts, notes, trade ideas, briefings. A desk has no hypotheses to freeze and no paper to write first; it keeps the two rules that make the work worth anything: every statement has a registered source, and every number is a recorded result or is quoted with its source.

## Panels

| Panel | Shows | Read from |
| --- | --- | --- |
| Projects | every project with kind, phase, gates and counts | \`project.yaml\` of each project |
| Project | phases and gates of a study, or topic and pieces of a desk; the log | \`project.yaml\`, \`log.md\` |
| Hypotheses, Claims, Results | the ledger and the recorded numbers | \`hypotheses.yaml\`, \`evidence/\`, \`results/results.json\` |
| Reviews, Documents | verification and referee reports; brief, landscape, notes | \`reviews/\`, \`research/\` |
| Deliverable, Deliverables | a paper rendered from the handover; what is written and wanted | \`dist/handover/\`, \`deliverables/\` |
| Pieces | the pieces of a project, and a field to start one | \`pieces/\` |
| Piece | text, card, checks, renders and decisions of one piece | \`pieces/<id>/\` |
| Post preview | a render as it would look in a feed | \`pieces/<id>/render/\` |
| Schedule | scheduled pieces day by day, what waits for a date or a review | \`pieces/*/piece.yaml\` |
| Lake | tables with contract, columns, rows and snapshots | the catalog of the data root |
| SQL console | one read-only statement against the lake or a registered database | \`sb sql\` |
| Connections | data sources and what each needs; MCP servers | the registry |
| Jobs | pipelines that run on a schedule, their runs | the registry, \`<data root>/jobs/\` |
| Fetch log | every request of the fetcher and the hosts it stopped | \`<data root>/raw/*/manifest.jsonl\` |
| System | what is installed and configured, and the command for what is missing | \`sb doctor --json\` |
| Assets | designs, templates, plugins and the formats they render | the registry, installed plugins |
| Check | what \`sb check\` and \`sb review-edits\` report | runs the command |
| Agents | what Claude Code sessions and subagents are doing | \`<data root>/activity/events.jsonl\` |

Panels in one link group follow each other: a project selected in *Projects*, a piece selected in *Pieces*, a number clicked in the *Deliverable*, a table selected in the *Lake*.

## Writing a piece

1. Type a title in *Pieces* and press *Add piece*. It becomes a folder under \`pieces/\`.
2. Write in the *Piece* panel. What you type is kept as a draft in the panel until you press *Save*; a save can be undone from the action history. Notation: \`{{result:key}}\` for a recorded number, \`[@W-0001]\` or \`[@citekey]\` for a source. A source is registered on the command line: \`sb snap URL\` archives a web page, \`sb doc FILE\` a report or any local document.
3. *Check sources and numbers* reports what does not resolve.
4. Under *Output*, choose a template and *Render*. Plain text and Markdown are built in; Word, slides and infoposts come with plugins. *Post preview* shows the render as a feed would: the first lines, "…more", the images.
5. Under *Card*: *Ready for review*, *Approve*, *Schedule*, *Mark as published*. **Nothing in this app posts anywhere.** Scheduling records when you intend to publish; you publish yourself and mark it.

## The data side

The *Lake* panel lists every table with its contract: what a row is, the key, the source, the licence. A table marked *restricted* is never part of a publication. *Rows* shows a preview; *Open in SQL console* starts a statement on it. The console runs one statement that reads; the service refuses everything else. Registering a source, a database connection or an MCP server is command-line work, because the entry records terms and licence and the provider's documentation is archived with it; *Connections* shows the commands.

*Jobs* are pipelines that run again and again, so a source without an API becomes a table that stays current. Sourcebound has no background service: the system's scheduler calls \`sb job run --due\`; the panel shows the line to install.

## The deliverable reader

The reader shows a deliverable without LaTeX, from the handover that \`sb handover\` writes. A number with a dotted line is a recorded result: hover for the script, commit and data snapshot behind it; click to select it in *Results*. A number shown as \`?key\` is used in the text but was never recorded. A section marked *edited by a person* changed since the last agent commit.

## Agents

For the *Agents* panel, run \`sb install hooks\` once. An agent connected to this app (*Assistant setup* in the rail) can read every panel and run the same commands. Reading, checking and querying run freely; notes and pieces can be changed and undone. Everything else waits for your approval: rendering, rebuilding the handover, running a job, and every decision about a piece (approve, schedule, published). The gates of a study stay where they are: approving a brief, freezing hypotheses, unblocking a host and publishing are done by you, never from here.

## Settings

*Settings* (the gear in the rail) has sections for this app: how often files are read again, which project and workspace open first, the reader, tables, the SQL console, dates and numbers, the Agents panel, the fetch log, pieces and usual posting days, the post preview, confirmations, and how much a panel hands to an agent. They belong to you and this browser; none is written to a project.

## Workspaces

*Study*: one study at a glance. *Overview*: all projects and activity. *Evidence*: hypotheses, claims and results. *Reading*: a deliverable with its numbers and reviews. *Desk*: pieces, the one being written, its preview and the schedule. *Data*: lake, console, connections, jobs, fetch log. *System*: what is installed, assets, jobs. Switch under *Workspaces* in the rail; arrange panels freely and save your own.
`;

// ---- the app ---------------------------------------------------------------------

export const werkbank = new Werkbank({
  appId: "sourcebound",
  title: "Sourcebound",
  logo: "/logo.svg",
  version: "0.1.0",
  docs: [{ id: "sourcebound", title: "Using Sourcebound", text: ABOUT }],
  tools: [
    projectsTool, projectTool, documentsTool, activityTool, checkTool,
    hypothesesTool, claimsTool, resultsTool, reviewsTool,
    deliverableTool, deliverablesTool,
    piecesTool, pieceTool, postPreviewTool, scheduleTool,
    lakeTool, sqlTool, connectionsTool, jobsTool, fetchLogTool,
    systemTool, assetsTool,
    chatTool, crafterTool,
  ],
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
      "It is the frontend of Sourcebound, a research and content workflow: it shows the projects on this machine (studies with pre-registered hypotheses and a paper; desks that follow a topic and produce pieces such as posts and notes), their claim ledgers, recorded results, reviews and deliverables, the data lake with its contracts, data connections, scheduled jobs, the fetch log, what is installed, and agent activity. All of it is read from files; the app holds no data of its own. Use it to inspect and cross-check: every number in a text must be a recorded result or carry its source, every claim must have evidence. You may read everything, query the lake read-only (sql.query), and write or change pieces and notes (piece.*, note.*: these can be undone). Do not treat anything here as approval: gates G1 to G3, freezing hypotheses, unblocking a stopped host, and approving, scheduling or publishing a piece are mine. piece.decide, piece.render, sb.handover, job.run and vscode.write need my approval. Nothing in this app posts or publishes anywhere.",
  },
  storage: localStorage,
  defaultWorkspace: study,
  presets: { Study: study, Overview: overview, Evidence: evidence, Reading: reading, Desk: desk, Data: data, System: system },
});

// Settings that code outside React needs (the data store, formatters, describe) are carried into `prefs`.
followSettings(werkbank);
