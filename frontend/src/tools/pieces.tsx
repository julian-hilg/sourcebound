import { Select, copyText, defineTool, openContextMenu, useLink, useSetting, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import type { Piece } from "../data/api";
import { EmptyState } from "../kit";
import { prefs } from "../prefs";
import { counts, matches, show, Status, usePanelState, when } from "./lib";
import { pickPiece, pieceCard, piecesOf, usePieces } from "./pieces.lib";

/**
 * The pieces of a project: posts, notes, ideas, briefings. A piece is a folder under pieces/
 * (`sb piece`); this panel lists them and starts new ones. The text is edited in the Piece
 * panel, which follows the selection.
 */

const stateSchema = z.object({ query: z.string().max(80), status: z.string().max(20), title: z.string().max(200) });
type State = z.infer<typeof stateSchema>;

const select = (pieces: Piece[], state: State) =>
  pieces.filter((p) => (state.status === "all" || (state.status === "open" ? !["published", "dropped"].includes(p.status ?? "") : p.status === state.status)) && matches(state.query, p.id, p.title, p.kind, p.channel, p.text));

function PiecesPanel() {
  const wb = useWerkbank();
  const { project, data, error } = usePieces();
  const [state, setState] = usePanelState<State>();
  const [selected, setSelected] = useLink<string | null>("piece");
  const [template] = useSetting<string>("pieces.template");
  const [kind] = useSetting<string>("pieces.kind");
  const [channel] = useSetting<string>("pieces.channel");
  if (!data || !project) return <EmptyState>{error ?? "Loading…"}</EmptyState>;
  const rows = select(data.pieces, state);
  const current = pickPiece(data, selected);
  const create = async () => {
    const title = state.title.trim();
    if (!title) return;
    const result = await wb.run("piece.create", { project, title, kind: kind || "post", ...(template || data.defaults.template ? { template: template || data.defaults.template } : {}), ...(channel ? { channel } : {}) });
    if (result.ok) {
      setState({ ...state, title: "" });
      setSelected((result.value as Piece).id);
    }
  };
  const by: Record<string, number> = {};
  for (const p of data.pieces) by[p.status ?? "?"] = (by[p.status ?? "?"] ?? 0) + 1;
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <input className="wb-input sb-search" type="search" value={state.query} placeholder="Search pieces" aria-label="Search pieces" onChange={(e) => setState({ ...state, query: e.target.value })} />
        <Select
          value={state.status}
          aria-label="Status"
          options={[{ value: "open", label: "In work" }, { value: "all", label: "All" }, ...data.statuses.map((s) => ({ value: s, label: s, hint: by[s] ? String(by[s]) : undefined }))]}
          onChange={(status) => setState({ ...state, status })}
        />
        <span title={counts(by)}>
          {rows.length} of {data.pieces.length}
        </span>
      </div>
      <form
        className="wb-toolhead"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <input className="wb-input sb-grow" value={state.title} placeholder="Title of a new piece" aria-label="Title of a new piece" onChange={(e) => setState({ ...state, title: e.target.value })} />
        <button type="submit" className="wb-button" disabled={!state.title.trim()} title={`Adds a ${kind || "post"} under pieces/ (sb piece add)`}>
          Add piece
        </button>
      </form>
      <div className="sb-scroll">
        <table className="wb-table sb-table">
          <thead>
            <tr>
              <th>Piece</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Channel</th>
              <th>Scheduled</th>
              <th>Rendered</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr
                key={p.id}
                aria-selected={p.id === current?.id}
                tabIndex={0}
                onClick={() => setSelected(p.id)}
                onDoubleClick={() => void show(wb, "pieces", { patch: { tab: "edit" }, link: "1" })}
                onKeyDown={(e) => e.key === "Enter" && setSelected(p.id)}
                onContextMenu={(e) =>
                  openContextMenu(wb, e, [
                    { label: "Edit", run: () => (setSelected(p.id), void show(wb, "pieces", { patch: { tab: "edit" }, link: "1" })) },
                    { label: "Preview", run: () => (setSelected(p.id), void show(wb, "pieces", { patch: { tab: "preview" }, link: "1" })) },
                    { heading: "Status" },
                    ...(["idea", "draft", "review", "dropped"] as const).map((status) => ({ label: status, checked: p.status === status, run: () => void wb.run("piece.update", { project, id: p.id, patch: { status } }) })),
                    { label: "approved (your decision)", checked: p.status === "approved", run: () => void wb.run("piece.decide", { project, id: p.id, status: "approved" }) },
                    { separator: true },
                    { label: "Copy folder path", run: () => copyText(`pieces/${p.id}`) },
                    { label: "Delete piece", danger: true, run: () => void wb.run("piece.delete", { project, id: p.id }) },
                  ])
                }
              >
                <td className="sb-wrap">
                  {p.title}
                  {p.error && <div className="wb-warn">piece.yaml cannot be read: {p.error}</div>}
                  <div className="wb-dim">{p.id}</div>
                </td>
                <td>{p.kind ?? "–"}</td>
                <td>
                  <Status value={p.status} />
                </td>
                <td>{p.channel || "–"}</td>
                <td className="wb-num">{p.scheduled_at ? when(p.scheduled_at) : "–"}</td>
                <td title={p.renders.map((r) => `${r.template} ${when(r.at)}`).join("\n")}>
                  {p.renders.length ? p.renders.map((r) => r.template).join(", ") : "–"}
                  {p.renders.some((r) => r.stale.length) && <span className="wb-warn"> older values</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <EmptyState>
            {data.pieces.length ? "No piece matches." : "No piece yet. A piece is a small output of this project: a post, a note, a trade idea. It needs no paper; it does need its sources. Type a title above to start one."}
          </EmptyState>
        )}
      </div>
    </div>
  );
}

export const piecesTool = defineTool<State>({
  id: "pieces",
  title: "Pieces",
  glyph: "✉",
  category: "Pieces",
  version: 1,
  stateSchema,
  defaultState: () => ({ query: "", status: "open", title: "" }),
  links: ["project", "piece"],
  component: PiecesPanel,
  describe: (state, { links }) => {
    const { project, data } = piecesOf(links);
    if (!data) return { project, loaded: false };
    const rows = select(data.pieces, state);
    return {
      project,
      selected: pickPiece(data, links.piece)?.id ?? null,
      filter: { query: state.query, status: state.status },
      statuses: data.statuses,
      note: "Select with link.publish { topic: 'piece', value: id }. Change with piece.create, piece.update, piece.delete; check with piece.check; render with piece.render. Approving, scheduling and marking as published (piece.decide) are the person's decisions. Nothing here posts anywhere.",
      templates: data.templates.map((t) => ({ id: t.id, kind: t.kind, title: t.title })),
      shown: rows.length,
      pieces: rows.slice(0, prefs.rowCap).map((p) => pieceCard(p, 600)),
    };
  },
});
