import { copyText, defineTool, openContextMenu, useToolState, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type Connections, type DataSource, type McpServer } from "../data/api";
import { CommandLine, EmptyState, KeyValue, Section, SplitPane, StatusDot, StatusPill, type Tone } from "../kit";
import { prefs } from "../prefs";
import { ago, showTable, tone } from "./lib";

/**
 * Data connections: every registered source (API, download, database, manual files) with what
 * it needs and whether that is in place, and the MCP servers agents may use. The list-and-detail
 * pattern is the Werkbank starter's Connections panel. Registering a source or a server is done
 * on the command line, where the register entry and its archived documentation are written.
 */

const stateSchema = z.object({ selected: z.string().max(100).nullable() });
type State = z.infer<typeof stateSchema>;

/** One mark per source: stopped host (bad), something missing (warn), in use (good). */
const mark = (s: DataSource): { tone: Tone; label: string } =>
  s.stopped_hosts.length
    ? { tone: "bad", label: "a host is stopped" }
    : s.needs_env.some((e) => !e.set)
      ? { tone: "warn", label: "an environment variable is not set" }
      : s.status === "active" || s.status === "approved"
        ? { tone: "good", label: s.status }
        : { tone: undefined, label: s.status || "candidate" };
const address = (m: McpServer) => m.url ?? [m.command, ...(m.args ?? [])].join(" ");

function ConnectionsPanel() {
  const wb = useWerkbank();
  const [state, setState] = useToolState<State>();
  const entry = useApi<Connections>(paths.connections, prefs.every.system);
  const c = entry.data;
  if (!c) return <EmptyState>{entry.error ?? "Loading…"}</EmptyState>;
  const source = c.sources.find((s) => `source:${s.id}` === state.selected);
  const server = c.mcp_servers.find((m) => `mcp:${m.name}` === state.selected);
  const list = (
    <nav aria-label="Connections">
      <div className="sb-list-heading">Data sources ({c.sources.length})</div>
      {c.sources.map((s) => (
        <button
          key={s.id}
          className="wb-list-item sb-list-row"
          aria-current={`source:${s.id}` === state.selected || undefined}
          onClick={() => setState({ selected: `source:${s.id}` })}
          onContextMenu={(e) =>
            openContextMenu(wb, e, [
              s.database && { label: "Open a SQL console on it", run: () => void wb.run("panel.open", { toolId: "sql", state: { target: s.id, sql: "SELECT 1", history: [] } }) },
              { label: "Show its requests in the fetch log", run: () => void wb.run("panel.open", { toolId: "fetchlog", state: { source: s.id, outcome: "all", query: "" } }) },
              { label: "Copy id", run: () => copyText(s.id) },
              s.url ? { label: "Copy address", run: () => copyText(s.url) } : null,
            ])
          }
        >
          <StatusDot {...mark(s)} />
          <span className="sb-list-name" title={s.name}>
            {s.name || s.id}
          </span>
          <span className="wb-dim">{s.access}</span>
        </button>
      ))}
      {c.sources.length === 0 && <p className="wb-hint sb-pad">No source registered yet.</p>}
      <div className="sb-list-heading">MCP servers ({c.mcp_servers.length})</div>
      {c.mcp_servers.map((m) => (
        <button key={m.name} className="wb-list-item sb-list-row" aria-current={`mcp:${m.name}` === state.selected || undefined} onClick={() => setState({ selected: `mcp:${m.name}` })}>
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
  const detail = source ? (
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
          <button className="wb-button" onClick={() => void wb.run("panel.open", { toolId: "sql", state: { target: source.id, sql: "SELECT 1", history: [] } })}>
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
        <p className="wb-hint">Connections are registered on the command line: the entry records terms, licence and legal notes, and the provider's documentation is archived with it.</p>
        <CommandLine command={'sb datasource add ID --name "…" --url URL --access api'} note="an API or download" />
        <CommandLine command={'sb datasource add ID --name "…" --access database --connection-env DB_URI'} note="a database, read-only through its URI in an environment variable" />
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
        {(source || server) && (
          <button className="wb-button" onClick={() => setState({ selected: null })}>
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
  defaultState: () => ({ selected: null }),
  component: ConnectionsPanel,
  describe: (state) => {
    const c = api.peek<Connections>(paths.connections);
    if (!c) return { loaded: false };
    return {
      selected: state.selected,
      note: "Environment variables are listed by name and whether they are set; values are never shown. A stopped host is cleared only by the person (sb unblock). Sources and MCP servers are registered on the command line.",
      seconds_between_requests_per_host: c.seconds_between_requests,
      sources: c.sources,
      sql_targets: c.sql_targets,
      mcp_servers: c.mcp_servers,
    };
  },
});
