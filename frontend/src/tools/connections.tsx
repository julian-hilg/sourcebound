import { Select, copyText, defineTool, openContextMenu, useWerkbank } from "@werkbank/framework";
import { useState } from "react";
import { z } from "zod";
import { api, paths, useApi, type Connections, type DatabaseDriver, type DataSource, type McpServer } from "../data/api";
import { AUTH_LABEL, DRIVERS, blankDraft, checkDraft, toDraft, type Draft } from "../data/databases";
import { CommandLine, EmptyState, KeyValue, Section, SplitPane, StatusDot, StatusPill, type Tone } from "../kit";
import { prefs } from "../prefs";
import { ago, show, showTable, tone, usePanelState, when } from "./lib";

/**
 * Data connections: every registered source (API, download, database, manual files) with what
 * it needs and whether that is in place, and the MCP servers agents may use. The list-and-detail
 * pattern is the Werkbank starter's Connections panel.
 *
 * Database connections are made here as in the starter: a form, field by field, that writes the
 * same register entry as `sb datasource add --driver ...` (connection.save, with undo), a test
 * (connection.test) and a SQL console on it. A password is typed once per session and held only in
 * the memory of `sb ui`; it never enters a file, this panel's state or a command's input. Other
 * sources and MCP servers are registered on the command line, where their terms and documentation
 * are recorded.
 */

const stateSchema = z.object({
  selected: z.string().max(100).nullable(),
  /** The unsaved database form, as typed (never a password), so it survives a reload. */
  draft: z.record(z.string(), z.unknown()).nullable().default(null),
});
type State = z.infer<typeof stateSchema>;

/** One mark per source: stopped host (bad), a failed test (bad), something missing (warn), in use (good). */
const mark = (s: DataSource): { tone: Tone; label: string } =>
  s.stopped_hosts.length
    ? { tone: "bad", label: "a host is stopped" }
    : s.connection?.last_test?.status === "failed"
      ? { tone: "bad", label: "the last test failed" }
      : s.connection?.last_test?.status === "ok"
        ? { tone: "good", label: "connected" }
        : s.connection && !s.connection.ready
          ? { tone: "warn", label: s.connection.why }
          : s.needs_env.some((e) => !e.set)
            ? { tone: "warn", label: "an environment variable is not set" }
            : s.status === "active" || s.status === "approved"
              ? { tone: "good", label: s.status }
              : { tone: undefined, label: s.status || "candidate" };
const address = (m: McpServer) => m.url ?? [m.command, ...(m.args ?? [])].join(" ");
const DRIVER_OPTIONS = (Object.keys(DRIVERS) as DatabaseDriver[]).map((value) => ({ value, label: DRIVERS[value].title }));

