import { Select, copyText, defineTool, openContextMenu, useSetting, useToolState, useWerkbank } from "@werkbank/framework";
import { ConfirmButton } from "../kit";
import { z } from "zod";
import { api, paths, type Detail, type Note } from "../data/api";
import { Status, projectOf, useDetail, when } from "./lib";

/**
 * The deliverables manager: what exists under deliverables/, and what is wanted (notes with a
 * status and a stored prompt, kept in deliverables/notes.yaml). The form keeps what was typed
 * as strings in the panel's state, so a half-written note survives a reload.
 */

const STATUSES = ["idea", "planned", "drafting", "review", "done", "dropped"] as const;
const KINDS = ["paper", "note", "report", "infographic", "post", "slides", "video", "other"];
const draftSchema = z.object({ title: z.string(), kind: z.string(), status: z.string(), deliverable: z.string(), text: z.string(), prompt: z.string() });
type Draft = z.infer<typeof draftSchema>;
const stateSchema = z.object({
  /** The note in the form: an id, "new", or nothing. */
  editing: z.string().nullable(),
  draft: draftSchema.nullable(),
});
type State = z.infer<typeof stateSchema>;

/** One schema for a note, used by the form here; the service validates the same rules again. */
const noteSchema = z.object({
  title: z.string().trim().min(1, "A note needs a title.").max(200, "At most 200 characters."),
  kind: z.string().trim().min(1, "Say what kind of deliverable it is.").max(40),
  status: z.enum(STATUSES),
  deliverable: z.string().trim().max(80),
  text: z.string().max(20_000),
  prompt: z.string().max(20_000),
});

const EMPTY: Draft = { title: "", kind: "note", status: "idea", deliverable: "", text: "", prompt: "" };
const draftOf = (n: Note): Draft => ({ title: n.title, kind: n.kind, status: n.status, deliverable: n.deliverable ?? "", text: n.text ?? "", prompt: n.prompt ?? "" });

