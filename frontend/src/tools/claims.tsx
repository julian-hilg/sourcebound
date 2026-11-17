import { Select, copyText, defineTool, openContextMenu, useLink, useToolState, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, type Claim, type Detail } from "../data/api";
import { prefs } from "../prefs";
import { Blank, Status, counts, downloadCsv, matches, projectOf, useDetail } from "./lib";

const stateSchema = z.object({ query: z.string().max(120), status: z.string().max(20), kind: z.string().max(20) });
type State = z.infer<typeof stateSchema>;

const select = (claims: Claim[], state: State) =>
  claims.filter(
    (c) =>
      (state.status === "all" || c.status === state.status) &&
      (state.kind === "all" || c.kind === state.kind) &&
      matches(state.query, c.id, c.text, c.note, ...(c.evidence ?? []).flatMap((e) => [e.ref, e.quote])),
  );

/** What kind of evidence a reference is, from its form. */
const refKind = (ref: string) => (ref.startsWith("R:") ? "result" : ref.startsWith("data:") ? "data" : /^W-\d+$/.test(ref) ? "web source" : "literature");

function Claims() {
  const wb = useWerkbank();
  const { detail: d, blank } = useDetail();
  const [state, setState] = useToolState<State>();
  const [selected, setSelected] = useLink<string | null>("claim");
  const [, setResult] = useLink<string | null>("result");
  if (!d) return blank;
  const rows = select(d.claim_list, state);
  const current = d.claim_list.find((c) => c.id === selected);
  const sources = new Map(d.source_list.map((s) => [s.id, s]));
  const results = new Map(d.result_list.map((r) => [r.key, r]));
  const options = (values: (string | undefined)[], all: string) => [
    { value: "all", label: all },
    ...[...new Set(values.filter((v): v is string => Boolean(v)))].sort().map((v) => ({ value: v, label: v })),
  ];
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <input className="wb-input sb-search" type="search" value={state.query} placeholder="Search claims" aria-label="Search claims" onChange={(e) => setState({ ...state, query: e.target.value })} />
        <Select value={state.status} aria-label="Status" options={options(d.claim_list.map((c) => c.status), "All statuses")} onChange={(status) => setState({ ...state, status })} />
        <Select value={state.kind} aria-label="Kind" options={options(d.claim_list.map((c) => c.kind), "All kinds")} onChange={(kind) => setState({ ...state, kind })} />
        <span title={counts(d.claims?.by_status)}>
          {rows.length} of {d.claim_list.length}
        </span>
        <span className="sb-grow" />
        <button
          className="wb-button"
          onClick={() => downloadCsv(`${d.slug}-claims.csv`, ["id", "status", "kind", "text", "evidence"], rows.map((c) => [c.id, c.status, c.kind, c.text, (c.evidence ?? []).map((e) => `${e.ref} (${e.stance ?? "?"})`).join("; ")]))}
        >
          CSV
        </button>
      </div>
      <div className="sb-split">
        <div className="sb-scroll">
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Claim</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.id}
                  aria-selected={c.id === selected}
                  tabIndex={0}
                  onClick={() => setSelected(c.id)}
                  onKeyDown={(e) => e.key === "Enter" && setSelected(c.id)}
                  onContextMenu={(e) => openContextMenu(wb, e, [{ label: "Copy id and text", run: () => copyText(`${c.id} ${c.text}`) }])}
                >
                  <td>{c.id}</td>
                  <td className="sb-wrap">{c.text}</td>
                  <td>{c.kind ?? "–"}</td>
                  <td>
                    <Status value={c.status} />
                  </td>
                  <td title={(c.evidence ?? []).map((e) => `${e.ref} (${e.stance ?? "?"})`).join("\n")}>
                    {(c.evidence ?? []).length}
                    {(c.evidence ?? []).some((e) => e.stance === "contradicts") && <span className="wb-warn"> contradicted</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <Blank>{d.claim_list.length ? "No claim matches." : "No claim in evidence/claims.yaml yet."}</Blank>}
        </div>
        {current && (
          <aside className="sb-detail" aria-label={`Claim ${current.id}`}>
            <p>
              <strong>{current.id}</strong> <Status value={current.status} /> <span className="wb-dim">{current.kind}</span>
            </p>
            <p>{current.text}</p>
            {current.note && <p className="wb-hint">{current.note}</p>}
            {(current.evidence ?? []).length === 0 && <p className="wb-warn">No evidence: this claim must not be used in a deliverable.</p>}
            <ul className="sb-evidence">
              {(current.evidence ?? []).map((e, i) => {
                const source = sources.get(e.ref);
                const result = e.ref.startsWith("R:") ? results.get(e.ref.slice(2)) : undefined;
                return (
                  <li key={i}>
                    <span className="sb-status" data-tone={e.stance === "contradicts" ? "bad" : e.stance === "supports" ? "good" : undefined}>
                      {e.stance ?? "?"}
                    </span>{" "}
                    {e.ref.startsWith("R:") ? (
                      <button className="sb-ref" onClick={() => setResult(e.ref.slice(2))} title="Show this result in the Results panel">
                        {e.ref}
                        {result ? ` = ${result.display}` : " (not recorded)"}
                      </button>
                    ) : (
                      <code>{e.ref}</code>
                    )}{" "}
                    <span className="wb-dim">{refKind(e.ref)}</span>
                    {e.loc && <span> · {e.loc}</span>}
                    {source && (
                      <div>
                        {source.title}
                        {source.publisher ? `, ${source.publisher}` : ""}{" "}
                        {source.url && (
                          <a href={source.url} target="_blank" rel="noreferrer">
                            {new URL(source.url).host}
                          </a>
                        )}
                      </div>
                    )}
                    {e.quote && <blockquote>{e.quote}</blockquote>}
                    {e.note && <div className="wb-hint">{e.note}</div>}
                  </li>
                );
              })}
            </ul>
          </aside>
        )}
      </div>
    </div>
  );
}

export const claimsTool = defineTool<State>({
  id: "claims",
  title: "Claims",
  glyph: "§",
  category: "Evidence",
  version: 1,
  stateSchema,
  defaultState: () => ({ query: "", status: "all", kind: "all" }),
  links: ["project", "claim", "result"],
  component: Claims,
  describe: (state, { links }) => {
    const id = projectOf(links);
    const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
    if (!d) return { project: id, loaded: false };
    const rows = select(d.claim_list, state);
    return {
      project: id, selected: links.claim ?? null, filter: state, by_status: d.claims?.by_status, shown: rows.length, total: d.claim_list.length,
      note: rows.length > prefs.rowCap ? `First ${prefs.rowCap} claims shown; narrow the filter (panel.setState) for the rest.` : undefined,
      claims: rows.slice(0, prefs.rowCap),
      web_sources: d.source_list.map(({ id: sid, title, url, publisher, accessed }) => ({ id: sid, title, url, publisher, accessed })),
    };
  },
});
