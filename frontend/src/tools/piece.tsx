import { Select, copyText, defineTool, useLink, useSetting, useWerkbank } from "@werkbank/framework";
import { useState } from "react";
import { z } from "zod";
import { paths, type Piece, type PieceCheck } from "../data/api";
import { ConfirmButton, EmptyState, KeyValue, Section, StatusPill } from "../kit";
import { prefs } from "../prefs";
import { weekdays } from "../settings";
import { Status, usePanelState, when } from "./lib";
import { STAMP, nextSlot, pickPiece, pieceCard, piecesOf, usePieces } from "./pieces.lib";

/**
 * One piece: its text, its card, its checks, its renders and the decisions about it.
 * What is typed is kept as a draft in the panel's state until it is saved through a command
 * (so it survives a reload and the save can be undone).
 */

const draftSchema = z.object({ text: z.string().max(60_000), title: z.string().max(200), kind: z.string().max(30), channel: z.string().max(40), template: z.string().max(60), note: z.string().max(4000), prompt: z.string().max(20_000) });
type Draft = z.infer<typeof draftSchema>;
const stateSchema = z.object({
  view: z.enum(["text", "card", "output"]),
  /** Unsaved changes, per "<project>/<piece>". The newest few are kept. */
  drafts: z.record(z.string(), draftSchema),
  when: z.string().max(20),
  renderWith: z.string().max(60),
});
type State = z.infer<typeof stateSchema>;

const KEYS = ["text", "title", "kind", "channel", "template", "note", "prompt"] as const;
const draftOf = (p: Piece): Draft => ({ text: p.text, title: p.title, kind: p.kind ?? "", channel: p.channel ?? "", template: p.template ?? "", note: p.note ?? "", prompt: p.prompt ?? "" });
const changed = (p: Piece, d: Draft) => KEYS.filter((k) => d[k] !== draftOf(p)[k]);

