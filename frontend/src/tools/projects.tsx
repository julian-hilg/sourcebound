import { copyText, defineTool, openContextMenu, useSetting, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, type Summary } from "../data/api";
import { Blank, ago, counts, downloadText, projectOf, useProject } from "./lib";

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

const gates = (p: Summary) => (p.gates ?? []).map((g) => `${g.id} ${g.passed ? "passed" : "open"}`).join(", ");

function Projects() {
  const wb = useWerkbank();
  const { id, select, list } = useProject();
  const projects = list.data?.projects;
  const [switchWorkspace] = useSetting<boolean>("projects.switchWorkspace");
  const [studyWorkspace] = useSetting<string>("projects.studyWorkspace");
  const [deskWorkspace] = useSetting<string>("projects.deskWorkspace");
  /** Select a project and switch to the workspace chosen for its kind (the selection survives the switch: presets share the link group). */
  const openIn = async (p: Summary) => {
    await wb.run("workspace.preset", { name: p.kind === "desk" ? deskWorkspace : studyWorkspace });
    await wb.run("link.publish", { group: "1", topic: "project", value: p.id });
  };
  const saveWorkspace = async () => {
    const result = await wb.run("vscode.workspace");
    if (result.ok) downloadText("research.code-workspace", JSON.stringify((result.value as { workspace: unknown }).workspace, null, 2) + "\n", "application/json");
  };
  if (!projects) return <Blank>{list.error ?? "Loading…"}</Blank>;
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Projects</strong>
        <span>{projects.length} found</span>
        <span className="sb-grow" />
        <button className="wb-button" title="Download a VS Code workspace with every project, the data root and the usual sb steps as tasks" onClick={() => void saveWorkspace()}>
          VS Code workspace
        </button>
      </div>
      {list.error && <p className="sb-notice" data-tone="warn">{list.error}</p>}
      <div className="sb-scroll">
        <table className="wb-table sb-table">
          <thead>
            <tr>
              <th>Project</th>
              <th>Kind</th>
              <th>Phase</th>
              <th>Gates</th>
              <th>Hypotheses</th>
              <th>Claims</th>
              <th>Results</th>
              <th>Pieces</th>
              <th>Reviews</th>
              <th>Last change</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr
                key={p.id}
                aria-selected={p.id === id}
                tabIndex={0}
                onClick={() => select(p.id)}
                onDoubleClick={() => switchWorkspace && void openIn(p)}
                onKeyDown={(e) => e.key === "Enter" && select(p.id)}
                onContextMenu={(e) =>
                  openContextMenu(wb, e, [
                    { label: "Select", run: () => select(p.id) },
                    { label: `Open in its workspace (${p.kind === "desk" ? deskWorkspace : studyWorkspace})`, run: () => void openIn(p) },
                    { label: "Run sb check", run: () => void wb.run("sb.check", { project: p.id }) },
                    { separator: true },
                    { label: "Copy folder path", run: () => copyText(p.path) },
                  ])
                }
              >
                <td className="sb-wrap" title={`${p.title}
${p.path}`}>
                  <strong>{p.slug}</strong>
                  {p.title !== p.slug && <div className="wb-dim sb-clamp">{p.title}</div>}
                  {p.error && <div className="wb-warn">Cannot be read: {p.error}</div>}
                </td>
                <td>{p.kind ?? "study"}</td>
                <td>{p.phase ?? "–"}</td>
                <td title={(p.gates ?? []).map((g) => `${g.id} ${g.title}: ${g.passed ? g.basis || "passed" : "open"}`).join("\n")}>
                  {p.kind === "desk" && <span className="wb-dim" title="A desk has no gates G1 and G2; publishing a piece is your decision">–</span>}
                  {(p.kind === "desk" ? [] : p.gates ?? []).map((g) => (
                    <span key={g.id} className="sb-gate" data-passed={g.passed}>
                      {g.id} {g.passed ? "✓" : "·"}
                    </span>
                  ))}
                </td>
                <td title={counts(p.hypotheses?.by_status)}>
                  {p.kind === "desk" ? "–" : (p.hypotheses?.total ?? "–")}
                  {p.hypotheses?.total ? <span className="wb-dim"> {p.hypotheses.frozen ? "frozen" : "not frozen"}</span> : null}
                </td>
                <td title={counts(p.claims?.by_status)}>
                  {p.claims?.total ?? "–"}
                  {p.claims?.by_status.open ? <span className="wb-warn"> {p.claims.by_status.open} open</span> : null}
                </td>
                <td>{p.results ?? "–"}</td>
                <td title={counts(p.pieces?.by_status)}>{p.pieces?.total ?? "–"}</td>
                <td>{p.reviews ?? "–"}</td>
                <td title={p.last_change ?? ""}>{ago(p.last_change)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {projects.length === 0 && <Blank>No project found. Create one with `sb new`, or start `sb ui` inside a project.</Blank>}
      </div>
    </div>
  );
}

export const projectsTool = defineTool<State>({
  id: "projects",
  title: "Projects",
  glyph: "▦",
  category: "Study",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  links: ["project"],
  component: Projects,
  describe: (_state, { links }) => {
    const projects = api.peek<{ projects: Summary[] }>(paths.projects)?.projects;
    if (!projects) return { loaded: false, note: "Project data has not been loaded yet; run data.refresh or describe again." };
    return {
      selected: projectOf(links),
      note: "Select a project for linked panels with link.publish { topic: 'project', value: <id> }.",
      projects: projects.map((p) => ({
        id: p.id, title: p.title, kind: p.kind ?? "study", topic: p.topic, pieces: p.pieces, path: p.path, phase: p.phase, gates: gates(p), hypotheses: p.hypotheses, claims: p.claims,
        results: p.results, reviews: p.reviews, web_sources: p.web_sources, deliverables: p.deliverables,
        last_change: p.last_change, last_log: p.last_log, error: p.error,
      })),
    };
  },
});
