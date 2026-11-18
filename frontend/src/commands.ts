import type { Command, Werkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, type ConnectionSaved, type ConnectionTest, type DatabaseSpec, type JobRun, type Note, type Piece, type PieceCheck, type QueryResult, type RunResult } from "./data/api";
import { databaseSpec } from "./data/databases";
import { prefs } from "./prefs";
import { readCheck, runs } from "./data/runs";

/**
 * What a person or an agent can do in the app beyond arranging panels. Each command does what
 * a command of the `sb` command line does; the app writes nothing the command line could not.
 *
 * Risk classes: reading and checking are `read`; notes are `local` (the app's own records, with
 * an inverse); anything that writes other project files is `external`, so an agent's request
 * waits for the person's approval.
 */

const project = z.string().min(1).describe("Project id as listed by the Projects panel (the project's slug)");

async function sb(projectId: string, command: string): Promise<RunResult> {
  const run = runs.start(projectId, command);
  try {
    const result = await api.post<RunResult>(paths.run(projectId), { command });
    runs.finish(run, result);
    void api.refresh();
    return result;
  } catch (error) {
    runs.finish(run, { error: (error as Error).message });
    throw error;
  }
}

const noteFields = {
  title: z.string().min(1).max(200).describe("What is wanted, in a few words"),
  kind: z.string().max(40).describe("paper, note, infographic, post, slides, video, or any other word").optional(),
  status: z.enum(["idea", "planned", "drafting", "review", "done", "dropped"]).optional(),
  deliverable: z.string().max(80).describe("Folder name under deliverables/ once the deliverable exists").optional(),
  text: z.string().max(20_000).describe("Notes: audience, length, what to keep in mind").optional(),
  prompt: z.string().max(20_000).describe("The prompt an agent is given to write it").optional(),
};

