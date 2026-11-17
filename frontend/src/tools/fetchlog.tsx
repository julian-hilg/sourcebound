import { Select, copyText, defineTool, openContextMenu, useSetting, useToolState, useWerkbank } from "@werkbank/framework";
import { prefs } from "../prefs";
import { z } from "zod";
import { api, paths, useApi, type FetchLog } from "../data/api";
import { Blank, matches, when } from "./lib";

const stateSchema = z.object({ source: z.string().max(80), outcome: z.enum(["all", "stored", "refused"]), query: z.string().max(120) });
type State = z.infer<typeof stateSchema>;

/** A request that stored a response has a numeric status below 400; everything else was refused or failed. */
const stored = (status: number | string) => typeof status === "number" && status < 400;

const select = (log: FetchLog, state: State) =>
  log.sources
    .filter((s) => state.source === "all" || s.source === state.source)
    .flatMap((s) => s.entries.map((e) => ({ ...e, source: s.source })))
    .filter((e) => (state.outcome === "all" || (state.outcome === "stored") === stored(e.status)) && matches(state.query, e.url, String(e.status)))
    .sort((a, b) => b.ts.localeCompare(a.ts));

function FetchLogPanel() {
  const wb = useWerkbank();
  const [state, setState] = useToolState<State>();
  const log = useApi<FetchLog>(paths.fetch, prefs.every.jobs);
  const [maxRows] = useSetting<number>("fetchlog.maxRows");
  if (!log.data) return <Blank>{log.error ?? "Loading…"}</Blank>;
  const matching = select(log.data, state);
  const rows = matching.slice(0, maxRows);
  const stops = log.data.sources.flatMap((s) => s.stopped.map((b) => ({ ...b, source: s.source })));
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <Select
          value={state.source}
          aria-label="Source"
          options={[{ value: "all", label: "All sources" }, ...log.data.sources.map((s) => ({ value: s.source, label: s.source, hint: `${s.requests} requests` }))]}
          onChange={(source) => setState({ ...state, source })}
        />
        <span className="wb-segment" role="group" aria-label="Outcome">
          {(["all", "stored", "refused"] as const).map((outcome) => (
            <button key={outcome} className="wb-button" aria-pressed={state.outcome === outcome} onClick={() => setState({ ...state, outcome })}>
              {outcome === "all" ? "All" : outcome === "stored" ? "Stored" : "Refused or failed"}
            </button>
          ))}
        </span>
        <input className="wb-input sb-search" type="search" value={state.query} placeholder="Search addresses" aria-label="Search addresses" onChange={(e) => setState({ ...state, query: e.target.value })} />
        <span>
          {rows.length}
          {matching.length > rows.length ? ` of ${matching.length}` : ""} requests
        </span>
      </div>
      {stops.map((b) => (
        <p key={`${b.source}/${b.host}`} className="sb-notice" data-tone="bad">
          <strong>{b.host}</strong> is stopped for source {b.source} since {when(b.since)}: {b.reason.replace(/^\d{4}-\d{2}-\d{2}T\S+\s+/, "") || "no reason recorded"}. Nothing is fetched from it until you
          clear the stop in a terminal: <code>sb unblock {b.source} {b.host}</code>
        </p>
      ))}
      <div className="sb-scroll">
        <table className="wb-table sb-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Outcome</th>
              <th>Address</th>
              <th>Archived as</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e, i) => (
              <tr key={`${e.ts}${e.url}${i}`} onContextMenu={(ev) => openContextMenu(wb, ev, [{ label: "Copy address", run: () => copyText(e.url) }, e.sha256 ? { label: "Copy SHA-256", run: () => copyText(e.sha256!) } : null])}>
                <td className="wb-num">{when(e.ts)}</td>
                <td>{e.source}</td>
                <td>
                  <span className="sb-status" data-tone={stored(e.status) ? "good" : "bad"}>
                    {String(e.status).replace("refused:robots", "refused by robots.txt").replace("refused:stopped", "host is stopped")}
                  </span>
                </td>
                <td className="sb-wrap sb-url">{e.url}</td>
                <td>{e.sha256 ? <code title={e.path ?? ""}>{e.sha256.slice(0, 12)}</code> : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Blank>{log.data.sources.length ? "No request matches." : `No request has been archived under ${log.data.raw_root} yet.`}</Blank>}
      </div>
    </div>
  );
}

export const fetchLogTool = defineTool<State>({
  id: "fetchlog",
  title: "Fetch log",
  glyph: "⇣",
  category: "Data",
  version: 1,
  stateSchema,
  defaultState: () => ({ source: "all", outcome: prefs.fetchOutcome, query: "" }),
  component: FetchLogPanel,
  describe: (state) => {
    const log = api.peek<FetchLog>(paths.fetch);
    if (!log) return { loaded: false };
    const rows = select(log, state);
    return {
      raw_archive: log.raw_root, seconds_between_requests_per_host: log.min_interval_s, filter: state,
      stopped_hosts: log.sources.flatMap((s) => s.stopped.map((b) => ({ source: s.source, ...b }))),
      note: "A stopped host is cleared only by the person, in a terminal (sb unblock). Never retry it.",
      sources: log.sources.map((s) => ({ source: s.source, requests: s.requests })),
      shown: rows.length,
      requests: rows.slice(0, prefs.rowCap),
    };
  },
});
