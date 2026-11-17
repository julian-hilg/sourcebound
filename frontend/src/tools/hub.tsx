import { defineTool, useToolState, type ToolDefinition } from "@werkbank/framework";
import { z } from "zod";
import { HubPart } from "./lib";

/**
 * A hub: one panel that holds several related panels as tabs, and optionally a list beside them (master and
 * detail). Each part is an ordinary tool definition; its component reads and writes its own state through
 * `usePanelState`, which a hub keeps under the part's key. The hub's own state holds the open tab.
 *
 * Saved hub state looks like `{ tab: "claims", claims: {…}, hypotheses: {…} }`. A part whose state no longer
 * fits its schema starts from its default; the other parts keep theirs.
 */

export interface HubPartSpec {
  /** Key in the hub's state and in `{ tab }`. Stable: saved workspaces refer to it. */
  key: string;
  /** Tab label. */
  title: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tool: ToolDefinition<any>;
}

interface HubSpec {
  id: string;
  title: string;
  glyph: string;
  category: string;
  /** The tabs, in order; the first is open in a new panel. */
  parts: HubPartSpec[];
  /** A part always shown beside the tabs (a list whose selection the tabs follow); stacked above them when narrow. */
  side?: HubPartSpec;
}

type HubState = { tab: string } & Record<string, unknown>;

export function defineHub(spec: HubSpec) {
  const all = spec.side ? [spec.side, ...spec.parts] : spec.parts;
  const keys = spec.parts.map((p) => p.key) as [string, ...string[]];
  const stateSchema = z.object({
    tab: z.enum(keys).catch(keys[0]),
    ...Object.fromEntries(all.map((p) => [p.key, p.tool.stateSchema.catch(() => p.tool.defaultState())])),
  }) as unknown as z.ZodType<HubState>;

  function Hub() {
    const [state, setState] = useToolState<HubState>();
    const active = spec.parts.find((p) => p.key === state.tab) ?? spec.parts[0]!;
    const Active = active.tool.component;
    const tabs = (
      <div className="sb-hub-tabs" role="tablist" aria-label={spec.title}>
        {spec.parts.map((p) => (
          <button
            key={p.key}
            role="tab"
            className="sb-hub-tab"
            aria-selected={p.key === active.key}
            onClick={() => setState((current) => ({ ...current, tab: p.key }))}
          >
            {p.title}
          </button>
        ))}
      </div>
    );
    const body = (
      <div className="sb-hub-body" role="tabpanel">
        <HubPart.Provider value={active.key}>
          <Active key={active.key} />
        </HubPart.Provider>
      </div>
    );
    if (!spec.side) return <div className="sb-hub">{tabs}{body}</div>;
    const Side = spec.side.tool.component;
    return (
      <div className="sb-hub-frame">
        <div className="sb-hub sb-hub-split">
          <div className="sb-hub-side">
            <HubPart.Provider value={spec.side.key}>
              <Side />
            </HubPart.Provider>
          </div>
          <div className="sb-hub-main">{tabs}{body}</div>
        </div>
      </div>
    );
  }

  return defineTool<HubState>({
    id: spec.id,
    title: spec.title,
    glyph: spec.glyph,
    category: spec.category,
    version: 2,
    stateSchema,
    defaultState: () => ({ tab: keys[0], ...Object.fromEntries(all.map((p) => [p.key, p.tool.defaultState()])) }),
    links: [...new Set(all.flatMap((p) => p.tool.links ?? []))],
    commands: all.flatMap((p) => p.tool.commands ?? []),
    component: Hub,
    describe: (state, ctx) => {
      const active = spec.parts.find((p) => p.key === state.tab) ?? spec.parts[0]!;
      const part = (p: HubPartSpec) => (p.tool.describe ? p.tool.describe(state[p.key], ctx) : null);
      return {
        tab: active.key,
        tabs: spec.parts.map((p) => ({ tab: p.key, title: p.title })),
        note: `Switch tabs with panel.setState { id, patch: { tab } }. Only the open tab${spec.side ? " and the list beside it are" : " is"} described.`,
        ...(spec.side ? { [spec.side.key]: part(spec.side) } : {}),
        [active.key]: part(active),
      };
    },
  });
}
