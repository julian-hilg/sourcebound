import { defineTool, useLink } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, type Detail, type Hypothesis } from "../data/api";
import { Blank, projectOf, Status, useDetail, usePanelState } from "./lib";

const stateSchema = z.object({ open: z.array(z.string()).max(200) });
type State = z.infer<typeof stateSchema>;

const list = (value: string[] | string | undefined) => (Array.isArray(value) ? value : value ? [value] : []);

function Hypotheses() {
  const { detail: d, blank } = useDetail();
  const [state, setState] = usePanelState<State>();
  const [selected, setSelected] = useLink<string | null>("hypothesis");
  const [, setClaim] = useLink<string | null>("claim");
  const [, setResult] = useLink<string | null>("result");
  if (!d) return blank;
  const results = new Map(d.result_list.map((r) => [r.key, r]));
  const toggle = (h: Hypothesis) => {
    setSelected(h.id);
    setState({ open: state.open.includes(h.id) ? state.open.filter((x) => x !== h.id) : [...state.open, h.id] });
  };
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Hypotheses</strong>
        <span>{d.hypothesis_list.length}</span>
        <span>{d.frozen ? `frozen on ${d.frozen.date}` : "not frozen: analysis must not start"}</span>
        <span className="sb-grow" />
        <button className="wb-button" onClick={() => setState({ open: state.open.length ? [] : d.hypothesis_list.map((h) => h.id) })}>
          {state.open.length ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className="sb-scroll">
        {d.hypothesis_list.length === 0 && <Blank>No hypothesis in hypotheses.yaml yet.</Blank>}
        {d.hypothesis_list.map((h) => {
          const open = state.open.includes(h.id);
          return (
            <section key={h.id} className="sb-card" data-selected={h.id === selected}>
              <button className="sb-card-head" aria-expanded={open} onClick={() => toggle(h)}>
                <strong>{h.id}</strong>
                <Status value={h.status} />
                {h.exploratory && <span className="wb-badge">exploratory</span>}
                {h.registration !== "unchanged" && h.registration !== "not frozen" && <Status value={h.registration} />}
                <span className="sb-card-text">{h.statement}</span>
              </button>
              {open && (
                <dl className="sb-facts sb-card-body">
                  <dt>Prediction</dt>
                  <dd>{h.prediction ?? "–"}</dd>
                  <dt>Test</dt>
                  <dd>{h.test ?? "–"}</dd>
                  <dt>Data</dt>
                  <dd>{list(h.data).join(", ") || "–"}</dd>
                  {h.metric && (
                    <>
                      <dt>Metric</dt>
                      <dd>{h.metric}</dd>
                    </>
                  )}
                  <dt>Decision rule</dt>
                  <dd>{h.decision_rule ?? "–"}</dd>
                  <dt>Kill criterion</dt>
                  <dd>{h.kill ?? "–"}</dd>
                  <dt>Registration</dt>
                  <dd>
                    {h.registration === "unchanged"
                      ? "unchanged since the freeze"
                      : h.registration === "changed"
                        ? "changed after the freeze: needs an amendment and sb freeze --amend"
                        : h.registration}
                  </dd>
                  {list(h.motivated_by).length > 0 && (
                    <>
                      <dt>Motivated by</dt>
                      <dd>
                        {list(h.motivated_by).map((c) => (
                          <button key={c} className="sb-ref" onClick={() => setClaim(c)} title="Show this claim in the Claims panel">
                            {c}
                          </button>
                        ))}
                      </dd>
                    </>
                  )}
                  {list(h.results).length > 0 && (
                    <>
                      <dt>Results</dt>
                      <dd>
                        {list(h.results).map((ref) => {
                          const key = ref.replace(/^R:/, "");
                          const r = results.get(key);
                          return (
                            <button key={ref} className="sb-ref" onClick={() => setResult(key)} title={r ? "Show this result in the Results panel" : "Not recorded in results.json"}>
                              {key} = {r ? `${r.display}${r.unit ? ` ${r.unit}` : ""}` : "not recorded"}
                            </button>
                          );
                        })}
                      </dd>
                    </>
                  )}
                </dl>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

export const hypothesesTool = defineTool<State>({
  id: "hypotheses",
  title: "Hypotheses",
  glyph: "H",
  category: "Evidence",
  version: 1,
  stateSchema,
  defaultState: () => ({ open: [] }),
  links: ["project", "hypothesis", "claim", "result"],
  component: Hypotheses,
  describe: (_state, { links }) => {
    const id = projectOf(links);
    const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
    if (!d) return { project: id, loaded: false };
    return { project: id, selected: links.hypothesis ?? null, pre_registration: d.frozen, amendments: d.amendments, hypotheses: d.hypothesis_list };
  },
});
