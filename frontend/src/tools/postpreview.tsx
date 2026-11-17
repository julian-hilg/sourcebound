import { Select, defineTool, useLink, useSetting } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type Piece, type PieceRender } from "../data/api";
import { EmptyState, PostPreview, type PreviewImage } from "../kit";
import { usePanelState, when } from "./lib";
import { pickPiece, piecesOf, usePieces } from "./pieces.lib";

/**
 * How a piece will look as a post in a feed. It shows a render, never the draft: what is on
 * screen is what the files hold. A render that brings a `preview.json` (the posts plugin
 * writes one) is shown as it describes itself; otherwise the preview is built from the
 * rendered text and any images. Nothing is posted from here.
 */

const stateSchema = z.object({ render: z.string().max(60).nullable() });
type State = z.infer<typeof stateSchema>;

interface TextFile {
  text: string;
}
/** What a render may say about itself. Every field is optional: older plugins write fewer. */
interface PreviewFile {
  text?: string;
  characters?: number;
  limit?: number;
  document_title?: string;
  title?: string;
  slides?: { file?: string; alt?: string }[];
  hashtags?: string[];
  warnings?: string[];
}

const IMAGE = /\.(png|jpe?g|svg)$/i;
const folderOf = (r: PieceRender) => r.files[0]?.split("/").slice(0, -1).join("/") ?? "";
const fileOf = (r: PieceRender | undefined, test: (name: string) => boolean) => r?.files.find((f) => test(f.split("/").pop()!));
/** The render to preview: the chosen one, else one that describes itself, else plain text, else the newest. */
const choose = (piece: Piece, wanted: string | null) =>
  piece.renders.find((r) => r.template === wanted) ?? piece.renders.find((r) => fileOf(r, (n) => n === "preview.json")) ?? piece.renders.find((r) => r.kind === "text") ?? piece.renders[0];
const plain = (markdown: string) => markdown.replace(/^#{1,6}\s+/gm, "").replace(/\*\*(.+?)\*\*/g, "$1").trim();

function PostPreviewPanel() {
  const { project, data, error } = usePieces();
  const [state, setState] = usePanelState<State>();
  const [linked] = useLink<string | null>("piece");
  const [author] = useSetting<string>("preview.author");
  const [headline] = useSetting<string>("preview.headline");
  const [lines] = useSetting<number>("preview.lines");
  const [width] = useSetting<string>("preview.width");
  const piece = pickPiece(data, linked);
  const render = piece ? choose(piece, state.render) : undefined;
  const previewPath = fileOf(render, (n) => n === "preview.json");
  const textPath = fileOf(render, (n) => n.endsWith(".txt"));
  const preview = useApi<TextFile>(project && previewPath ? paths.file(project, previewPath) : null);
  const text = useApi<TextFile>(project && textPath ? paths.file(project, textPath) : null);
  if (!data || !project) return <EmptyState>{error ?? "Loading…"}</EmptyState>;
  if (!piece) return <EmptyState>No piece selected.</EmptyState>;
  let described: PreviewFile = {};
  try {
    described = preview.data ? (JSON.parse(preview.data.text) as PreviewFile) : {};
  } catch {
    described = { warnings: ["preview.json of this render cannot be read."] };
  }
  const body = described.text ?? text.data?.text?.trim() ?? plain(piece.text);
  // Images: the ones the render names, else every image of the chosen render, else of any render.
  const named = (described.slides ?? []).filter((s) => s.file).map((s): PreviewImage => ({ src: paths.raw(project, `${folderOf(render!)}/${s.file}`), alt: s.alt ?? s.file! }));
  const found = (render?.files.filter((f) => IMAGE.test(f)) ?? []).concat(render && render.files.some((f) => IMAGE.test(f)) ? [] : piece.renders.flatMap((r) => r.files.filter((f) => IMAGE.test(f))));
  const images = named.length ? named : [...new Set(found)].sort().map((f): PreviewImage => ({ src: paths.raw(project, f), alt: f.split("/").pop()! }));
  const fromDraft = !render || (!described.text && !text.data);
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Preview</strong>
        {piece.renders.length > 0 ? (
          <Select aria-label="Render" value={render?.template ?? ""} options={piece.renders.map((r) => ({ value: r.template, label: r.template, hint: r.kind }))} onChange={(r) => setState({ render: r })} />
        ) : (
          <span>not rendered</span>
        )}
        {render && <span>rendered {when(render.at)}</span>}
        <span className="kit-grow" />
        <span className="wb-badge" title="Nothing is posted from this app. You publish yourself; the status only records it.">
          preview only
        </span>
      </div>
      {fromDraft && (
        <p className="sb-notice" data-tone="warn">
          {render ? "This render has no text file: the text below is the piece's source, with its markup." : "Not rendered yet: the text below is the piece's source. Render it (Piece panel, Output) to see numbers filled in and sources listed."}
        </p>
      )}
      {render && render.stale.length > 0 && (
        <p className="sb-notice" data-tone="warn">
          This render shows older values of {render.stale.slice(0, 5).join(", ")}: render again.
        </p>
      )}
      {[...(described.warnings ?? []), ...(render?.notes ?? [])].map((w) => (
        <p key={w} className="sb-notice" data-tone="warn">
          {w}
        </p>
      ))}
      <div className="sb-scroll sb-desk">
        <PostPreview
          author={data.preview?.author || author || "Your name"}
          headline={data.preview?.author ? data.preview.headline : headline || (author ? undefined : "Set the name under Settings → Post preview, or preview: author in project.yaml")}
          meta={piece.status === "scheduled" && piece.scheduled_at ? `Scheduled for ${when(piece.scheduled_at)}` : piece.status === "published" ? `Published ${when(piece.published_at)}` : `${piece.status ?? "draft"}${piece.channel ? ` · ${piece.channel}` : ""}`}
          text={body}
          visibleLines={lines}
          images={images}
          documentTitle={described.document_title ?? described.title}
          characters={described.characters ?? body.length}
          limit={described.limit ?? (piece.channel === "linkedin" ? 3000 : undefined)}
          width={width === "phone" ? 360 : 540}
        />
      </div>
    </div>
  );
}

export const postPreviewTool = defineTool<State>({
  id: "postpreview",
  title: "Post preview",
  glyph: "▣",
  category: "Pieces",
  version: 1,
  stateSchema,
  defaultState: () => ({ render: null }),
  links: ["project", "piece"],
  component: PostPreviewPanel,
  describe: (state, { links }) => {
    const { project, data } = piecesOf(links);
    const piece = pickPiece(data, links.piece);
    if (!data || !project || !piece) return { project, loaded: Boolean(data), piece: null };
    const render = choose(piece, state.render);
    const textPath = fileOf(render, (n) => n.endsWith(".txt"));
    const text = textPath ? api.peek<TextFile>(paths.file(project, textPath))?.text : undefined;
    return {
      project,
      piece: piece.id,
      status: piece.status,
      scheduled_at: piece.scheduled_at ?? null,
      render: render ? { template: render.template, kind: render.kind, at: render.at, files: render.files, shows_older_values_of: render.stale } : null,
      note: "A preview of a render. Nothing is posted from this app.",
      text: (text ?? plain(piece.text)).slice(0, 6000),
      characters: (text ?? plain(piece.text)).length,
      images: piece.renders.flatMap((r) => r.files.filter((f) => IMAGE.test(f))),
    };
  },
});
