import { useSyncExternalStore } from "react";
import { prefs, usePrefsVersion } from "../prefs";

/**
 * The app's one data store: answers of the local Sourcebound service (`sb ui`), cached per address.
 *
 * Panels read through `useApi`; nothing is kept in a panel. An address is loaded when the first
 * panel shows it and reloaded on a timer while a panel still does (hidden tabs unsubscribe, so
 * they cost nothing). The project files are the truth: this store never holds a change of its own.
 */

export interface Entry<T = unknown> {
  data?: T;
  error?: string;
  loading: boolean;
  loadedAt?: number;
}

const EMPTY: Entry = { loading: false };
const LOADING: Entry = { loading: true };

class Api {
  private entries = new Map<string, Entry>();
  private texts = new Map<string, string>();
  private listeners = new Map<string, Set<() => void>>();
  private every = new Map<string, number>();
  private inflight = new Set<string>();
  private timer: ReturnType<typeof setInterval> | null = null;
  /** Reload interval for ordinary addresses, in milliseconds (a setting). */
  get interval(): number {
    return prefs.every.project;
  }
  /** Whether the service answered the last request; shown in the status bar. */
  online: boolean | null = null;
  private statusListeners = new Set<() => void>();

  get<T>(path: string | null): Entry<T> {
    if (!path) return EMPTY as Entry<T>;
    return (this.entries.get(path) ?? LOADING) as Entry<T>;
  }

  /** The cached answer, for `describe` and commands; undefined while it has not been loaded. */
  peek<T>(path: string): T | undefined {
    return this.entries.get(path)?.data as T | undefined;
  }

