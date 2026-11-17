import { Select, copyText, defineTool, openContextMenu, useSetting, useToolState, useWerkbank } from "@werkbank/framework";
import { useState } from "react";
import { z } from "zod";
import { api, paths, useApi, type Connections, type Lake, type QueryResult } from "../data/api";
import { DataGrid, toCsv } from "../kit";
import { prefs } from "../prefs";
import { downloadText, num } from "./lib";

/**
 * A read-only SQL console on the data lake and on registered database sources. The pattern is
 * the Werkbank starter's console; here the server is real. The service refuses every statement
 * that does not only read, so nothing typed here can change data.
 */

const stateSchema = z.object({
  target: z.string().max(80),
  sql: z.string().max(8000),
  history: z.array(z.string().max(8000)).max(40),
});
type State = z.infer<typeof stateSchema>;

const START = "SELECT schema_name, table_name, estimated_size AS rows\nFROM duckdb_tables()\nWHERE database_name = 'lake'\nORDER BY 1, 2";

function SqlConsole() {
  const wb = useWerkbank();
  const [state, setState] = useToolState<State>();
  const [keep] = useSetting<number>("sql.historyLength");
  const [limit] = useSetting<string>("sql.rowLimit");
  const [wrap] = useSetting<boolean>("sql.wrapEditor");
  const [nullText] = useSetting<string>("tables.nullText");
  const [density] = useSetting<string>("tables.density");
  const connections = useApi<Connections>(paths.connections, prefs.every.system);
  const lake = useApi<Lake>(state.target === "lake" ? paths.lake : null, prefs.every.system);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const targets = connections.data?.sql_targets ?? [{ id: "lake", title: "Data lake", ready: true, hint: "" }];
  const target = targets.find((t) => t.id === state.target) ?? targets[0]!;

  const run = async (sql = state.sql) => {
    if (!sql.trim()) return setError("Type a statement first.");
    setBusy(true);
    const outcome = await wb.run("sql.query", { target: target.id, sql });
    setBusy(false);
    if (!outcome.ok) return (setResult(null), setError(outcome.error));
    setError(null);
    setResult(outcome.value as QueryResult);
    setState({ ...state, sql, history: [sql, ...state.history.filter((h) => h !== sql)].slice(0, keep) });
  };
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <Select aria-label="Target" value={target.id} options={targets.map((t) => ({ value: t.id, label: t.title, hint: t.ready ? undefined : "not ready" }))} onChange={(id) => setState({ ...state, target: id })} />
        <span className="wb-badge" title="The service runs one statement that reads (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN) and refuses everything else.">
          read-only
        </span>
        {!target.ready && <span className="wb-warn">{target.hint}</span>}
        <span className="kit-grow" />
        <Select
          aria-label="History"
          placeholder={state.history.length ? "History" : "No history yet"}
          searchable
          value=""
          options={state.history.map((q) => ({ value: q, label: q.replace(/\s+/g, " ").slice(0, 80) }))}
          onChange={(sql) => setState({ ...state, sql })}
        />
        <button className="wb-button" disabled={busy} onClick={() => void run()} title="Ctrl/⌘ Enter">
          {busy ? "Running…" : "Run"}
        </button>
        {result && (
          <button className="wb-button" onClick={() => downloadText("query.csv", toCsv(result.columns, result.rows), "text/csv")}>
            CSV
          </button>
        )}
      </div>
      <div className="sb-sql-top">
        <textarea
          className="sb-sql-editor"
          spellCheck={false}
          aria-label="SQL"
          wrap={wrap ? "soft" : "off"}
          value={state.sql}
          onChange={(e) => setState({ ...state, sql: e.target.value })}
          onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && (e.preventDefault(), void run())}
        />
        {state.target === "lake" && lake.data && (
          <nav className="sb-sql-schema" aria-label="Tables">
            {lake.data.tables.map((t) => (
              <details key={t.name}>
                <summary onDoubleClick={() => setState({ ...state, sql: `SELECT *\nFROM ${t.name}\nLIMIT 100` })} title="Double-click to select from it">
                  {t.name}
                </summary>
                <ul>
                  {t.columns.map((c) => (
                    <li key={c.name} title={c.description}>
                      {c.name} <span className="wb-dim">{c.type.toLowerCase()}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </nav>
        )}
      </div>
      <div className="sb-readout" role="status">
        {error ? (
          <span className="wb-warn">{error}</span>
        ) : result ? (
          `${num(result.row_count)} row${result.row_count === 1 ? "" : "s"} in ${result.seconds} s${result.truncated ? `, first ${num(result.rows.length)} shown (row limit ${limit})` : ""}`
        ) : (
          "Ctrl/⌘ Enter runs the statement. Double-click a table to select from it. Tables are <schema>.<table>."
        )}
      </div>
      <div className="sb-sql-result">
        {result && (
          <DataGrid
            columns={result.columns.map((key, i) => ({ key, type: result.types[i] }))}
            rows={result.rows}
            locale={prefs.locale}
            nullText={nullText}
            rowHeight={density === "comfortable" ? 28 : 22}
            label="Query result"
            empty="The statement returned no rows."
            onRowMenu={(e, cell) =>
              openContextMenu(wb, e, [
                { label: "Copy value", run: () => copyText(String(cell.value ?? "")) },
                { label: "Copy row as JSON", run: () => copyText(JSON.stringify(Object.fromEntries(result.columns.map((c, i) => [c, cell.row[i]])))) },
                { label: "Copy row as tab-separated", run: () => copyText(cell.row.join("\t")) },
              ])
            }
          />
        )}
      </div>
    </div>
  );
}

export const sqlTool = defineTool<State>({
  id: "sql",
  title: "SQL console",
  glyph: "⌗",
  category: "Data",
  version: 1,
  stateSchema,
  defaultState: () => ({ target: "lake", sql: START, history: [] }),
  component: SqlConsole,
  describe: (state) => ({
    target: state.target,
    sql: state.sql,
    history: state.history.slice(0, 5),
    note: "A read-only console. Run statements with sql.query { target, sql }; the result of a statement the person ran is on their screen only.",
    targets: api.peek<Connections>(paths.connections)?.sql_targets,
    lake_tables: api.peek<Lake>(paths.lake)?.tables.map((t) => ({ name: t.name, columns: t.columns.map((c) => `${c.name} ${c.type}`) })),
  }),
});