/** Create or change a database connection, test it, open a console on it. */
function DatabaseForm({ source, state, setState }: { source: DataSource | null; state: State; setState: (s: State) => void }) {
  const wb = useWerkbank();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const conn = source?.connection ?? null;
  const isNew = source === null;
  const draft = (state.draft as Draft | null) ?? (conn ? toDraft(source!.id, source!.name || source!.id, conn.spec) : blankDraft());
  const dirty = state.draft !== null;
  const checked = checkDraft(draft, isNew);
  const errors = dirty && !checked.ok ? checked.errors : {};
  const d = DRIVERS[draft.driver];
  const auth = String(draft.auth || d.auth?.[0] || "none");
  const needsPassword = !d.file && auth === "sql";
  const edit = (patch: Partial<Draft>) => setState({ ...state, draft: { ...draft, ...patch } });
  const changeDriver = (driver: DatabaseDriver) => {
    const fresh = blankDraft(driver);
    edit({ driver, port: fresh.port, auth: DRIVERS[driver].auth?.includes(auth as never) ? auth : fresh.auth });
  };

  const act = async (label: string, work: () => Promise<unknown>) => {
    setBusy(label);
    setFailure(null);
    try {
      await work();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const save = async () => {
    if (!checked.ok) return false;
    await wb.run("connection.save", { id: draft.id, name: draft.name.trim(), spec: checked.spec });
    setState({ selected: `source:${draft.id}`, draft: null });
    return true;
  };
  const test = () =>
    act("test", async () => {
      if ((dirty || isNew) && !(await save())) return;
      // The password goes to the service directly, not through a command (whose input the history keeps).
      if (password) await api.post(paths.connections, { op: "secret", id: draft.id, password });
      setPassword("");
      await wb.run("connection.test", { id: draft.id });
    });

  const field = (name: string, label: string, input: React.ReactNode, hint?: string) => (
    <div className="wb-control" data-invalid={errors[name] ? true : undefined}>
      <label htmlFor={`db-${name}`}>{label}</label>
      {input}
      {errors[name] ? (
        <span className="wb-control-error" role="alert">
          {errors[name]}
        </span>
      ) : (
        hint && <span className="wb-control-label">{hint}</span>
      )}
    </div>
  );
  const text = (name: keyof Draft, extra: object = {}) => (
    <input id={`db-${name}`} className="wb-input" value={String(draft[name] ?? "")} aria-invalid={errors[name] ? true : undefined} spellCheck={false} autoComplete="off" onChange={(e) => edit({ [name]: e.target.value } as Partial<Draft>)} {...extra} />
  );
  const choice = (name: keyof Draft, label: string) => (
    <label className="wb-choice">
      <input type="checkbox" checked={Boolean(draft[name])} onChange={(e) => edit({ [name]: e.target.checked } as Partial<Draft>)} />
      {label}
    </label>
  );
  const test_ = conn?.last_test;

  return (
    <form className="wb-form sb-pad" noValidate onSubmit={(e) => (e.preventDefault(), void act("save", save))}>
      <div className="wb-form-actions">
        <strong>{isNew ? "New database connection" : source!.name || source!.id}</strong>
        <span className="wb-badge">{d.title}</span>
        {dirty && (
          <span className="wb-badge" data-tone="warn">
            unsaved changes
          </span>
        )}
        {!dirty && test_ && <StatusPill tone={test_.status === "ok" ? "good" : "bad"}>{test_.status === "ok" ? "connected" : "test failed"}</StatusPill>}
        {!dirty && conn && !test_ && <StatusPill tone={conn.ready ? undefined : "warn"}>not tested</StatusPill>}
      </div>
      {!dirty && test_ && (
        <p className={test_.status === "ok" ? "wb-hint" : "sb-notice"} data-tone={test_.status === "ok" ? undefined : "bad"} role="status">
          {test_.status === "ok" ? `Connected: ${test_.message}` : test_.message} <span className="wb-dim">({when(test_.at)})</span>
        </p>
      )}
      {conn?.problems && !dirty && (
        <p className="sb-notice" data-tone="warn">
          The register entry has problems ({Object.entries(conn.problems).map(([k, v]) => `${k}: ${v}`).join("; ")}). Correct them here and save.
        </p>
      )}
      {failure && (
        <p className="sb-notice" data-tone="bad" role="alert">
          {failure}
        </p>
      )}
      <div className="wb-form-row">
        {field("name", "Name", text("name"))}
        {isNew ? field("id", "Id", text("id", { placeholder: "warehouse" }), "The source id: in pipelines, sources.query(\"id\", …).") : field("id", "Id", <code id="db-id">{draft.id}</code>)}
      </div>
      {field("driver", "Database", <Select id="db-driver" value={draft.driver} options={DRIVER_OPTIONS} onChange={(v) => changeDriver(v as DatabaseDriver)} />)}
      {d.file ? (
        field("path", "Database file", text("path", { placeholder: draft.driver === "sqlite" ? "D:\\data\\shop.sqlite" : "D:\\data\\warehouse.duckdb" }), "Opened read-only on the machine that runs sb ui.")
      ) : (
        <>
          <div className="wb-form-row">
            {field("server", "Server", text("server", { placeholder: "sql-01.example.org" }))}
            {field("port", "Port", text("port", { inputMode: "numeric" }))}
          </div>
          {field("database", "Database name", text("database"))}
          <div className="wb-form-row">
            {field("auth", "Authentication", <Select id="db-auth" value={auth} options={(d.auth ?? []).map((a) => ({ value: a, label: AUTH_LABEL[a] }))} onChange={(v) => edit({ auth: v })} />)}
            {auth === "sql" && field("user", "User", text("user"))}
          </div>
          {auth === "windows" && <p className="wb-hint">Connects as the Windows user who runs sb ui; no password is needed.</p>}
          {auth === "sql" &&
            field("password_env", "Password from an environment variable (optional)", text("password_env", { placeholder: "WAREHOUSE_PASSWORD" }), "For pipelines and jobs: the NAME of the variable, never the password.")}
          {draft.driver === "mssql" && (
            <div className="wb-form-row">
              {choice("encrypt", "Encrypt the connection")}
              {choice("trust_server_certificate", "Trust server certificate")}
            </div>
          )}
          {draft.driver === "postgresql" &&
            field("ssl_mode", "SSL", <Select id="db-ssl_mode" value={String(draft.ssl_mode)} options={["disable", "prefer", "require", "verify-full"].map((v) => ({ value: v, label: v }))} onChange={(v) => edit({ ssl_mode: v })} />)}
        </>
      )}
      {needsPassword && (
        <div className="wb-control">
          <label htmlFor="db-password">Password</label>
          <input
            id="db-password"
            className="wb-input"
            type="password"
            autoComplete="off"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={conn?.password_in_session ? "entered for this session" : draft.password_env ? `else from ${draft.password_env}` : ""}
          />
          <span className="wb-control-label">Held in the memory of sb ui for this session only. It is never written to the register entry, a workspace or a log.</span>
        </div>
      )}
      {field("timeout", "Timeout of a test (seconds)", text("timeout", { inputMode: "numeric" }))}
      <div className="wb-form-actions">
        <button className="wb-button" type="submit" disabled={!dirty || !checked.ok || busy !== null}>
          {busy === "save" ? "Saving…" : "Save"}
        </button>
        <button className="wb-button" type="button" disabled={busy !== null || (dirty && !checked.ok)} onClick={() => void test()}>
          {busy === "test" ? "Testing…" : dirty || isNew ? "Save and test" : "Test connection"}
        </button>
        {dirty && (
          <button className="wb-button" type="button" onClick={() => setState({ selected: isNew ? null : state.selected, draft: null })}>
            Discard changes
          </button>
        )}
        <span className="kit-grow" />
        {conn?.password_in_session && (
          <button className="wb-button" type="button" onClick={() => void act("forget", () => wb.run("connection.forget", { id: draft.id }))}>
            Forget password
          </button>
        )}
        {!isNew && conn && (
          <button className="wb-button" type="button" disabled={busy !== null} onClick={() => void act("remove", async () => (await wb.run("connection.remove", { id: draft.id }), setState({ selected: null, draft: null })))}>
            Remove
          </button>
        )}
      </div>
      {!dirty && conn?.ready && test_?.status === "ok" && (
        <p>
          <button className="wb-button" type="button" onClick={() => void show(wb, "sql", { patch: { target: source!.id, sql: "SELECT 1" } })}>
            Open a SQL console on it
          </button>
        </p>
      )}
      {!isNew && <CommandLine command={`sb datasource test ${draft.id}`} note="the same test from a terminal (asks for the password)" />}
    </form>
  );
}

function ConnectionsPanel() {
  const wb = useWerkbank();
  const [state, setState] = usePanelState<State>();
  const entry = useApi<Connections>(paths.connections, prefs.every.system);
  const c = entry.data;
  if (!c) return <EmptyState>{entry.error ?? "Loading…"}</EmptyState>;
  const source = c.sources.find((s) => `source:${s.id}` === state.selected);
  const server = c.mcp_servers.find((m) => `mcp:${m.name}` === state.selected);
  const adding = state.selected === "new-database";
  const pick = (selected: string | null) => setState({ selected, draft: null });
  const list = (
    <nav aria-label="Connections">
      <div className="sb-pad">
        <Select
          aria-label="New database connection"
          placeholder="New database connection…"
          value=""
          options={DRIVER_OPTIONS}
          onChange={(driver) => setState({ selected: "new-database", draft: blankDraft(driver as DatabaseDriver) as unknown as Record<string, unknown> })}
        />
      </div>
      <div className="sb-list-heading">Data sources ({c.sources.length})</div>
      {c.sources.map((s) => (
        <button
          key={s.id}
          className="wb-list-item sb-list-row"
          aria-current={`source:${s.id}` === state.selected || undefined}
          onClick={() => pick(`source:${s.id}`)}
          onContextMenu={(e) =>
            openContextMenu(wb, e, [
              s.connection && { label: "Test connection", run: () => void wb.run("connection.test", { id: s.id }) },
              s.database && { label: "Open a SQL console on it", run: () => void show(wb, "sql", { patch: { target: s.id, sql: "SELECT 1" } }) },
              { label: "Show its requests in the fetch log", run: () => void show(wb, "sources", { patch: { tab: "fetchlog", fetchlog: { source: s.id, outcome: "all", query: "" } } }) },
              { label: "Copy id", run: () => copyText(s.id) },
              s.url ? { label: "Copy address", run: () => copyText(s.url) } : null,
            ])
          }
        >
          <StatusDot {...mark(s)} />
          <span className="sb-list-name" title={s.name}>
            {s.name || s.id}
          </span>
          <span className="wb-dim">{s.connection ? DRIVERS[s.connection.spec.driver]?.title ?? s.access : s.access}</span>
        </button>
      ))}
      {c.sources.length === 0 && <p className="wb-hint sb-pad">No source registered yet.</p>}
      <div className="sb-list-heading">MCP servers ({c.mcp_servers.length})</div>
      {c.mcp_servers.map((m) => (
        <button key={m.name} className="wb-list-item sb-list-row" aria-current={`mcp:${m.name}` === state.selected || undefined} onClick={() => pick(`mcp:${m.name}`)}>
          <StatusDot tone={m.env.some((e) => !e.set) ? "warn" : "good"} label={m.env.some((e) => !e.set) ? "an environment variable is not set" : "registered"} />
          <span className="sb-list-name">{m.name}</span>
          <span className="wb-dim">{m.transport}</span>
        </button>
      ))}
      {c.mcp_servers.length === 0 && <p className="wb-hint sb-pad">None registered.</p>}
    </nav>
  );
  const env = (needs: { name: string; set: boolean }[]) =>
    needs.length === 0
      ? "none"
      : needs.map((e) => (
          <span key={e.name} className="sb-inline">
            <code>{e.name}</code> <StatusPill tone={e.set ? "good" : "warn"}>{e.set ? "set" : "not set"}</StatusPill>
          </span>
        ));
  const detail = adding ? (
    <DatabaseForm key="new" source={null} state={state} setState={setState} />
  ) : source?.connection ? (
    <DatabaseForm key={source.id} source={source} state={state} setState={setState} />
  ) : source ? (
    <div className="sb-pad">
      <p>
        <strong>{source.name || source.id}</strong> <code>{source.id}</code> <StatusPill tone={tone(source.status)}>{source.status || "candidate"}</StatusPill>
      </p>
      {source.stopped_hosts.map((host) => (
        <p key={host} className="sb-notice" data-tone="bad">
          <strong>{host}</strong> is stopped: it refused a request. Nothing is fetched from it until you have looked and cleared the stop in a terminal:{" "}
          <code>sb unblock {source.id} {host}</code>
        </p>
      ))}
      {source.needs_env.some((e) => !e.set) && (
        <p className="sb-notice" data-tone="warn">
          Set the missing environment variable in the shell that starts <code>sb ui</code> and the pipelines. The value never goes into a file.
        </p>
      )}
      <KeyValue
        items={[
          { label: "Access", value: `${source.access}${source.database ? " (database, read through sources.query)" : ""}` },
          { label: "Publisher", value: source.publisher || "–" },
          { label: "Address", value: source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.url}</a> : "–" },
          { label: "Needs", value: env(source.needs_env) },
          { label: "Tables", value: source.tables.length ? source.tables.map((t) => <button key={t} className="sb-ref" onClick={() => void showTable(wb, t)}>{t}</button>) : "none yet" },
          { label: "Licence", value: source.license || "not recorded" },
          source.terms ? { label: "Terms", value: /^https?:/.test(source.terms) ? <a href={source.terms} target="_blank" rel="noreferrer">{source.terms}</a> : source.terms } : null,
          { label: "Updates", value: source.frequency || "–" },
          { label: "Documentation", value: `${source.docs} archived documents` },
          source.mcp ? { label: "Provider's MCP", value: source.mcp } : null,
          { label: "Last request", value: source.last_request ? `${ago(source.last_request.ts)} (${source.last_request.status})` : "none yet" },
          { label: "Entry checked", value: source.checked || "–" },
        ]}
      />
      {source.database && (
        <p>
          <button className="wb-button" onClick={() => void show(wb, "sql", { patch: { target: source.id, sql: "SELECT 1" } })}>
            Open a SQL console on it
          </button>
        </p>
      )}
    </div>
  ) : server ? (
    <div className="sb-pad">
      <p>
        <strong>{server.name}</strong> <span className="wb-dim">MCP server, {server.transport}</span>
      </p>
      <KeyValue
        items={[
          { label: server.transport === "http" ? "Address" : "Command", value: <code>{address(server)}</code> },
          { label: "Needs", value: env(server.env) },
          server.source ? { label: "Data source", value: server.source } : null,
          server.note ? { label: "Note", value: server.note } : null,
        ]}
      />
      <p className="wb-hint">A project uses a registered server once it is linked into its .mcp.json; Claude Code asks once before it uses a server from that file.</p>
      <CommandLine command={`sb mcp link ${server.name}`} note="run inside the project" />
    </div>
  ) : (
    <div className="sb-pad">
      <Section title="Adding a connection">
        <p className="wb-hint">
          A database connection is made here: choose “New database connection…” above (SQL Server, PostgreSQL, MySQL, or a SQLite or DuckDB file). Other sources are registered on the command line: the entry records terms, licence and legal
          notes, and the provider's documentation is archived with it.
        </p>
        <CommandLine command={'sb datasource add ID --name "…" --url URL --access api'} note="an API or download" />
        <CommandLine command={'sb datasource add ID --name "…" --driver mssql --server HOST --database DB --auth windows'} note="the same database connection from a terminal" />
        <CommandLine command="sb datasource docs ID FILE|URL" note="archive its documentation" />
        <CommandLine command="sb mcp add NAME --url URL" note="an MCP server agents may use" />
        <CommandLine command={'sb mcp add NAME --command "program args" --env TOKEN_VAR'} note="a local MCP server; --env names a variable, never a value" />
      </Section>
      <p className="wb-hint">
        The fetcher sends one request per host every {c.seconds_between_requests} seconds, respects robots.txt and stops a host that refuses. A stop is cleared only by you, in a terminal.
      </p>
    </div>
  );
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Connections</strong>
        <span>
          {c.sources.length} sources, {c.sql_targets.length} SQL targets, {c.mcp_servers.length} MCP servers
        </span>
        <span className="kit-grow" />
        {(source || server || adding) && (
          <button className="wb-button" onClick={() => pick(null)}>
            How to add one
          </button>
        )}
      </div>
      <SplitPane list={list} detail={detail} listWidth={280} label="Connection" />
    </div>
  );
}

export const connectionsTool = defineTool<State>({
  id: "connections",
  title: "Connections",
  glyph: "⇄",
  category: "Data",
  version: 1,
  stateSchema,
  defaultState: () => ({ selected: null, draft: null }),
  component: ConnectionsPanel,
  describe: (state) => {
    const c = api.peek<Connections>(paths.connections);
    if (!c) return { loaded: false };
    return {
      selected: state.selected,
      draft: state.draft,
      note:
        "Environment variables are listed by name and whether they are set; values are never shown. A stopped host is cleared only by the person (sb unblock). " +
        "Database connections: connection.save (field by field, with undo), connection.test, then sql.query with the source id as target. A password is typed by the person in this panel and held only in the memory of sb ui; agents never handle it. " +
        "Other sources and MCP servers are registered on the command line.",
      seconds_between_requests_per_host: c.seconds_between_requests,
      sources: c.sources,
      sql_targets: c.sql_targets,
      mcp_servers: c.mcp_servers,
    };
  },
});