function PiecePanel() {
  const wb = useWerkbank();
  const { project, data, error } = usePieces();
  const [state, setState] = usePanelState<State>();
  const [linked] = useLink<string | null>("piece");
  const [days] = useSetting<string>("pieces.postingDays");
  const [time] = useSetting<string>("pieces.postingTime");
  const [confirmRender] = useSetting<boolean>("confirm.render");
  const [confirmDelete] = useSetting<boolean>("confirm.delete");
  const [check, setCheck] = useState<PieceCheck | null>(null);
  const [message, setMessage] = useState<{ tone?: "bad"; text: string } | null>(null);
  if (!data || !project) return <EmptyState>{error ?? "Loading…"}</EmptyState>;
  const piece = pickPiece(data, linked);
  if (!piece) return <EmptyState>No piece selected. Add one in the Pieces panel.</EmptyState>;
  const key = `${project}/${piece.id}`;
  const saved = draftOf(piece);
  const draft = state.drafts[key] ?? saved;
  const dirty = changed(piece, draft);
  const tooLong = piece.text.length > 60_000;
  const edit = (patch: Partial<Draft>) => {
    const next = { ...draft, ...patch };
    const others = Object.entries(state.drafts).filter(([k]) => k !== key).slice(-3);
    setState({ ...state, drafts: Object.fromEntries(changed(piece, next).length ? [...others, [key, next]] : others) });
  };
  const forget = () => setState({ ...state, drafts: Object.fromEntries(Object.entries(state.drafts).filter(([k]) => k !== key)) });
  const say = (result: { ok: boolean; error?: string }, done: string) => setMessage(result.ok ? { text: done } : { tone: "bad", text: result.error ?? "It did not work." });
  const save = async () => {
    if (!dirty.length) return;
    if (!draft.title.trim()) return setMessage({ tone: "bad", text: "A piece needs a title." });
    const result = await wb.run("piece.update", { project, id: piece.id, patch: Object.fromEntries(dirty.map((k) => [k, draft[k]])) });
    if (result.ok) forget();
    say(result, "Saved.");
  };
  const runCheck = async () => {
    const result = await wb.run("piece.check", { project, id: piece.id });
    if (result.ok) setCheck(result.value as PieceCheck);
    else setMessage({ tone: "bad", text: result.error });
  };
  const template = state.renderWith || piece.template || data.templates[0]?.id || "";
  const render = async () => say(await wb.run("piece.render", { project, id: piece.id, template }), `Rendered with ${template}.`);
  const exportTo = data.export_dir;
  const exportFiles = async () => {
    const result = await wb.run("piece.export", { project, id: piece.id });
    if (result.ok) setMessage({ text: `Exported to ${(result.value as { folder: string }).folder}. Nothing was posted.` });
    else setMessage({ tone: "bad", text: result.error });
  };
  const decide = async (status: "approved" | "scheduled" | "published", extra: object = {}) => say(await wb.run("piece.decide", { project, id: piece.id, status, ...extra }), status === "scheduled" ? "Scheduled." : status === "approved" ? "Approved." : "Marked as published.");
  const slot = state.when.trim();
  const field = (k: Exclude<(typeof KEYS)[number], "text">, label: string, control: React.ReactNode) => (
    <div className="wb-form-row">
      <label className="wb-control-label" htmlFor={`piece-${k}`}>
        {label}
      </label>
      {control}
    </div>
  );
  const words = draft.text.trim().split(/\s+/).filter(Boolean).length;
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong className="kit-ellipsis" title={piece.id}>
          {draft.title || piece.id}
        </strong>
        <Status value={piece.status} />
        {piece.scheduled_at && <span>for {when(piece.scheduled_at)}</span>}
        <span className="kit-grow" />
        <span className="wb-segment" role="group" aria-label="View">
          {(["text", "card", "output"] as const).map((view) => (
            <button key={view} className="wb-button" aria-pressed={state.view === view} onClick={() => setState({ ...state, view })}>
              {view === "text" ? "Text" : view === "card" ? "Card" : `Output (${piece.renders.length})`}
            </button>
          ))}
        </span>
        <button className="wb-button" disabled={!dirty.length} onClick={() => void save()} title="Writes the changes to the piece's files (sb piece set); can be undone from the action history">
          Save{dirty.length ? ` (${dirty.length})` : ""}
        </button>
        {dirty.length > 0 && (
          <button className="wb-button" onClick={forget}>
            Revert
          </button>
        )}
      </div>
      {message && (
        <p className="sb-notice" data-tone={message.tone} role="status">
          {message.text}
        </p>
      )}
      {piece.error && <p className="sb-notice" data-tone="bad">piece.yaml cannot be read: {piece.error}</p>}
      {state.view === "text" ? (
        tooLong ? (
          <EmptyState>This text is longer than the editor here takes ({piece.text.length.toLocaleString(prefs.locale)} characters). Edit pieces/{piece.id}/text.md in your editor.</EmptyState>
        ) : (
          <>
            <textarea className="sb-editor" spellCheck aria-label="Text of the piece" lang={piece.lang} value={draft.text} placeholder={"Write the text here.\n\nA recorded number: {{result:key}}\nA source: [@W-0001] (sb snap URL, or sb doc FILE)"} onChange={(e) => edit({ text: e.target.value })} onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "s" && (e.preventDefault(), void save())} />
            <div className="sb-readout">
              {words.toLocaleString(prefs.locale)} words, {draft.text.length.toLocaleString(prefs.locale)} characters · {piece.lang ?? ""} · {dirty.includes("text") ? "not saved" : `saved, last change ${piece.updated ?? "–"}`}
              <span className="kit-grow" />
              <button className="sb-ref" onClick={() => void runCheck()}>
                Check sources and numbers
              </button>
            </div>
            {check && check.id === piece.id && (
              <div className="sb-checks">
                {check.errors.map((x) => (
                  <p key={x} className="sb-notice" data-tone="bad">
                    Error: {x}
                  </p>
                ))}
                {check.warnings.map((x) => (
                  <p key={x} className="sb-notice" data-tone="warn">
                    Warning: {x}
                  </p>
                ))}
                {check.errors.length + check.warnings.length === 0 && <p className="sb-notice">Every source and every number resolves.</p>}
                {dirty.includes("text") && <p className="sb-notice wb-dim">The check read the saved text, not what you typed since.</p>}
              </div>
            )}
          </>
        )
      ) : state.view === "card" ? (
        <div className="sb-scroll">
          <form className="wb-form sb-pad" onSubmit={(e) => (e.preventDefault(), void save())}>
            {field("title", "Title", <input id="piece-title" className="wb-input" value={draft.title} onChange={(e) => edit({ title: e.target.value })} />)}
            {field("kind", "Kind", <input id="piece-kind" className="wb-input" value={draft.kind} placeholder="post, note, idea, briefing" onChange={(e) => edit({ kind: e.target.value })} />)}
            {field("channel", "Channel", <input id="piece-channel" className="wb-input" value={draft.channel} placeholder="linkedin, newsletter, internal" onChange={(e) => edit({ channel: e.target.value })} />)}
            {field("template", "Template", <Select id="piece-template" value={draft.template || "-"} options={[{ value: "-", label: "None chosen" }, ...data.templates.map((t) => ({ value: t.id, label: t.id, hint: t.kind }))]} onChange={(v) => edit({ template: v === "-" ? "" : v })} />)}
            {field("note", "Notes", <textarea id="piece-note" className="wb-input sb-area" value={draft.note} placeholder="Audience, angle, what to keep in mind" onChange={(e) => edit({ note: e.target.value })} />)}
            {field("prompt", "Prompt", <textarea id="piece-prompt" className="wb-input sb-area" value={draft.prompt} placeholder="What an agent is asked to write" onChange={(e) => edit({ prompt: e.target.value })} />)}
          </form>
          <div className="sb-pad">
            <Section title="Decisions">
              <p className="wb-hint">These are yours. An agent that asks for one waits for your approval. Nothing here posts anywhere: scheduling records when you intend to publish, and you publish yourself.</p>
              <p className="wb-row wb-wrap">
                <button className="wb-button" disabled={piece.status === "review"} onClick={async () => say(await wb.run("piece.update", { project, id: piece.id, patch: { status: "review" } }), "In review.")}>
                  Ready for review
                </button>
                <button className="wb-button" disabled={piece.status === "approved"} onClick={() => void decide("approved")}>
                  Approve
                </button>
                <button className="wb-button" disabled={piece.status === "published"} onClick={() => void decide("published")}>
                  Mark as published
                </button>
              </p>
              <p className="wb-row wb-wrap">
                <input className="wb-input sb-when" value={state.when} placeholder="2026-11-20 08:30" aria-label="Date and time to publish" aria-invalid={Boolean(slot) && !STAMP.test(slot)} onChange={(e) => setState({ ...state, when: e.target.value })} />
                <button className="wb-button" onClick={() => setState({ ...state, when: nextSlot(data.pieces, weekdays(days), time) })} title={`The next of your usual posting days (${days}) at ${time} with nothing else scheduled`}>
                  Next free slot
                </button>
                <button className="wb-button" disabled={!STAMP.test(slot)} onClick={() => void decide("scheduled", { scheduled_at: slot })}>
                  Schedule
                </button>
              </p>
              {slot && !STAMP.test(slot) && <p className="wb-control-error">Write the date and time as 2026-11-20 08:30.</p>}
            </Section>
            <KeyValue
              items={[
                { label: "Folder", value: `pieces/${piece.id}` },
                { label: "Created", value: piece.created ?? "–" },
                { label: "Updated", value: piece.updated ?? "–" },
                piece.published_at ? { label: "Published", value: when(piece.published_at) } : null,
                piece.url ? { label: "Where", value: piece.url } : null,
                piece.data_files.length ? { label: "Content files", value: piece.data_files.join(", ") } : null,
              ]}
            />
            <p>
              <ConfirmButton confirm={confirmDelete} tone="warn" question="Delete this piece?" onConfirm={() => void wb.run("piece.delete", { project, id: piece.id }).then(forget)}>
                Delete piece
              </ConfirmButton>
            </p>
          </div>
        </div>
      ) : (
        <div className="sb-scroll sb-pad">
          <p className="wb-row wb-wrap">
            <Select aria-label="Template" value={template} placeholder="Choose a template" options={data.templates.map((t) => ({ value: t.id, label: t.id, hint: t.kind, group: t.origin }))} onChange={(renderWith) => setState({ ...state, renderWith })} />
            <ConfirmButton confirm={confirmRender} question="Rewrite this render?" disabled={!template} onConfirm={() => void render()} title="Writes pieces/<id>/render/<template>/ (sb render)">
              Render
            </ConfirmButton>
            {dirty.length > 0 && <span className="wb-warn">Save first: a render reads the saved files.</span>}
            <span className="sb-grow" />
            <button
              className="wb-button"
              disabled={!exportTo || piece.renders.length === 0}
              title={exportTo ? `Copies the newest render of every template, the post text and the alt texts to ${exportTo} (sb piece export)` : "Set export.dir in project.yaml to export (e.g. a shared marketing folder)"}
              onClick={() => void exportFiles()}
            >
              Export to folder
            </button>
          </p>
          {piece.renders.length === 0 && <p className="wb-hint">Not rendered yet. A render turns the text into a format: plain text for a post, Markdown, and whatever the installed plugins offer (Word, slides).</p>}
          {piece.renders.map((r) => (
            <Section key={r.template} title={r.template} aside={<span className="wb-dim">{r.kind} · design {r.design} · {when(r.at)}</span>}>
              {r.stale.length > 0 && (
                <p className="sb-notice" data-tone="warn">
                  Shows older values of {r.stale.slice(0, 6).join(", ")}: render again.
                </p>
              )}
              <ul className="sb-files">
                {r.files.map((file) => (
                  <li key={file}>
                    <a href={paths.raw(project, file)} target="_blank" rel="noreferrer">
                      {file.split("/").pop()}
                    </a>{" "}
                    <button className="sb-ref" onClick={() => copyText(file)}>
                      copy path
                    </button>
                  </li>
                ))}
              </ul>
              <div className="sb-thumbs">
                {r.files.filter((f) => /\.(png|jpe?g|svg)$/i.test(f)).map((file) => (
                  <a key={file} href={paths.raw(project, file)} target="_blank" rel="noreferrer" title={file.split("/").pop()}>
                    <img src={paths.raw(project, file)} alt={file.split("/").pop()} loading="lazy" />
                  </a>
                ))}
              </div>
            </Section>
          ))}
          <p className="wb-hint">
            Formats: <StatusPill>{[...new Set(data.templates.map((t) => t.kind))].join(", ") || "none"}</StatusPill>. Templates are registered on the command line (Assets panel).
          </p>
        </div>
      )}
    </div>
  );
}

export const pieceTool = defineTool<State>({
  id: "piece",
  title: "Piece",
  glyph: "✎",
  category: "Pieces",
  version: 1,
  stateSchema,
  defaultState: () => ({ view: "text", drafts: {}, when: "", renderWith: "" }),
  links: ["project", "piece"],
  component: PiecePanel,
  describe: (state, { links }) => {
    const { project, data } = piecesOf(links);
    if (!data) return { project, loaded: false };
    const piece = pickPiece(data, links.piece);
    if (!piece) return { project, piece: null };
    const draft = state.drafts[`${project}/${piece.id}`];
    return {
      project,
      view: state.view,
      note: "The saved piece. Change it with piece.update { project, id, patch: { text, title, … } }. Notation in the text: {{result:key}} for a recorded number, [@W-0001] or [@citekey] for a source. A template that reads a data file (slides.yaml for slides and PowerPoint): piece.format { project, id } returns its exact format and the current content; write the whole file with piece.data { project, id, name, text }.",
      piece: pieceCard(piece, prefs.textCap),
      unsaved_changes_in_this_panel: draft ? changed(piece, draft) : [],
    };
  },
});
