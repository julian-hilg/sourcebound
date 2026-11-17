import { defineTool, useSetting } from "@werkbank/framework";
import { prefs } from "../prefs";
import { z } from "zod";
import { api, paths, useApi, type ActivityEvent } from "../data/api";
import { ago, Blank, projectOf, usePanelState, useProject, when } from "./lib";

const stateSchema = z.object({ scope: z.enum(["all", "project"]) });
type State = z.infer<typeof stateSchema>;
interface Activity {
  log: string;
  events: ActivityEvent[];
}

/** A session counts as working if it reported something in the last two minutes and has not stopped since. */
const ACTIVE_MS = 120_000;
const select = (events: ActivityEvent[], state: State, project: string | null) => events.filter((e) => state.scope === "all" || e.project === project);

function sessions(events: ActivityEvent[]) {
  const latest = new Map<string, ActivityEvent>();
  for (const e of events) if (!latest.has(e.session)) latest.set(e.session, e);
  return [...latest.values()].filter((e) => e.event !== "Stop" && Date.now() - new Date(e.ts).getTime() < ACTIVE_MS);
}

/** What an event says, in words. */
const what = (e: ActivityEvent) =>
  e.event === "PreToolUse"
    ? e.tool === "Agent" || e.tool === "Task"
      ? `starts subagent ${e.agent ?? ""}`
      : `uses ${e.tool ?? "a tool"}`
    : e.event === "SubagentStop"
      ? `subagent ${e.agent ?? ""} finished`
      : e.event === "Stop"
        ? "finished its turn"
        : e.event === "SessionStart"
          ? "session started"
          : e.event;

function ActivityPanel() {
  const { id } = useProject();
  const [state, setState] = usePanelState<State>();
  // Reloaded every few seconds while the panel is visible (Settings → Reloading).
  const activity = useApi<Activity>(paths.activity, prefs.every.activity);
  const [hide] = useSetting<string>("activity.hideTools");
  const [subagentsOnly] = useSetting<boolean>("activity.subagentsOnly");
  const [maxRows] = useSetting<number>("activity.maxRows");
  const hidden = new Set(hide.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean));
  if (!activity.data) return <Blank>{activity.error ?? "Loading…"}</Blank>;
  const all = select(activity.data.events, state, id);
  const rows = all.filter((e) => !(e.event === "PreToolUse" && hidden.has((e.tool ?? "").toLowerCase())) && (!subagentsOnly || Boolean(e.agent))).slice(0, maxRows);
  const working = sessions(activity.data.events);
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Agents</strong>
        <span className="sb-status" data-tone={working.length ? "good" : undefined}>
          {working.length ? `${working.length} session${working.length > 1 ? "s" : ""} working` : "idle"}
        </span>
        <span className="sb-grow" />
        <span className="wb-segment" role="group" aria-label="Scope">
          <button className="wb-button" aria-pressed={state.scope === "all"} onClick={() => setState({ scope: "all" })}>
            All projects
          </button>
          <button className="wb-button" aria-pressed={state.scope === "project"} onClick={() => setState({ scope: "project" })}>
            {id ?? "Selected project"}
          </button>
        </span>
      </div>
      <div className="sb-scroll">
        {rows.length === 0 ? (
          <Blank>
            {all.length
              ? "Every event is hidden by the filters under Settings → Agents panel."
              : activity.data.events.length
              ? "No event for this project yet."
              : "No agent activity recorded yet. Run `sb install hooks` once; Claude Code sessions started after that report what they do here."}
          </Blank>
        ) : (
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Project</th>
                <th>Agent</th>
                <th>What</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => (
                <tr key={`${e.ts}${e.session}${i}`}>
                  <td className="wb-num" title={when(e.ts)}>
                    {ago(e.ts)}
                  </td>
                  <td title={e.cwd}>{e.project ?? "–"}</td>
                  <td title={`session ${e.session}`}>{e.agent ?? "lead"}</td>
                  <td>{what(e)}</td>
                  <td className="sb-wrap">{e.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export const activityTool = defineTool<State>({
  id: "activity",
  title: "Agents",
  glyph: "◉",
  category: "Study",
  version: 1,
  stateSchema,
  defaultState: () => ({ scope: "all" }),
  links: ["project"],
  component: ActivityPanel,
  describe: (state, { links }) => {
    const activity = api.peek<Activity>(paths.activity);
    if (!activity) return { loaded: false };
    const rows = select(activity.events, state, projectOf(links));
    return {
      log_file: activity.log, scope: state.scope, project: projectOf(links),
      note: "Claude Code hook events, newest first. A line holds the tool and one short summary, never a prompt or file contents.",
      sessions_working: sessions(activity.events).map((e) => ({ session: e.session, project: e.project, last_event: e.ts })),
      events: rows.slice(0, Math.min(80, prefs.rowCap)),
    };
  },
});
