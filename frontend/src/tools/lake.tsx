import { copyText, defineTool, openContextMenu, useLink, useSetting, useToolState, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type Lake, type LakeTable, type QueryResult } from "../data/api";
import { DataGrid, EmptyState, KeyValue, SplitPane, StatusDot, StatusPill, toCsv } from "../kit";
import { prefs } from "../prefs";
import { downloadText, matches, num, when } from "./lib";

/**
 * The data lake: every table with its contract, columns, a preview of its rows and the
 * snapshots of the catalog. Reading only; tables are written by pipelines.
 */

const stateSchema = z.object({ view: z.enum(["columns", "rows", "snapshots"]), query: z.string().max(80) });
type State = z.infer<typeof stateSchema>;

const selectFrom = (t: LakeTable) => `SELECT *\nFROM ${t.name}\nLIMIT 100`;
const pick = (lake: Lake | undefined, name: unknown) => lake?.tables.find((t) => t.name === name) ?? lake?.tables[0];

function LakePanel() {
  const wb = useWerkbank();
  const [state, setState] = useToolState<State>();
  const [linked, setTable] = useLink<string | null>("table");
  const [limit] = useSetting<string>("tables.previewRows");
  const [nullText] = useSetting<string>("tables.nullText");
  const [density] = useSetting<string>("tables.density");
  const entry = useApi<Lake>(paths.lake, prefs.every.system);
  const lake = entry.data;
  const table = pick(lake, linked);
  const rows = useApi<QueryResult>(table && state.view === "rows" ? paths.lakeTable(table.name, Number(limit)) : null, prefs.every.system);
  if (!lake) return <EmptyState>{entry.error ?? "Opening the catalog…"}</EmptyState>;
  const shown = lake.tables.filter((t) => matches(state.query, t.name, t.contract?.title, t.comment));
  const schemas = [...new Set(shown.map((t) => t.schema))];
  const openSql = (t: LakeTable) => void wb.run("panel.open", { toolId: "sql", state: { target: "lake", sql: selectFrom(t), history: [] } });
  const list = (
    <nav aria-label="Tables">
      {schemas.map((schema) => (
        <div key={schema}>
          <div className="sb-list-heading">{schema}</div>
          {shown
            .filter((t) => t.schema === schema)
            .map((t) => (
              <button
                key={t.name}
                className="wb-list-item sb-list-row"
                aria-current={t.name === table?.name || undefined}
                onClick={() => setTable(t.name)}
                onDoubleClick={() => openSql(t)}
                onContextMenu={(e) =>
                  openContextMenu(wb, e, [
                    { label: "Open in a SQL console", run: () => openSql(t) },
                    { label: "Copy table name", run: () => copyText(t.name) },
                    { label: "Copy SELECT", run: () => copyText(selectFrom(t)) },
                    { label: "Copy lake.read(…)", run: () => copyText(`lake.read("${t.name}")`) },
                  ])
                }
              >
                <StatusDot tone={t.contract ? (t.restricted ? "warn" : "good") : undefined} label={t.contract ? (t.restricted ? "restricted licence" : "has a contract") : "no contract"} />
                <span className="sb-list-name">{t.table}</span>
                <span className="wb-dim wb-num">{num(t.rows)}</span>
              </button>
            ))}
        </div>
      ))}
      {shown.length === 0 && <p className="wb-hint sb-pad">{lake.tables.length ? "No table matches." : "The lake has no table yet. A pipeline writes the first one."}</p>}
    </nav>
  );
  const detail = !table ? null : (
    <div className="sb-panel">
      <div className="sb-pad sb-detail-head">
        <p>
          <strong>{table.name}</strong> <span className="wb-dim">{num(table.rows)} rows (estimate)</span>{" "}
          {table.restricted && (
            <StatusPill tone="warn" outlined title="Its licence starts with restricted or proprietary: sb publish leaves it out">
              restricted
            </StatusPill>
          )}{" "}
          {!table.contract && <StatusPill tone="warn">no contract</StatusPill>}
        </p>
        <p>{table.contract?.title || table.comment}</p>
        <span className="wb-segment" role="group" aria-label="View">
          {(["columns", "rows", "snapshots"] as const).map((view) => (
            <button key={view} className="wb-button" aria-pressed={state.view === view} onClick={() => setState({ ...state, view })}>
              {view === "columns" ? `Columns (${table.columns.length})` : view === "rows" ? "Rows" : "Snapshots"}
            </button>
          ))}
        </span>{" "}
        <button className="wb-button" onClick={() => openSql(table)}>
          Open in SQL console
        </button>
        {state.view === "rows" && rows.data && (
          <>
            {" "}
            <button className="wb-button" onClick={() => downloadText(`${table.name}.csv`, toCsv(rows.data!.columns, rows.data!.rows), "text/csv")}>
              CSV
            </button>{" "}
            <span className="wb-dim">
              {num(rows.data.rows.length)} of {num(rows.data.row_count)} rows
            </span>
          </>
        )}
      </div>
      {state.view === "rows" ? (
        rows.data ? (
          <DataGrid
            columns={rows.data.columns.map((key, i) => ({ key, type: rows.data!.types[i] }))}
            rows={rows.data.rows}
            locale={prefs.locale}
            nullText={nullText}
            rowHeight={density === "comfortable" ? 28 : 22}
            label={`Rows of ${table.name}`}
            onRowMenu={(e, cell) =>
              openContextMenu(wb, e, [
                { label: "Copy value", run: () => copyText(String(cell.value ?? "")) },
                { label: "Copy row as JSON", run: () => copyText(JSON.stringify(Object.fromEntries(rows.data!.columns.map((c, i) => [c, cell.row[i]])))) },
                { label: "Copy row as tab-separated", run: () => copyText(cell.row.join("\t")) },
              ])
            }
          />
        ) : (
          <EmptyState>{rows.error ?? "Reading rows…"}</EmptyState>
        )
      ) : state.view === "columns" ? (
        <div className="sb-scroll">
          {table.contract && (
            <div className="sb-pad">
              <KeyValue
                items={[
                  { label: "Grain", value: table.contract.grain || "–" },
                  { label: "Primary key", value: table.contract.primary_key.join(", ") || "–" },
                  { label: "Sources", value: table.contract.sources.join(", ") || "–" },
                  { label: "Pipeline", value: table.contract.pipeline || "–" },
                  { label: "Licence", value: table.contract.license || "none stated: the table cannot be published" },
                  { label: "Owner", value: table.contract.owner },
                  table.contract.description ? { label: "About", value: table.contract.description } : null,
                ]}
              />
            </div>
          )}
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Unit</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((c) => (
                <tr key={c.name} onContextMenu={(e) => openContextMenu(wb, e, [{ label: "Copy column name", run: () => copyText(c.name) }])}>
                  <td>
                    <code>{c.name}</code>
                    {table.contract?.primary_key.includes(c.name) && <span className="wb-dim"> key</span>}
                  </td>
                  <td>{c.type}</td>
                  <td>{c.unit || "–"}</td>
                  <td className="sb-wrap">{c.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="sb-scroll">
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>Snapshot</th>
                <th>When</th>
                <th>What</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {lake.snapshots.map((s) => (
                <tr key={s.id} title={s.changes}>
                  <td className="wb-num">{s.id}</td>
                  <td>{when(s.at.replace(" ", "T").replace(/([+-]\d\d)$/, "$1:00"))}</td>
                  <td className="sb-wrap">{s.message || <span className="wb-dim">{s.changes}</span>}</td>
                  <td>{s.author}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="wb-hint sb-pad">Snapshots are versions of the whole catalog, newest first. A result records the snapshot of every table it read.</p>
        </div>
      )}
    </div>
  );
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Lake</strong>
        <input className="wb-input sb-search" type="search" value={state.query} placeholder="Filter tables" aria-label="Filter tables" onChange={(e) => setState({ ...state, query: e.target.value })} />
        <span>
          {lake.tables.length} tables · snapshot {lake.snapshots[0]?.id ?? "–"}
        </span>
        <span className="kit-grow" />
        <span className="wb-dim sb-url" title={lake.data_path}>
          {lake.catalog.split(":")[0]}
        </span>
      </div>
      <SplitPane list={list} detail={detail} listWidth={230} label={table ? `Table ${table.name}` : undefined} />
    </div>
  );
}

export const lakeTool = defineTool<State>({
  id: "lake",
  title: "Lake",
  glyph: "≋",
  category: "Data",
  version: 1,
  stateSchema,
  defaultState: () => ({ view: "columns", query: "" }),
  links: ["table"],
  component: LakePanel,
  describe: (state, { links }) => {
    const lake = api.peek<Lake>(paths.lake);
    if (!lake) return { loaded: false };
    const table = pick(lake, links.table);
    return {
      note: "Select a table with link.publish { topic: 'table', value: '<schema>.<table>' }; read rows with sql.query { target: 'lake', sql }.",
      catalog: lake.catalog,
      selected: table?.name ?? null,
      view: state.view,
      tables: lake.tables.map((t) => ({ name: t.name, rows_estimate: t.rows, title: t.contract?.title ?? t.comment, restricted: t.restricted, has_contract: Boolean(t.contract), sources: t.contract?.sources })),
      selected_table: table ? { ...table.contract, columns: table.columns } : null,
      snapshots: lake.snapshots.slice(0, 15),
    };
  },
});