export const commands: Command<Werkbank, any>[] = [
  {
    id: "data.refresh",
    title: "Reload project data",
    category: "Sourcebound",
    risk: "read",
    log: false,
    run: () => api.refresh(),
  },
  {
    id: "sb.check",
    title: "Run sb check",
    category: "Sourcebound",
    risk: "read",
    input: z.object({ project, offline: z.boolean().describe("Skip the look-up of citation keys in Zotero").optional() }),
    run: async (_ctx, i: { project: string; offline?: boolean }) => {
      const result = await sb(i.project, i.offline ? "check-offline" : "check");
      return { ...result, ...readCheck(result.output) };
    },
  },
  {
    id: "sb.reviewEdits",
    title: "List sections a person edited (sb review-edits)",
    category: "Sourcebound",
    risk: "read",
    input: z.object({ project }),
    run: (_ctx, i: { project: string }) => sb(i.project, "review-edits"),
  },
  {
    id: "sb.handover",
    title: "Rebuild the handover (sb handover)",
    category: "Sourcebound",
    // Rewrites dist/handover in the project and may compile diagrams: files outside the app, no inverse.
    risk: "external",
    input: z.object({ project }),
    run: (_ctx, i: { project: string }) => sb(i.project, "handover"),
  },
  {
    id: "vscode.workspace",
    title: "Show the VS Code workspace of all projects",
    category: "Sourcebound",
    risk: "read",
    palette: false,
    run: () => api.fetch<{ path: string; workspace: unknown }>(paths.workspace),
  },
  {
    id: "vscode.write",
    title: "Write the VS Code workspace file (sb workspace)",
    category: "Sourcebound",
    risk: "external",
    input: z.object({ path: z.string().describe("Where to write it; default: research.code-workspace in the projects folder").optional() }),
    run: (_ctx, i: { path?: string }) => api.post<{ path: string }>(paths.workspace, { path: i?.path }),
  },
  {
    id: "note.create",
    title: "Add a deliverable note",
    category: "Deliverables",
    risk: "local",
    palette: false,
    input: z.object({ project, ...noteFields }),
    run: async (_ctx, { project: id, ...fields }: { project: string } & Partial<Note>) => {
      const { note } = await api.post<{ note: Note }>(paths.notes(id), { op: "add", ...fields });
      void api.refresh(paths.project(id));
      return note;
    },
    undo: (_ctx, i: { project: string }, created) =>
      void api.post(paths.notes(i.project), { op: "rm", id: (created as Note).id }).then(() => api.refresh(paths.project(i.project))),
  },
  {
    id: "note.update",
    title: "Change a deliverable note",
    category: "Deliverables",
    risk: "local",
    palette: false,
    input: z.object({ project, id: z.string().describe("Note id, e.g. N003"), patch: z.object({ ...noteFields, title: noteFields.title.optional() }) }),
    run: async (_ctx, i: { project: string; id: string; patch: Partial<Note> }) => {
      const answer = await api.post<{ before: Note; note: Note }>(paths.notes(i.project), { op: "set", id: i.id, ...i.patch });
      void api.refresh(paths.project(i.project));
      return answer;
    },
    undo: (_ctx, i: { project: string }, answer) =>
      void api.post(paths.notes(i.project), { op: "put", note: (answer as { before: Note }).before }).then(() => api.refresh(paths.project(i.project))),
  },
  {
    id: "note.delete",
    title: "Delete a deliverable note",
    category: "Deliverables",
    risk: "local",
    palette: false,
    input: z.object({ project, id: z.string().describe("Note id, e.g. N003") }),
    run: async (_ctx, i: { project: string; id: string }) => {
      const { removed } = await api.post<{ removed: Note }>(paths.notes(i.project), { op: "rm", id: i.id });
      void api.refresh(paths.project(i.project));
      return removed;
    },
    undo: (_ctx, i: { project: string }, removed) =>
      void api.post(paths.notes(i.project), { op: "put", note: removed }).then(() => api.refresh(paths.project(i.project))),
  },
  // ---- data: database connections (what `sb datasource add|set|test|rm` do). No command carries a
  // password: its input is recorded in the history. The panel hands a password to the service directly.
  {
    id: "connection.save",
    title: "Create or change a database connection",
    category: "Data",
    risk: "local",
    palette: false,
    input: z.object({
      id: z.string().regex(/^[a-z][a-z0-9_]*$/).describe("Source id: lowercase letters, digits and _"),
      name: z.string().min(1).max(120).describe("What the person calls it").optional(),
      spec: databaseSpec,
    }),
    run: async (_ctx, i: { id: string; name?: string; spec: DatabaseSpec }) => {
      const saved = await api.post<ConnectionSaved>(paths.connections, { op: "save", ...i });
      void api.refresh(paths.connections);
      return saved;
    },
    undo: (_ctx, i: { id: string }, saved) => {
      const s = saved as ConnectionSaved;
      void api.post(paths.connections, s.before === null ? { op: "remove", id: i.id } : { op: "restore", id: i.id, text: s.before }).then(() => api.refresh(paths.connections));
    },
  },
  {
    id: "connection.remove",
    title: "Remove a database connection",
    category: "Data",
    risk: "local",
    palette: false,
    input: z.object({ id: z.string().describe("Source id of a database connection nothing was read from yet") }),
    run: async (_ctx, i: { id: string }) => {
      const removed = await api.post<ConnectionSaved>(paths.connections, { op: "remove", id: i.id });
      void api.refresh(paths.connections);
      return removed;
    },
    undo: (_ctx, i: { id: string }, removed) =>
      void api.post(paths.connections, { op: "restore", id: i.id, text: (removed as ConnectionSaved).before }).then(() => api.refresh(paths.connections)),
  },
  {
    id: "connection.test",
    title: "Test a database connection",
    category: "Data",
    // Connects and asks for the server's version; like sql.query it only reads.
    risk: "read",
    input: z.object({ id: z.string().describe("Source id of a database connection") }),
    run: async (_ctx, i: { id: string }) => {
      const result = await api.post<ConnectionTest>(paths.connections, { op: "test", id: i.id });
      void api.refresh(paths.connections);
      return { id: i.id, ...result };
    },
  },
  {
    id: "connection.forget",
    title: "Forget the password typed for a connection",
    category: "Data",
    risk: "read",
    palette: false,
    input: z.object({ id: z.string() }),
    run: async (_ctx, i: { id: string }) => {
      const answer = await api.post(paths.connections, { op: "forget", id: i.id });
      void api.refresh(paths.connections);
      return answer;
    },
  },
  // ---- data: one reading statement against the lake or a registered database
  {
    id: "sql.query",
    title: "Run a read-only SQL statement",
    category: "Data",
    risk: "read",
    palette: false,
    input: z.object({
      target: z.string().describe("`lake` for the data lake (tables as <schema>.<table>), or the id of a database source from the Connections panel").default("lake"),
      sql: z.string().min(1).max(8000).describe("One statement that reads: SELECT, WITH, SHOW, DESCRIBE or EXPLAIN. The service refuses anything else."),
      limit: z.number().int().min(1).max(5000).describe("Most rows to return").optional(),
    }),
    run: async ({ wb, actor }, i: { target?: string; sql: string; limit?: number }) => {
      const limit = i.limit ?? Number(wb.settings.get<string>("sql.rowLimit"));
      const result = await api.post<QueryResult>(paths.sql, { target: i.target ?? "lake", query: i.sql, limit });
      // An agent gets a bounded answer; the console gets what its row limit allows.
      if (actor !== "agent" || result.rows.length <= prefs.rowCap) return result;
      return { ...result, rows: result.rows.slice(0, prefs.rowCap), truncated: true, note: `First ${prefs.rowCap} of ${result.row_count} rows (the person's cap for agents). Aggregate in SQL, or add WHERE and ORDER BY.` };
    },
  },
  {
    id: "job.run",
    title: "Run a job now",
    category: "Data",
    // A job fetches from the web (under the fetcher's rules) and writes to the lake: an effect outside the app.
    risk: "external",
    palette: false,
    input: z.object({ id: z.string().min(1).describe("Job id as listed by the Jobs panel") }),
    run: async (_ctx, i: { id: string }) => {
      const line = await api.post<JobRun>(paths.jobRun, { id: i.id });
      void api.refresh(paths.jobs);
      return line;
    },
  },

  // ---- pieces: small outputs of ongoing research
  {
    id: "piece.create",
    title: "Add a piece",
    category: "Pieces",
    risk: "local",
    palette: false,
    input: z.object({
      project,
      title: z.string().min(1).max(200),
      id: z.string().regex(/^[a-z0-9][a-z0-9_-]*$/).describe("Folder name under pieces/; made from the date and title when left out").optional(),
      kind: z.string().max(30).describe("post, note, idea, briefing, report, …").optional(),
      template: z.string().max(60).describe("A template id from the Assets panel").optional(),
      channel: z.string().max(40).optional(),
      lang: z.string().max(5).optional(),
      text: z.string().max(100_000).describe("The text in the handover notation: {{result:key}} for recorded numbers, [@W-0001] for sources").optional(),
      note: z.string().max(4000).optional(),
      prompt: z.string().max(20_000).optional(),
    }),
    run: async (_ctx, { project: id, ...fields }: { project: string } & Record<string, unknown>) => {
      const { piece } = await api.post<{ piece: Piece }>(paths.pieces(id), { op: "add", ...fields });
      void api.refresh(paths.pieces(id));
      return piece;
    },
    undo: (_ctx, i: { project: string }, created) =>
      void api.post(paths.pieces(i.project), { op: "rm", id: (created as Piece).id }).then(() => api.refresh(paths.pieces(i.project))),
  },
  {
    id: "piece.update",
    title: "Change a piece",
    category: "Pieces",
    risk: "local",
    palette: false,
    input: z.object({
      project,
      id: z.string().min(1),
      patch: z.object({
        title: z.string().min(1).max(200).optional(),
        kind: z.string().max(30).optional(),
        template: z.string().max(60).optional(),
        design: z.string().max(60).optional(),
        channel: z.string().max(40).optional(),
        lang: z.string().max(5).optional(),
        note: z.string().max(4000).optional(),
        prompt: z.string().max(20_000).optional(),
        url: z.string().max(400).optional(),
        text: z.string().max(100_000).optional(),
        status: z.enum(["idea", "draft", "review", "dropped"]).describe("approved, scheduled and published are the person's decisions: use piece.decide").optional(),
      }),
    }),
    run: async (_ctx, i: { project: string; id: string; patch: Record<string, unknown> }) => {
      const answer = await api.post<{ before: Piece; piece: Piece }>(paths.pieces(i.project), { op: "set", id: i.id, ...i.patch });
      void api.refresh(paths.pieces(i.project));
      return answer;
    },
    undo: (_ctx, i: { project: string; id: string; patch: Record<string, unknown> }, answer) => {
      const before = (answer as { before: Record<string, unknown> }).before;
      // Put back exactly the fields this change touched.
      const back = Object.fromEntries(Object.keys(i.patch).map((k) => [k, before[k] ?? ""]));
      void api.post(paths.pieces(i.project), { op: "set", id: i.id, ...back }).then(() => api.refresh(paths.pieces(i.project)));
    },
  },
  {
    id: "piece.format",
    title: "What a piece's template needs, and the format of its files",
    category: "Pieces",
    risk: "read",
    palette: false,
    input: z.object({
      project,
      id: z.string().min(1),
      template: z.string().max(60).describe("Default: the piece's template, else the project's piece_defaults").optional(),
    }),
    run: async (_ctx, i: { project: string; id: string; template?: string }) =>
      api.post<{ template: string; kind: string; data_files: string[]; guide: string; current: Record<string, string | null> }>(paths.pieces(i.project), { op: "format", id: i.id, template: i.template }),
  },
  {
    id: "piece.data",
    title: "Write a data file of a piece (e.g. slides.yaml)",
    category: "Pieces",
    // Structured content a template reads, beside text.md. Validated as YAML holding a mapping; the render
    // checks the rest (fields, sizes, sources). Undo puts back what was there.
    risk: "local",
    palette: false,
    input: z.object({
      project,
      id: z.string().min(1),
      name: z.string().regex(/^[a-z][a-z0-9_-]{0,40}$/).describe('The file without ".yaml", e.g. "slides" (piece.format lists what the template reads)'),
      text: z.string().max(200_000).describe("The whole file as YAML, in the format piece.format returns"),
    }),
    run: async (_ctx, i: { project: string; id: string; name: string; text: string }) => {
      const answer = await api.post<{ name: string; before: string | null }>(paths.pieces(i.project), { op: "data", id: i.id, name: i.name, text: i.text });
      void api.refresh(paths.pieces(i.project));
      return answer;
    },
    undo: (_ctx, i: { project: string; id: string; name: string }, answer) =>
      void api
        .post(paths.pieces(i.project), { op: "data", id: i.id, name: i.name, text: (answer as { before: string | null }).before })
        .then(() => api.refresh(paths.pieces(i.project))),
  },
  {
    id: "piece.decide",
    title: "Approve, schedule or mark a piece as published",
    category: "Pieces",
    // The person's decision about what goes out. Nothing is posted by this app; the status only records the decision.
    risk: "external",
    palette: false,
    input: z.object({
      project,
      id: z.string().min(1),
      status: z.enum(["approved", "scheduled", "published"]),
      scheduled_at: z.string().describe("For `scheduled`: date and time, e.g. 2026-11-20 08:30 (local time)").optional(),
      url: z.string().max(400).describe("For `published`: where it went").optional(),
    }),
    run: async (_ctx, i: { project: string; id: string; status: string; scheduled_at?: string; url?: string }) => {
      const body: Record<string, unknown> = { op: "set", id: i.id, status: i.status };
      if (i.scheduled_at) body.scheduled_at = i.scheduled_at;
      if (i.url) body.url = i.url;
      if (i.status === "published") body.published_at = new Date().toISOString().slice(0, 16);
      const answer = await api.post<{ before: Piece; piece: Piece }>(paths.pieces(i.project), body);
      void api.refresh(paths.pieces(i.project));
      return answer.piece;
    },
  },
  {
    id: "piece.delete",
    title: "Delete a piece",
    category: "Pieces",
    risk: "local",
    palette: false,
    input: z.object({ project, id: z.string().min(1) }),
    run: async (_ctx, i: { project: string; id: string }) => {
      const { removed } = await api.post<{ removed: Piece }>(paths.pieces(i.project), { op: "rm", id: i.id });
      void api.refresh(paths.pieces(i.project));
      return removed;
    },
    undo: (_ctx, i: { project: string; id: string }) =>
      void api.post(paths.pieces(i.project), { op: "restore", id: i.id }).then(() => api.refresh(paths.pieces(i.project))),
  },
  {
    id: "piece.check",
    title: "Check a piece (sb piece check)",
    category: "Pieces",
    risk: "read",
    palette: false,
    input: z.object({ project, id: z.string().min(1) }),
    run: (_ctx, i: { project: string; id: string }) => api.post<PieceCheck>(paths.pieces(i.project), { op: "check", id: i.id }),
  },
  {
    id: "piece.render",
    title: "Render a piece with a template (sb render)",
    category: "Pieces",
    // Rewrites pieces/<id>/render/<template>/ in the project. The output can be rebuilt at any time, but it
    // is files outside the app and the command has no inverse, so it cannot be `local`.
    risk: "external",
    palette: false,
    input: z.object({ project, id: z.string().min(1), template: z.string().min(1).describe("A template id from the Assets panel"), design: z.string().describe("A design id; default: the template's").optional() }),
    run: async (_ctx, i: { project: string; id: string; template: string; design?: string }) => {
      const { render } = await api.post<{ render: Record<string, unknown> }>(paths.pieces(i.project), { op: "render", id: i.id, template: i.template, design: i.design });
      void api.refresh(paths.pieces(i.project));
      return render;
    },
  },
  {
    id: "piece.export",
    title: "Save a piece to a folder: post text, carousel PDF, slide images (sb piece export)",
    category: "Pieces",
    // Copies files to a folder outside the project (export.dir, e.g. a shared marketing folder). It never
    // deletes what it did not write, but it has no inverse: external. It posts nothing.
    risk: "external",
    palette: false,
    input: z.object({
      project,
      id: z.string().min(1),
      to: z.string().max(400).describe("The folder to save into; default: export.dir of the project, else the standard folder of this machine").optional(),
    }),
    run: async (_ctx, i: { project: string; id: string; to?: string }) => {
      const { export: done } = await api.post<{ export: { folder: string; files: string[] } }>(paths.pieces(i.project), { op: "export", id: i.id, to: i.to });
      return done;
    },
  },
  {
    id: "deliverable.render",
    title: "Render a deliverable with a template (sb render deliverables/NAME)",
    category: "Deliverables",
    // Rewrites dist/render/<name>/<template>/ in the project from the handover; as piece.render, files
    // outside the app without an inverse: external.
    risk: "external",
    palette: false,
    input: z.object({
      project,
      deliverable: z.string().min(1).describe("A folder under deliverables/"),
      template: z.string().min(1).describe("A template id from the Assets panel, e.g. a Word template"),
      design: z.string().describe("A design id; default: the template's").optional(),
    }),
    run: async (_ctx, i: { project: string; deliverable: string; template: string; design?: string }) => {
      const { render } = await api.post<{ render: Record<string, unknown> }>(paths.render(i.project), { deliverable: i.deliverable, template: i.template, design: i.design });
      void api.refresh(paths.project(i.project));
      return render;
    },
  },
];