function Deliverables() {
  const wb = useWerkbank();
  const { id, detail: d, blank } = useDetail();
  const [state, setState] = useToolState<State>();
  const [confirmDelete] = useSetting<boolean>("confirm.delete");
  if (!d || !id) return blank;
  const draft = state.draft;
  const checked = draft ? noteSchema.safeParse(draft) : null;
  const errors: Record<string, string> = {};
  if (checked && !checked.success) for (const issue of checked.error.issues) errors[String(issue.path[0])] ??= issue.message;
  const edit = (patch: Partial<Draft>) => setState({ ...state, draft: { ...(draft ?? EMPTY), ...patch } });
  const open = (note: Note | null) => setState({ editing: note ? note.id : "new", draft: note ? draftOf(note) : EMPTY });
  const close = () => setState({ editing: null, draft: null });
  const save = async () => {
    if (!checked?.success) return;
    const result = state.editing === "new" ? await wb.run("note.create", { project: id, ...checked.data }) : await wb.run("note.update", { project: id, id: state.editing, patch: checked.data });
    if (result.ok) close();
  };
  const field = (key: keyof Draft, label: string, control: React.ReactNode) => (
    <div className="wb-form-row">
      <label className="wb-control-label" htmlFor={`note-${key}`}>
        {label}
      </label>
      {control}
      {errors[key] && <div className="wb-control-error">{errors[key]}</div>}
    </div>
  );
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Deliverables</strong>
        <span>
          {d.deliverable_folders.length} written, {d.notes.filter((n) => n.status !== "done" && n.status !== "dropped").length} wanted
        </span>
        <span className="sb-grow" />
        <button className="wb-button" onClick={() => open(null)}>
          New note
        </button>
      </div>
      <div className="sb-split">
        <div className="sb-scroll">
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>Deliverable</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {d.deliverable_folders.map((f) => (
                <tr key={`folder-${f.name}`}>
                  <td className="sb-wrap">
                    <strong>deliverables/{f.name}</strong>{" "}
                    <span className="wb-dim">
                      {f.format}, {f.sections} sections
                    </span>
                  </td>
                  <td>{f.kind || "–"}</td>
                  <td>
                    <button className="sb-ref" onClick={() => void wb.run("panel.open", { toolId: "deliverable" })}>
                      Read
                    </button>
                    {f.pdf && (
                      <a className="sb-ref" href={paths.raw(id, f.pdf)} target="_blank" rel="noreferrer">
                        PDF
                      </a>
                    )}
                  </td>
                  <td>–</td>
                </tr>
              ))}
              {d.notes.map((n) => (
                <tr
                  key={n.id}
                  aria-selected={n.id === state.editing}
                  tabIndex={0}
                  onClick={() => open(n)}
                  onKeyDown={(e) => e.key === "Enter" && open(n)}
                  onContextMenu={(e) =>
                    openContextMenu(wb, e, [
                      { heading: "Status" },
                      ...STATUSES.map((status) => ({ label: status, checked: n.status === status, run: () => void wb.run("note.update", { project: id, id: n.id, patch: { status } }) })),
                      { separator: true },
                      { label: "Copy prompt", disabled: !n.prompt, run: () => copyText(n.prompt) },
                      { label: "Delete note", danger: true, run: () => void wb.run("note.delete", { project: id, id: n.id }).then(close) },
                    ])
                  }
                >
                  <td className="sb-wrap">
                    <span className="wb-dim">{n.id}</span> {n.title}
                  </td>
                  <td>{n.kind}</td>
                  <td>
                    <Status value={n.status} />
                  </td>
                  <td>{when(n.updated, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.notes.length === 0 && (
            <p className="wb-hint sb-pad">
              No note yet. A note records a deliverable you want from this study (a two-page note, an infographic, a talk), how far it is, and the prompt an
              agent gets for it. Notes are kept in deliverables/notes.yaml; `sb note` edits the same file.
            </p>
          )}
        </div>
        {draft && (
          <form
            className="sb-detail wb-form"
            aria-label={state.editing === "new" ? "New note" : `Note ${state.editing}`}
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <p>
              <strong>{state.editing === "new" ? "New note" : `Note ${state.editing}`}</strong>
            </p>
            {field("title", "Title", <input id="note-title" className="wb-input" value={draft.title} aria-invalid={Boolean(errors.title)} placeholder="Two-page note for practitioners" onChange={(e) => edit({ title: e.target.value })} />)}
            {field("kind", "Kind", <Select id="note-kind" value={draft.kind} options={[...new Set([...KINDS, draft.kind])].filter(Boolean).map((k) => ({ value: k, label: k }))} onChange={(kind) => edit({ kind })} />)}
            {field("status", "Status", <Select id="note-status" value={draft.status} options={STATUSES.map((s) => ({ value: s, label: s }))} onChange={(status) => edit({ status })} />)}
            {field(
              "deliverable",
              "Folder",
              <Select
                id="note-deliverable"
                value={draft.deliverable || "-"}
                options={[{ value: "-", label: "Not written yet" }, ...d.deliverable_folders.map((f) => ({ value: f.name, label: `deliverables/${f.name}` }))]}
                onChange={(v) => edit({ deliverable: v === "-" ? "" : v })}
              />,
            )}
            {field("text", "Notes", <textarea id="note-text" className="wb-input sb-area" value={draft.text} placeholder="Audience, length, what to keep in mind" onChange={(e) => edit({ text: e.target.value })} />)}
            {field("prompt", "Prompt", <textarea id="note-prompt" className="wb-input sb-area" value={draft.prompt} placeholder="What the writer agent is asked to produce, e.g. an infographic of finding H2" onChange={(e) => edit({ prompt: e.target.value })} />)}
            <div className="wb-form-actions">
              <button type="submit" className="wb-button" disabled={!checked?.success}>
                Save
              </button>
              <button type="button" className="wb-button" onClick={close}>
                Cancel
              </button>
              {draft.prompt && (
                <button type="button" className="wb-button" onClick={() => copyText(draft.prompt)}>
                  Copy prompt
                </button>
              )}
              {state.editing !== "new" && (
                <ConfirmButton confirm={confirmDelete} tone="warn" question="Delete this note?" onConfirm={() => void wb.run("note.delete", { project: id, id: state.editing }).then(close)}>
                  Delete
                </ConfirmButton>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export const deliverablesTool = defineTool<State>({
  id: "deliverables",
  title: "Deliverables",
  glyph: "☰",
  category: "Deliverables",
  version: 1,
  stateSchema,
  defaultState: () => ({ editing: null, draft: null }),
  links: ["project"],
  component: Deliverables,
  describe: (state, { links }) => {
    const id = projectOf(links);
    const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
    if (!d) return { project: id, loaded: false };
    return {
      project: id,
      written: d.deliverable_folders,
      handover: d.handover,
      notes: d.notes,
      form: state.editing ? { editing: state.editing, draft: state.draft } : null,
      note: "Change notes with note.create, note.update and note.delete; they are stored in deliverables/notes.yaml of the project.",
    };
  },
});
