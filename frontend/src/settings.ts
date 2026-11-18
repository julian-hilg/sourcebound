import type { SettingSpec, Werkbank } from "@werkbank/framework";
import { z } from "zod";
import { setPrefs } from "./prefs";

/**
 * Settings this app adds to the framework's own. Each one is read somewhere: by a panel
 * (`useSetting`), by the data store and the formatters (through `prefs`, see `apply` below), or
 * by a command. They belong to the person and this browser; nothing here is written to a project.
 */

const seconds = (min: number, max: number) => z.number().int().min(min).max(max);
const choice = <T extends string>(values: readonly [T, ...T[]], labels: Record<T, string>) => ({
  schema: z.enum(values as readonly [string, ...string[]]),
  options: values.map((value) => ({ value: value as string, label: labels[value] as string })),
});
export const WORKSPACES = ["Study", "Overview", "Evidence", "Reading", "Desk", "Post studio", "Data", "System"] as const;
const workspaceLabels = Object.fromEntries(WORKSPACES.map((w) => [w, w])) as Record<(typeof WORKSPACES)[number], string>;

export const appSettings: SettingSpec<any>[] = [
  // ---- how often the files are read again
  { key: "data.refreshSeconds", title: "Reload project files every", section: "Reloading", description: "Seconds between reloads of what the visible panels show from the project folders (ledger, results, pieces).", schema: seconds(2, 120), default: 6 },
  { key: "data.activitySeconds", title: "Reload agent activity every", section: "Reloading", description: "Seconds between reloads of the Agents panel.", schema: seconds(1, 60), default: 2 },
  { key: "data.jobsSeconds", title: "Reload jobs and the fetch log every", section: "Reloading", description: "Seconds between reloads of the Jobs and Fetch log panels.", schema: seconds(3, 300), default: 15 },
  { key: "data.systemSeconds", title: "Reload system, lake and connections every", section: "Reloading", description: "Seconds between reloads of the System, Lake, Connections and Assets panels. These change rarely; the System report also measures folder sizes.", schema: seconds(10, 900), default: 60 },

  // ---- projects
  { key: "projects.first", title: "Project shown first", section: "Projects", description: "The id (slug) of the project panels show until you select another. Empty: the first one found.", schema: z.string().max(80), default: "", control: "text" },
  { key: "projects.switchWorkspace", title: "Switch workspace when opening a project", section: "Projects", description: "Double-clicking a project in the Projects panel also switches to the workspace chosen below for its kind.", schema: z.boolean(), default: false },
  { key: "projects.studyWorkspace", title: "Workspace for a study", section: "Projects", description: "Used by “Open in its workspace” for projects with hypotheses and a paper.", default: "Study", ...choice(WORKSPACES, workspaceLabels) },
  { key: "projects.deskWorkspace", title: "Workspace for a desk", section: "Projects", description: "Used by “Open in its workspace” for ongoing research that produces pieces.", default: "Desk", ...choice(WORKSPACES, workspaceLabels) },

  // ---- the deliverable reader
  { key: "reader.font", title: "Typeface", section: "Reader", description: "The deliverable reader's text.", default: "sans", ...choice(["serif", "sans"], { serif: "Serif, as in the PDF", sans: "Sans-serif, as the rest of the app" }) },
  { key: "reader.width", title: "Text width", section: "Reader", description: "How wide the page is before it stops growing with the panel.", default: "normal", ...choice(["narrow", "normal", "wide"], { narrow: "Narrow (about 60 characters)", normal: "Normal (about 75 characters)", wide: "Wide (about 95 characters)" }) },
  { key: "reader.fontSize", title: "Text size", section: "Reader", description: "In pixels.", schema: z.number().int().min(12).max(24), default: 16 },
  { key: "reader.markNumbers", title: "Mark recorded numbers", section: "Reader", description: "A dotted line under every number that comes from a recorded result.", schema: z.boolean(), default: true },
  { key: "reader.showEdited", title: "Mark sections edited by a person", section: "Reader", description: "Show which sections changed since the last agent commit.", schema: z.boolean(), default: true },
  { key: "reader.citations", title: "Citations", section: "Reader", description: "How the reader shows a citation in the text.", default: "numbered", ...choice(["numbered", "author-year"], { numbered: "Numbered, [1] (as in the Word renders)", "author-year": "Author and year (as in the LaTeX PDF)" }) },
  { key: "reader.showReferences", title: "Show the reference list", section: "Reader", description: "The list of cited sources at the end of the text.", schema: z.boolean(), default: true },

  // ---- tables and grids
  { key: "tables.density", title: "Row height in tables", section: "Tables", description: "Applies to the lists and grids of this app's panels.", default: "comfortable", ...choice(["compact", "comfortable"], { compact: "Compact", comfortable: "Comfortable" }) },
  { key: "tables.previewRows", title: "Rows in a table preview", section: "Tables", description: "How many rows the Lake panel loads when a table is selected.", default: "200", ...choice(["50", "200", "1000", "5000"], { "50": "50 rows", "200": "200 rows", "1000": "1,000 rows", "5000": "5,000 rows (the most the service returns)" }) },
  { key: "tables.nullText", title: "Text for an empty value", section: "Tables", description: "What grids show where the data has no value.", schema: z.string().max(12), default: "NULL", control: "text", suggestions: ["NULL", "–", "n/a"] },

  // ---- SQL console
  { key: "sql.rowLimit", title: "Row limit for queries", section: "SQL console", description: "The most rows a statement returns to the console.", default: "500", ...choice(["100", "500", "2000", "5000"], { "100": "100 rows", "500": "500 rows", "2000": "2,000 rows", "5000": "5,000 rows" }) },
  { key: "sql.historyLength", title: "Statements kept in the history", section: "SQL console", description: "Per console panel; the oldest are dropped.", schema: z.number().int().min(0).max(40), default: 12 },
  { key: "sql.wrapEditor", title: "Wrap long lines in the editor", section: "SQL console", schema: z.boolean(), default: true },

  // ---- dates and numbers
  { key: "format.dates", title: "Dates and times", section: "Dates and numbers", description: "ISO is unambiguous and sorts; the local form follows the number format below.", default: "iso", ...choice(["iso", "local"], { iso: "ISO: 2026-11-16 17:02", local: "Local form" }) },
  { key: "format.relative", title: "Recent times as “3 min ago”", section: "Dates and numbers", description: "Off: every time is shown as a date and time.", schema: z.boolean(), default: true },
  { key: "format.locale", title: "Number format", section: "Dates and numbers", description: "Grouping and decimal marks in grids and tiles. Numbers in a deliverable are never reformatted: they are shown as recorded.", default: "en-GB", ...choice(["en-GB", "en-US", "de-DE", "de-CH", "fr-FR"], { "en-GB": "1,234.5 (English, UK)", "en-US": "1,234.5 (English, US)", "de-DE": "1.234,5 (German)", "de-CH": "1’234.5 (Swiss)", "fr-FR": "1 234,5 (French)" }) },

  // ---- agents panel
  { key: "activity.hideTools", title: "Hide events of these tools", section: "Agents panel", description: "Tool names separated by commas. Reading and searching make most of the noise.", schema: z.string().max(200), default: "Read, Grep, Glob", control: "text" },
  { key: "activity.subagentsOnly", title: "Show subagents only", section: "Agents panel", description: "Hide what the lead session does itself.", schema: z.boolean(), default: false },
  { key: "activity.maxRows", title: "Events shown", section: "Agents panel", schema: z.number().int().min(20).max(300), default: 150 },

  // ---- fetch log
  { key: "fetchlog.defaultOutcome", title: "A new Fetch log panel shows", section: "Fetch log", default: "all", ...choice(["all", "refused"], { all: "All requests", refused: "Refused or failed requests only" }) },
  { key: "fetchlog.maxRows", title: "Requests shown", section: "Fetch log", description: "The service returns the newest 200 per source.", schema: z.number().int().min(20).max(1000), default: 200 },

  // ---- pieces
  { key: "pieces.followWorkspace", title: "Workspace for a piece an agent works on", section: "Pieces", description: "Where the app goes when it follows an agent and no Pieces panel is open.", default: "Post studio", ...choice(WORKSPACES, workspaceLabels) },
  { key: "pieces.follow", title: "Show what an agent works on", section: "Pieces", description: "When an agent renders a piece or runs `sb piece open`, select that project and piece and show its post preview.", schema: z.boolean(), default: true },
  { key: "pieces.template", title: "Template for a new piece", section: "Pieces", description: "A template id from the Assets panel. Empty: the project's own default, if it names one.", schema: z.string().max(60), default: "", control: "text" },
  { key: "pieces.kind", title: "Kind of a new piece", section: "Pieces", schema: z.string().max(30), default: "post", control: "text", suggestions: ["post", "note", "idea", "briefing", "report"] },
  { key: "pieces.channel", title: "Channel of a new piece", section: "Pieces", description: "Where pieces usually go, e.g. linkedin or newsletter.", schema: z.string().max(40), default: "", control: "text", suggestions: ["linkedin", "newsletter", "internal"] },
  { key: "pieces.postingDays", title: "Usual posting days", section: "Pieces", description: "Weekdays separated by commas (Mon, Tue, …). Marked in the Schedule panel and used by “Next free slot”.", schema: z.string().max(60), default: "Tue, Wed, Thu", control: "text" },
  { key: "pieces.postingTime", title: "Usual posting time", section: "Pieces", description: "24-hour time, e.g. 08:30. Used by “Next free slot”.", schema: z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, "Use HH:MM"), default: "08:30", control: "text" },
  { key: "pieces.scheduleDays", title: "Days shown in the Schedule panel", section: "Pieces", schema: z.number().int().min(7).max(90), default: 21 },

  // ---- post preview (browser only: not written to any project)
  { key: "preview.author", title: "Name shown in the post preview", section: "Post preview", description: "Kept in this browser only.", schema: z.string().max(80), default: "", control: "text" },
  { key: "preview.headline", title: "Headline under the name", section: "Post preview", description: "Kept in this browser only.", schema: z.string().max(120), default: "", control: "text" },
  { key: "preview.lines", title: "Lines visible before “…more”", section: "Post preview", description: "A feed shows about three lines of a post before cutting it.", schema: z.number().int().min(1).max(12), default: 3 },
  { key: "preview.width", title: "Preview width", section: "Post preview", default: "desktop", ...choice(["phone", "desktop"], { phone: "Phone (360 px)", desktop: "Desktop feed (540 px)" }) },

  // ---- confirmations
  { key: "confirm.handover", title: "Ask before rebuilding a handover", section: "Confirmations", description: "The button asks “Really?” first. It rewrites dist/handover in the project.", schema: z.boolean(), default: false },
  { key: "confirm.jobRun", title: "Ask before running a job", section: "Confirmations", description: "A job fetches from the web under the fetcher's rules.", schema: z.boolean(), default: true },
  { key: "confirm.render", title: "Ask before rendering a piece", section: "Confirmations", description: "Rendering rewrites the piece's render folder.", schema: z.boolean(), default: false },
  { key: "confirm.delete", title: "Ask before deleting a piece or note", section: "Confirmations", description: "The Delete buttons ask “Really?” first. Deleting can be undone from the action history either way.", schema: z.boolean(), default: true },

  // ---- what agents get
  { key: "agents.rowCap", title: "Rows a panel hands to an agent", section: "Agents", description: "The most rows of a list or query result in a panel's description and in the result of sql.query run by an agent.", default: "100", ...choice(["25", "100", "250", "1000"], { "25": "25 rows", "100": "100 rows", "250": "250 rows", "1000": "1,000 rows" }) },
  { key: "agents.textCap", title: "Characters of text a panel hands to an agent", section: "Agents", description: "Documents and deliverables are cut after this many characters.", default: "30000", ...choice(["8000", "30000", "100000"], { "8000": "8,000", "30000": "30,000", "100000": "100,000" }) },
];

