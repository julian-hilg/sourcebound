import { Select, copyText, defineTool, openContextMenu, useLink, useToolState, useWerkbank } from "@werkbank/framework";
import { useEffect, useRef } from "react";
import { z } from "zod";
import { api, paths, type Detail, type Result } from "../data/api";
import { prefs } from "../prefs";
import { Blank, downloadCsv, matches, projectOf, useDetail, when } from "./lib";

const stateSchema = z.object({ query: z.string().max(120), hypothesis: z.string().max(40) });
type State = z.infer<typeof stateSchema>;

const select = (results: Result[], state: State) =>
  results.filter(
    (r) =>
      (state.hypothesis === "all" || (state.hypothesis === "none" ? !r.hypothesis : r.hypothesis === state.hypothesis)) &&
      matches(state.query, r.key, r.display, r.note, r.script, r.hypothesis),
  );

const snapshots = (r: Result) =>
  Object.entries(r.data ?? {})
    .map(([table, snapshot]) => `${table}@${snapshot ?? "?"}`)
    .join(", ");

function Results() {
  const wb = useWerkbank();
  const { detail: d, blank } = useDetail();
  const [state, setState] = useToolState<State>();
  const [selected, setSelected] = useLink<string | null>("result");
  const [, setHypothesis] = useLink<string | null>("hypothesis");
  const row = useRef<HTMLTableRowElement | null>(null);
  // A number clicked in the reader or a claim selects its result here: bring it into view.
  // In braces: newer browsers return a promise from scrollIntoView, and an effect must return nothing or a function.
  useEffect(() => {
    row.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);
  if (!d) return blank;
  const rows = select(d.result_list, state);
  const hypotheses = [...new Set(d.result_list.map((r) => r.hypothesis).filter((h): h is string => Boolean(h)))].sort();
  const current = d.result_list.find((r) => r.key === selected);
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <input className="wb-input sb-search" type="search" value={state.query} placeholder="Search results" aria-label="Search results" onChange={(e) => setState({ ...state, query: e.target.value })} />
        <Select
          value={state.hypothesis}
          aria-label="Hypothesis"
          options={[{ value: "all", label: "All results" }, ...hypotheses.map((h) => ({ value: h, label: h })), { value: "none", label: "No hypothesis", hint: "descriptive or exploratory" }]}
          onChange={(hypothesis) => setState({ ...state, hypothesis })}
        />
        <span>
          {rows.length} of {d.result_list.length}
        </span>
        <span className="sb-grow" />
        <button
          className="wb-button"
          onClick={() =>
            downloadCsv(`${d.slug}-results.csv`, ["key", "display", "value", "unit", "hypothesis", "script", "commit", "data", "recorded_at", "note"], rows.map((r) => [r.key, r.display, typeof r.value === "object" ? JSON.stringify(r.value) : (r.value as string | number), r.unit, r.hypothesis, r.script, r.git, snapshots(r), r.at, r.note]))
          }
        >
          CSV
        </button>
      </div>
      {d.result_problems.errors.map((line) => (
        <p key={line} className="sb-notice" data-tone="bad">
          {line}
        </p>
      ))}
      <div className="sb-split">
        <div className="sb-scroll">
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Value</th>
                <th>Hypothesis</th>
                <th>Recorded by</th>
                <th>Commit</th>
                <th>Data snapshot</th>
                <th>Recorded</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.key}
                  ref={r.key === selected ? row : undefined}
                  aria-selected={r.key === selected}
                  tabIndex={0}
                  onClick={() => setSelected(r.key)}
                  onKeyDown={(e) => e.key === "Enter" && setSelected(r.key)}
                  onContextMenu={(e) =>
                    openContextMenu(wb, e, [
                      { label: "Copy key", run: () => copyText(r.key) },
                      { label: "Copy as \\result{…}", run: () => copyText(`\\result{${r.key}}`) },
                      { label: "Copy as {{result:…}}", run: () => copyText(`{{result:${r.key}}}`) },
                      r.hypothesis ? { label: `Show hypothesis ${r.hypothesis}`, run: () => setHypothesis(r.hypothesis!) } : null,
                    ])
                  }
                >
                  <td>
                    <code>{r.key}</code>
                  </td>
                  <td className="wb-num">
                    {r.display}
                    {r.unit ? ` ${r.unit}` : ""}
                  </td>
                  <td>{r.hypothesis ?? "–"}</td>
                  <td>{r.script ?? <span className="wb-warn">no script</span>}</td>
                  <td>{r.git ? <span className={r.git.endsWith("+dirty") ? "wb-warn" : undefined}>{r.git}</span> : <span className="wb-warn">none</span>}</td>
                  <td>{snapshots(r) || "–"}</td>
                  <td>{when(r.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <Blank>{d.result_list.length ? "No result matches." : "No result recorded yet. Analysis scripts record them with sourcebound.results."}</Blank>}
        </div>
        {current && (
          <aside className="sb-detail" aria-label={`Result ${current.key}`}>
            <p>
              <code>{current.key}</code> = <strong className="wb-num">{current.display}</strong>
              {current.unit ? ` ${current.unit}` : ""}
            </p>
            <dl className="sb-facts">
              <dt>Exact value</dt>
              <dd className="wb-num">{typeof current.value === "object" ? JSON.stringify(current.value) : String(current.value)}</dd>
              {current.ci != null && (
                <>
                  <dt>Interval</dt>
                  <dd className="wb-num">{JSON.stringify(current.ci)}</dd>
                </>
              )}
              <dt>Hypothesis</dt>
              <dd>{current.hypothesis ?? "none (descriptive or exploratory)"}</dd>
              <dt>Recorded by</dt>
              <dd>
                {current.script ?? "–"} at commit {current.git ?? "none"}, {when(current.at)}
              </dd>
              <dt>Data</dt>
              <dd>{snapshots(current) || "no lake table named"}</dd>
              {current.note && (
                <>
                  <dt>Note</dt>
                  <dd>{current.note}</dd>
                </>
              )}
            </dl>
          </aside>
        )}
      </div>
    </div>
  );
}

export const resultsTool = defineTool<State>({
  id: "results",
  title: "Results",
  glyph: "#",
  category: "Evidence",
  version: 1,
  stateSchema,
  defaultState: () => ({ query: "", hypothesis: "all" }),
  links: ["project", "result", "hypothesis"],
  component: Results,
  describe: (state, { links }) => {
    const id = projectOf(links);
    const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
    if (!d) return { project: id, loaded: false };
    const rows = select(d.result_list, state);
    return {
      project: id, selected: links.result ?? null, filter: state, problems: d.result_problems, shown: rows.length, total: d.result_list.length,
      note: rows.length > prefs.rowCap ? `First ${prefs.rowCap} results shown; narrow the filter (panel.setState) for the rest.` : undefined,
      results: rows.slice(0, prefs.rowCap).map((r) => ({ key: r.key, display: r.display, value: r.value, unit: r.unit, hypothesis: r.hypothesis, script: r.script, commit: r.git, data: r.data, recorded_at: r.at, note: r.note })),
    };
  },
});