  subscribe(path: string | null, listener: () => void, every?: number): () => void {
    if (!path) return () => {};
    let set = this.listeners.get(path);
    if (!set) this.listeners.set(path, (set = new Set()));
    set.add(listener);
    if (every) this.every.set(path, every);
    if (!this.entries.has(path)) void this.load(path);
    this.timer ??= setInterval(() => this.tick(), 1000);
    return () => {
      set.delete(listener);
      if (set.size === 0) this.listeners.delete(path);
      if (this.listeners.size === 0 && this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }

  subscribeStatus = (listener: () => void) => {
    this.statusListeners.add(listener);
    return () => void this.statusListeners.delete(listener);
  };

  private tick(): void {
    if (document.visibilityState !== "visible") return;
    const now = Date.now();
    for (const path of this.listeners.keys()) {
      const entry = this.entries.get(path);
      if (entry && now - (entry.loadedAt ?? 0) >= (this.every.get(path) ?? this.interval)) void this.load(path);
    }
  }

  private setOnline(online: boolean): void {
    if (this.online === online) return;
    this.online = online;
    this.statusListeners.forEach((l) => l());
  }

  async load(path: string): Promise<void> {
    if (this.inflight.has(path)) return;
    this.inflight.add(path);
    // What was there stays on screen while the next answer is on its way.
    const before = this.entries.get(path);
    const done = (entry: Entry, notify = true) => {
      this.inflight.delete(path);
      this.entries.set(path, entry);
      if (notify) this.listeners.get(path)?.forEach((l) => l());
    };
    try {
      const response = await fetch(path, { headers: { accept: "application/json" } });
      const text = await response.text();
      this.setOnline(true);
      if (!response.ok) {
        let message = `The Sourcebound service answered ${response.status}.`;
        try {
          message = (JSON.parse(text) as { error?: string }).error ?? message;
        } catch {
          /* not JSON: keep the status */
        }
        this.texts.delete(path);
        return done({ error: message, loading: false, loadedAt: Date.now() });
      }
      // Only tell the panels when the answer differs, so an unchanged project does not re-render every few seconds.
      if (before && !before.error && this.texts.get(path) === text) {
        before.loadedAt = Date.now();
        return done(before, false);
      }
      this.texts.set(path, text);
      done({ data: JSON.parse(text), loading: false, loadedAt: Date.now() });
    } catch {
      this.setOnline(false);
      this.texts.delete(path);
      done({ data: before?.data, error: "The Sourcebound service is not reachable. Start it with `sb ui`.", loading: false, loadedAt: Date.now() });
    }
  }

  /** Reload everything a panel shows right now (after a command changed a file). */
  async refresh(prefix = ""): Promise<void> {
    await Promise.all([...this.listeners.keys()].filter((p) => p.startsWith(prefix)).map((p) => this.load(p)));
  }

  /** Load an address once and return the answer (for commands; throws with the service's message). */
  async fetch<T>(path: string): Promise<T> {
    await this.load(path);
    const entry = this.entries.get(path);
    if (entry?.data === undefined || entry.error) throw new Error(entry?.error ?? "No answer from the Sourcebound service.");
    return entry.data as T;
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    let response: Response;
    try {
      response = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    } catch {
      this.setOnline(false);
      throw new Error("The Sourcebound service is not reachable. Start it with `sb ui`.");
    }
    this.setOnline(true);
    const answer = (await response.json().catch(() => ({}))) as T & { error?: string };
    if (!response.ok) throw new Error(answer.error ?? `The Sourcebound service answered ${response.status}.`);
    return answer;
  }
}

export const api = new Api();

/** An answer of the service, kept current while the panel is visible. `every` is a reload interval in ms. */
export function useApi<T>(path: string | null, every?: number): Entry<T> {
  usePrefsVersion(); // a changed preference (date format, locale) redraws every panel that shows data
  return useSyncExternalStore(
    (listener) => api.subscribe(path, listener, every),
    () => api.get<T>(path),
  );
}

export const useOnline = () => useSyncExternalStore(api.subscribeStatus, () => api.online);

// ---- addresses -----------------------------------------------------------------

const enc = encodeURIComponent;
export const paths = {
  projects: "/api/projects",
  project: (id: string) => `/api/projects/${enc(id)}`,
  handover: (id: string) => `/api/projects/${enc(id)}/handover`,
  file: (id: string, path: string) => `/api/projects/${enc(id)}/file?path=${enc(path)}`,
  /** A file of the project; `true` or "png": a PDF figure as an image; "pdf": a Word or PowerPoint file as PDF. */
  raw: (id: string, path: string, as: boolean | "png" | "pdf" = false) => `/api/projects/${enc(id)}/raw?path=${enc(path)}${as ? `&as=${as === true ? "png" : as}` : ""}`,
  render: (id: string) => `/api/projects/${enc(id)}/render`,
  run: (id: string) => `/api/projects/${enc(id)}/run`,
  notes: (id: string) => `/api/projects/${enc(id)}/notes`,
  fetch: "/api/fetch",
  activity: "/api/activity",
  focus: "/api/focus",
  workspace: "/api/workspace",
  system: "/api/system",
  lake: "/api/lake",
  lakeTable: (name: string, limit: number) => `/api/lake/table?name=${enc(name)}&limit=${limit}`,
  sql: "/api/sql",
  connections: "/api/connections",
  jobs: "/api/jobs",
  jobRun: "/api/jobs/run",
  assets: "/api/assets",
  pieces: (id: string) => `/api/projects/${enc(id)}/pieces`,
};

// ---- what the service returns --------------------------------------------------

export interface Gate {
  id: "G1" | "G2" | "G3";
  title: string;
  passed: boolean;
  basis: string;
}

export interface LogLine {
  date: string;
  who: string;
  text: string;
}

export interface Summary {
  id: string;
  path: string;
  slug: string;
  title: string;
  error?: string;
  lang?: string;
  phase?: string;
  kind?: string;
  topic?: string;
  pieces?: { total: number; by_status: Record<string, number> };
  created?: string;
  gates?: Gate[];
  hypotheses?: { total: number; by_status: Record<string, number>; frozen: string | null };
  claims?: { total: number; by_status: Record<string, number> };
  web_sources?: number;
  results?: number;
  reviews?: number;
  deliverables?: string[];
  last_change?: string | null;
  last_log?: LogLine | null;
}

export interface Hypothesis {
  id: string;
  statement: string;
  status: string;
  prediction?: string;
  test?: string;
  data?: string[] | string;
  metric?: string;
  decision_rule?: string;
  kill?: string;
  priority?: number;
  exploratory?: boolean;
  motivated_by?: string[];
  results?: string[];
  registration: "unchanged" | "changed" | "frozen without hash" | "not frozen";
}

export interface Evidence {
  ref: string;
  stance?: string;
  loc?: string;
  quote?: string;
  note?: string;
}

export interface Claim {
  id: string;
  text: string;
  kind?: string;
  status?: string;
  evidence?: Evidence[];
  note?: string;
}

export interface WebSource {
  id: string;
  title?: string;
  url?: string;
  publisher?: string;
  accessed?: string;
  date?: string;
  author?: string;
}

export interface Result {
  key: string;
  value: unknown;
  display: string;
  unit: string | null;
  ci: unknown;
  hypothesis: string | null;
  note: string | null;
  script: string | null;
  git: string | null;
  data: Record<string, number | string | null> | null;
  at: string | null;
}

export interface DocumentFile {
  path: string;
  group: string;
  name: string;
  changed: string;
  bytes: number;
}

export interface Note {
  id: string;
  title: string;
  kind: string;
  status: string;
  deliverable: string;
  text: string;
  prompt: string;
  created: string;
  updated: string;
}

export interface HandoverState {
  built: boolean;
  at?: string;
  stale?: boolean;
  changed_since?: string[];
}

export interface DeliverableFolder {
  name: string;
  kind: string;
  format: "latex" | "markdown";
  sections: number;
  pdf: string | null;
  /** What `sb render deliverables/<name>` wrote in other formats (Word, slides), newest first. */
  renders?: PieceRender[];
}

export interface Detail extends Summary {
  card: Record<string, unknown>;
  frozen: { date?: string; git?: string; amendments?: number } | null;
  amendments: { hypothesis?: string; reason?: string; date?: string }[];
  hypothesis_list: Hypothesis[];
  claim_list: Claim[];
  source_list: WebSource[];
  result_list: Result[];
  result_problems: { errors: string[]; warnings: string[] };
  documents: DocumentFile[];
  log: LogLine[];
  deliverable_folders: DeliverableFolder[];
  handover: HandoverState;
  notes: Note[];
}

export interface HandoverSection {
  file: string;
  source: string;
  appendix: boolean;
  results: string[];
  citations: string[];
  tables: string[];
  figures: string[];
}

export interface HandoverDeliverable {
  name: string;
  title?: string;
  subtitle?: string;
  author?: string;
  date?: string;
  keywords?: string;
  sections: HandoverSection[];
  unconverted: string[];
}

export interface Reference {
  type: string;
  year: string;
  author?: string;
  editor?: string;
  title?: string;
  journaltitle?: string;
  journal?: string;
  booktitle?: string;
  publisher?: string;
  institution?: string;
  volume?: string;
  number?: string;
  pages?: string;
  doi?: string;
  url?: string;
}

export interface HandoverResult {
  value: unknown;
  display: string;
  unit: string | null;
  hypothesis: string | null;
  note: string | null;
  provenance?: { script?: string; git?: string; data?: Record<string, unknown>; at?: string };
}

export interface Handover extends HandoverState {
  handover?: { slug: string; title: string; lang: string; created_at: string; commit: string | null; deliverables: HandoverDeliverable[]; problems: string[] };
  sections?: Record<string, string>;
  results?: Record<string, HandoverResult>;
  tables?: Record<string, { columns: string[]; rows: string[][] }>;
  references?: Record<string, Reference>;
  web_sources?: Record<string, WebSource>;
  edited_by_person?: string[] | null;
  figures?: string[];
  /** The service can turn a PDF figure into an image (pdftoppm or sips); else the page shows the PDF itself. */
  pdf_as_png?: boolean;
  /** How the service shows a Word or PowerPoint render as PDF ("libreoffice", "word"), or null if it cannot. */
  office_as_pdf?: string | null;
}

export interface FetchEntry {
  ts: string;
  url: string;
  status: number | string;
  sha256: string | null;
  path: string | null;
}

export interface FetchLog {
  raw_root: string;
  min_interval_s: number;
  sources: { source: string; requests: number; stopped: { host: string; reason: string; since: string }[]; entries: FetchEntry[] }[];
}

export interface ActivityEvent {
  ts: string;
  event: string;
  session: string;
  project: string | null;
  cwd: string;
  agent: string | null;
  tool: string | null;
  summary: string;
}

export interface RunResult {
  command: string;
  project: string;
  exit_code: number;
  output: string;
  at: string;
}

// ---- beyond one study: the system, the lake, connections, jobs, assets, pieces ----

export interface SystemReport {
  sourcebound: { version: string; python: string; executable: string; platform: string; checkout: string | null; packages: Record<string, string | null> };
  configuration: Record<string, unknown> & { file: string; from: string; data_root: string; registry: string; projects_dir: string | null };
  lake: { catalog: string; data_path: string; tables?: number; snapshot?: number; error?: string };
  storage: { id: string; path: string; exists: boolean; files?: number; bytes?: number }[];
  registry: Record<string, number>;
  tools: { id: string; title: string; installed: boolean; path: string; version: string; purpose: string; get: string }[];
  latex: Record<string, boolean>;
  zotero: { url: string; running: boolean };
  modules: { id: string; installed: boolean; install: string; purpose: string }[];
  plugins: PluginInfo[];
  renderers: RendererInfo[];
  setup: { id: string; title: string; done: boolean; detail: string; fix: string }[];
  activity_log: string;
  problems: { level: string; text: string; fix: string }[];
}

export interface PluginInfo {
  name: string;
  package: string;
  version: string;
  error: string | null;
  renderers: string[];
  commands: string[];
}

export interface RendererInfo {
  kind: string;
  title: string;
  plugin: string;
  outputs: string[];
}

export interface LakeColumn {
  name: string;
  type: string;
  description: string;
  unit: string;
}

export interface LakeTable {
  name: string;
  schema: string;
  table: string;
  rows: number | null;
  comment: string;
  contract: { title: string; description: string; grain: string; primary_key: string[]; license: string; sources: string[]; pipeline: string; owner: string } | null;
  restricted: boolean;
  columns: LakeColumn[];
}

export interface Lake {
  catalog: string;
  data_path: string;
  tables: LakeTable[];
  snapshots: { id: number; at: string; changes: string; author: string; message: string }[];
}

export interface QueryResult {
  target: string;
  columns: string[];
  types: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  seconds: number;
}

export interface EnvNeed {
  name: string;
  set: boolean;
}

export interface DataSource {
  id: string;
  name: string;
  access: string;
  status: string;
  docs: number;
  url: string;
  publisher: string;
  license: string;
  terms: string;
  tables: string[];
  mcp: string;
  frequency: string;
  checked: string;
  needs_env: EnvNeed[];
  database: boolean;
  /** The database connection, when the entry describes one field by field (never a password). */
  connection: DatabaseConnection | null;
  last_request: { ts: string; status: number | string } | null;
  stopped_hosts: string[];
}

export type DatabaseDriver = "mssql" | "postgresql" | "mysql" | "sqlite" | "duckdb";
/** The `database:` block of a register entry, as `databases.check` writes it. */
export interface DatabaseSpec {
  driver: DatabaseDriver;
  server?: string;
  port?: number;
  database?: string;
  auth?: "sql" | "windows" | "none";
  user?: string;
  password_env?: string;
  encrypt?: boolean;
  trust_server_certificate?: boolean;
  ssl_mode?: "disable" | "prefer" | "require" | "verify-full";
  timeout?: number;
  path?: string;
}
export interface ConnectionTest {
  status: "ok" | "failed";
  message: string;
  at: string;
}
export interface DatabaseConnection {
  spec: DatabaseSpec;
  /** Fields the entry gets wrong (an entry edited by hand), one message each. */
  problems: Record<string, string> | null;
  where: string;
  needs_password: boolean;
  /** A password was typed in this session; it lives only in the memory of `sb ui`. */
  password_in_session: boolean;
  ready: boolean;
  why: string;
  last_test: ConnectionTest | null;
}
/** What saving a connection answers: `before` is the entry's earlier text (null when it was created). */
export interface ConnectionSaved {
  path: string;
  created?: boolean;
  before: string | null;
}

export interface McpServer {
  name: string;
  transport: string;
  url?: string;
  command?: string;
  args?: string[];
  env: EnvNeed[];
  note?: string;
  source?: string;
}

export interface Connections {
  sources: DataSource[];
  sql_targets: { id: string; title: string; ready: boolean; hint: string; tested?: "ok" | "failed" | null }[];
  mcp_servers: McpServer[];
  seconds_between_requests: number;
}

export interface Job {
  id: string;
  title: string;
  run?: string;
  every?: string;
  enabled: boolean;
  table?: string;
  source?: string;
  last_run?: string | null;
  last_status?: string | null;
  last_seconds?: number | null;
  last_message?: string;
  next_run?: string;
  due?: boolean;
  error?: string;
}

export interface JobRun {
  at: string;
  job: string;
  status: string;
  seconds: number;
  message: string;
  blocked?: boolean;
}

export interface Jobs {
  jobs: Job[];
  log: JobRun[];
  schedule_hint: string;
}

export interface Design {
  id: string;
  name: string;
  origin: string;
  folder: string | null;
  colors: Record<string, string>;
  error: string | null;
}

export interface Template {
  id: string;
  kind: string;
  title: string;
  design: string;
  for: string[];
  origin: string;
  folder: string;
  error: string | null;
}

export interface Assets {
  designs: Design[];
  templates: Template[];
  plugins: PluginInfo[];
  renderers: RendererInfo[];
  registry: string;
}

export interface PieceRender {
  template: string;
  kind: string;
  design: string;
  at: string;
  /** Paths relative to the project. */
  files: string[];
  /** Result keys whose value changed since this render. */
  stale: string[];
  /** What the renderer adjusted or could not do (a label moved, a typeface missing). */
  notes?: string[];
}

export interface Piece {
  id: string;
  title: string;
  kind?: string;
  template?: string;
  design?: string;
  status?: string;
  lang?: string;
  channel?: string;
  note?: string;
  prompt?: string;
  url?: string;
  scheduled_at?: string;
  published_at?: string;
  created?: string;
  updated?: string;
  error?: string;
  text: string;
  data_files: string[];
  /** The content of those files by name without ".yaml" (e.g. slides), for the Slides view and its agents. */
  data?: Record<string, string>;
  renders: PieceRender[];
}

export interface Pieces {
  project: string;
  statuses: string[];
  defaults: { template?: string; design?: string };
  /** Who posts this desk's pieces, from `preview:` in project.yaml (e.g. an organisation's page). */
  preview?: { author?: string; headline?: string };
  /** Where `sb piece export` copies a piece (`export.dir` in project.yaml), or null. */
  export_dir?: string | null;
  pieces: Piece[];
  templates: Template[];
}

export interface PieceCheck {
  id: string;
  errors: string[];
  warnings: string[];
}