/** Carry the settings that code outside React needs into `prefs`, now and whenever one changes. */
export function followSettings(wb: Werkbank): void {
  const get = <T>(key: string) => wb.settings.get<T>(key);
  const apply = () => {
    setPrefs({
      locale: get<string>("format.locale"),
      isoDates: get<string>("format.dates") === "iso",
      relativeTimes: get<boolean>("format.relative"),
      firstProject: get<string>("projects.first").trim(),
      rowCap: Number(get<string>("agents.rowCap")),
      textCap: Number(get<string>("agents.textCap")),
      fetchOutcome: get<"all" | "refused">("fetchlog.defaultOutcome"),
      every: { project: get<number>("data.refreshSeconds") * 1000, activity: get<number>("data.activitySeconds") * 1000, jobs: get<number>("data.jobsSeconds") * 1000, system: get<number>("data.systemSeconds") * 1000 },
    });
    document.documentElement.dataset.sbDensity = get<string>("tables.density");
  };
  apply();
  wb.settings.subscribe(apply);
}

/** Weekday numbers (0 = Sunday) from "Tue, Wed, Thu". */
export function weekdays(text: string): number[] {
  const names = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  return [...new Set(text.split(/[,\s]+/).map((w) => names.indexOf(w.slice(0, 3).toLowerCase())).filter((n) => n >= 0))];
}
