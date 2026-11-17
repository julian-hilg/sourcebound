import { defineTool, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, type Detail } from "../data/api";
import { KeyValue } from "../kit";
import { counts, projectOf, show, useDetail, when } from "./lib";

const PHASES = ["brief", "landscape", "hypotheses", "data", "analysis", "review", "deliverables", "published"];
/** The gate a person passes after a phase: G1 after the brief, G2 after the hypotheses, G3 before publishing. */
const GATE_AFTER: Record<string, string> = { brief: "G1", hypotheses: "G2", deliverables: "G3" };

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

function Project() {
  const wb = useWerkbank();
  const { id, detail: d, blank } = useDetail();
  if (!d || !id) return blank;
  const at = PHASES.indexOf(d.phase ?? "");
  const log = [...d.log].reverse();
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>{d.slug}</strong>
        <span>
          {d.lang} · created {d.created || "–"}
        </span>
        <span className="sb-grow" />
        <button className="wb-button" onClick={() => void wb.run("sb.check", { project: id }).then(() => show(wb, "project", { patch: { tab: "check" } }))}>
          Check
        </button>
      </div>
      <div className="sb-scroll">
        <div className="sb-pad">
          <h2 className="sb-title">{d.title}</h2>
          <p className="wb-hint sb-path">{d.path}</p>
          {d.kind === "desk" && (
            <KeyValue
              items={[
                { label: "Kind", value: "desk: ongoing research on a topic; its outputs are pieces" },
                { label: "Topic", value: d.topic || "not written yet (project.yaml, topic:)" },
                { label: "Channels", value: (d.card.channels as string[] | undefined)?.join(", ") || "none named" },
                { label: "Pieces", value: `${d.pieces?.total ?? 0}: ${counts(d.pieces?.by_status)}` },
              ]}
            />
          )}
          <ol className="sb-phases" aria-label="Phases" hidden={d.kind === "desk"}>
            {PHASES.map((phase, i) => {
              const gate = d.gates?.find((g) => g.id === GATE_AFTER[phase]);
              return (
                <li key={phase} data-state={i < at ? "done" : i === at ? "current" : "ahead"} aria-current={i === at ? "step" : undefined}>
                  <span>{phase}</span>
                  {gate && (
                    <span className="sb-gate" data-passed={gate.passed} title={`${gate.title}: ${gate.passed ? gate.basis || "passed" : "open"}`}>
                      {gate.id} {gate.passed ? "✓" : "·"}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
        <div className="wb-kpis">
          {(
            [
              d.kind === "desk" ? ["Pieces", d.pieces?.total, counts(d.pieces?.by_status)] : ["Hypotheses", d.hypotheses?.total, counts(d.hypotheses?.by_status)],
              ["Claims", d.claims?.total, counts(d.claims?.by_status)],
              ["Results", d.results, d.result_problems.errors.length ? `${d.result_problems.errors.length} problems` : "recorded"],
              ["Web sources", d.web_sources, "archived"],
              ["Reviews", d.reviews, "reports"],
            ] as const
          ).map(([label, value, hint]) => (
            <div className="wb-kpi" key={label}>
              <div className="wb-kpi-label">{label}</div>
              <div className="wb-kpi-value">{value ?? "–"}</div>
              <div className="wb-kpi-label sb-kpi-hint" title={String(hint)}>
                {hint}
              </div>
            </div>
          ))}
        </div>
        <div className="sb-pad">
          <dl className="sb-facts">
            <dt hidden={d.kind === "desk"}>Pre-registration</dt>
            <dd hidden={d.kind === "desk"}>
              {d.frozen ? `frozen on ${d.frozen.date ?? "?"}${d.frozen.git ? ` at commit ${d.frozen.git}` : ""}, ${d.amendments.length} amendments` : "not frozen"}
            </dd>
            {(d.kind === "desk" ? [] : d.gates ?? []).map((g) => (
              <div key={g.id} style={{ display: "contents" }}>
                <dt>
                  {g.id} {g.title}
                </dt>
                <dd>{g.passed ? g.basis || "passed" : "open"}</dd>
              </div>
            ))}
            <dt>Deliverables</dt>
            <dd>{d.deliverable_folders.map((f) => `${f.name} (${f.format}, ${f.sections} sections${f.pdf ? ", PDF built" : ""})`).join("; ") || "none yet"}</dd>
            <dt>Handover</dt>
            <dd>{d.handover.built ? `built ${when(d.handover.at)}${d.handover.stale ? "; the text or results changed since" : ", up to date"}` : "not built"}</dd>
          </dl>
          {[...d.result_problems.errors, ...d.result_problems.warnings].map((line) => (
            <p key={line} className="sb-notice" data-tone="warn">
              {line}
            </p>
          ))}
          <h3 className="sb-heading">Research log</h3>
          {log.length === 0 && <p className="wb-hint">No entry in log.md yet.</p>}
          <ul className="sb-log">
            {log.map((entry, i) => (
              <li key={i}>
                <span className="wb-num wb-dim">{entry.date}</span> <strong>{entry.who}</strong> {entry.text}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export const projectTool = defineTool<State>({
  id: "project",
  title: "Project",
  glyph: "◧",
  category: "Study",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  links: ["project"],
  component: Project,
  describe: (_state, { links }) => {
    const id = projectOf(links);
    const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
    if (!d) return { project: id, loaded: false };
    return {
      project: id, title: d.title, kind: d.kind ?? "study", topic: d.topic, pieces: d.pieces, path: d.path, phase: d.phase, phases: PHASES, gates: d.gates, pre_registration: d.frozen, amendments: d.amendments,
      hypotheses: d.hypotheses, claims: d.claims, results: d.results, result_problems: d.result_problems, web_sources: d.web_sources,
      deliverables: d.deliverable_folders, handover: d.handover, card: d.card, log: d.log.slice(-40),
    };
  },
});
