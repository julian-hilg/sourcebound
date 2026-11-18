import { Select, defineTool, useLink, useSetting, useWerkbank } from "@werkbank/framework";
import { useState } from "react";
import { z } from "zod";
import { api, paths, useApi, type Piece, type PieceRender } from "../data/api";
import { ConfirmButton, EmptyState, SlideGrid, type SlideImage } from "../kit";
import { prefs } from "../prefs";
import { usePanelState, when } from "./lib";
import { pickPiece, piecesOf, usePieces } from "./pieces.lib";

/**
 * A piece's slides, large and numbered, to work on one slide at a time with a person or the
 * assistant ("slide 3: a shorter title"). What is on screen is the newest render of a slides or
 * PowerPoint template; the content behind it is the piece's slides.yaml, which `describe` hands to
 * an agent together with the selected slide. Changing a slide is piece.data, then piece.render.
 */

const stateSchema = z.object({ template: z.string().max(60).nullable(), slide: z.number().int().min(1).max(200).nullable() });
type State = z.infer<typeof stateSchema>;

interface PreviewFile {
  slides?: { file?: string | null; title?: string; alt?: string }[];
}

const DECK_KINDS = new Set(["slides", "pptx"]);
const folderOf = (r: PieceRender) => r.files[0]?.split("/").slice(0, -1).join("/") ?? "";
const previewOf = (r: PieceRender | undefined) => r?.files.find((f) => f.endsWith("/preview.json"));
/** The render to show: the chosen template, else the piece's template, else the newest slides render. */
const choose = (piece: Piece, wanted: string | null) => {
  const decks = piece.renders.filter((r) => r.kind === "slides" && previewOf(r));
  return decks.find((r) => r.template === wanted) ?? decks.find((r) => r.template === piece.template) ?? [...decks].sort((a, b) => b.at.localeCompare(a.at))[0];
};

function SlidesPanel() {
  const wb = useWerkbank();
  const { project, data, error } = usePieces();
  const [state, setState] = usePanelState<State>();
  const [linked] = useLink<string | null>("piece");
  const [confirmRender] = useSetting<boolean>("confirm.render");
  const [message, setMessage] = useState<{ tone?: "bad"; text: string } | null>(null);
  const piece = pickPiece(data, linked);
  const render = piece ? choose(piece, state.template) : undefined;
  const previewPath = previewOf(render);
  const preview = useApi<{ text: string }>(project && previewPath ? paths.file(project, previewPath) : null);
  if (!data || !project) return <EmptyState>{error ?? "Loading…"}</EmptyState>;
  if (!piece) return <EmptyState>No piece selected.</EmptyState>;
  let described: PreviewFile = {};
  try {
    described = preview.data ? (JSON.parse(preview.data.text) as PreviewFile) : {};
  } catch {
    described = {};
  }
  const slides: SlideImage[] = render
    ? (described.slides ?? []).filter((s) => s.file).map((s, i) => ({ src: `${paths.raw(project, `${folderOf(render)}/${s.file}`)}&v=${encodeURIComponent(render.at)}`, title: s.title || `Slide ${i + 1}`, alt: s.alt }))
    : [];
  const deckTemplates = data.templates.filter((t) => DECK_KINDS.has(t.kind));
  const template = render?.template ?? (piece.template && deckTemplates.some((t) => t.id === piece.template) ? piece.template : deckTemplates[0]?.id) ?? "";
  const renderNow = async () => {
    const result = await wb.run("piece.render", { project, id: piece.id, template });
    setMessage(result.ok ? { text: `Rendered with ${template}.` } : { tone: "bad", text: result.error });
  };
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Slides</strong>
        <span>{slides.length ? `${slides.length} slides` : "none rendered"}</span>
        {render && <span className="wb-dim">rendered {when(render.at)}</span>}
        <span className="sb-grow" />
        <Select aria-label="Template" value={template} placeholder="Template" options={deckTemplates.map((t) => ({ value: t.id, label: t.id, hint: t.kind }))} onChange={(t) => setState({ ...state, template: t })} />
        <ConfirmButton confirm={confirmRender} question="Rewrite this render?" disabled={!template} onConfirm={() => void renderNow()} title="Render the slides again from slides.yaml (sb render)">
          Render
        </ConfirmButton>
      </div>
      {message && (
        <p className="sb-notice" data-tone={message.tone === "bad" ? "warn" : undefined}>
          {message.text}
        </p>
      )}
      {render && (render.changed_since ?? []).some((f) => f !== "text.md") && (
        <p className="sb-notice" data-tone="warn">
          Changed after this render: {(render.changed_since ?? []).filter((f) => f !== "text.md").join(", ")}. The slides show the older version: render again.
        </p>
      )}
      {render && render.stale.length > 0 && (
        <p className="sb-notice" data-tone="warn">
          Shows older values of {render.stale.slice(0, 5).join(", ")}: render again.
        </p>
      )}
      <div className="sb-scroll sb-desk">
        {slides.length ? (
          <SlideGrid slides={slides} selected={state.slide} onSelect={(slide) => setState({ ...state, slide: state.slide === slide ? null : slide })} />
        ) : (
          <EmptyState>
            {piece.data?.slides
              ? "slides.yaml is written but not rendered yet: Render, or ask the assistant to render it."
              : "This piece has no slides yet. Ask the assistant, e.g. “make three slides from the text”, or write pieces/<id>/slides.yaml."}
          </EmptyState>
        )}
      </div>
      <p className="wb-hint sb-pad">
        Select a slide and tell the assistant what to change, e.g. “slide {state.slide ?? 3}: shorter title”. It edits slides.yaml and renders again; the slides here update by
        themselves. Nothing is posted from this app.
      </p>
    </div>
  );
}

export const slidesTool = defineTool<State>({
  id: "slides",
  title: "Slides",
  glyph: "▤",
  category: "Pieces",
  version: 1,
  stateSchema,
  defaultState: () => ({ template: null, slide: null }),
  links: ["project", "piece"],
  component: SlidesPanel,
  describe: (state, { links }) => {
    const { project, data } = piecesOf(links);
    const piece = pickPiece(data, links.piece);
    if (!data || !project || !piece) return { project, loaded: Boolean(data), piece: null };
    const render = choose(piece, state.template);
    const previewPath = previewOf(render);
    let titles: string[] = [];
    try {
      const raw = previewPath ? api.peek<{ text: string }>(paths.file(project, previewPath))?.text : undefined;
      titles = raw ? ((JSON.parse(raw) as PreviewFile).slides ?? []).map((s) => s.title ?? "") : [];
    } catch {
      titles = [];
    }
    const deck = piece.data?.slides ?? null;
    return {
      project,
      piece: piece.id,
      title: piece.title,
      template: render?.template ?? piece.template ?? null,
      render: render ? { at: render.at, notes: render.notes ?? [], shows_older_values_of: render.stale, changed_since: render.changed_since ?? [], files: render.files } : null,
      slides: titles.map((title, i) => ({ n: i + 1, title })),
      selected: state.slide ? { n: state.slide, title: titles[state.slide - 1] ?? null } : null,
      slides_yaml: deck ? deck.slice(0, prefs.textCap) : null,
      how_to_change:
        "Slide n is the n-th entry of `slides:` in slides.yaml (with a cover, slide 1 is the cover). To change slides: piece.format { project, id } for the format, then piece.data { project, id, name: 'slides', text: <the whole new file> }, then piece.check, then piece.render { project, id, template }. Keep every number cited (source: line) or a {{result:key}}; do not change the template or the design. Say in one line what you changed.",
    };
  },
});
