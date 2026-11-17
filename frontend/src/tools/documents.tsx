import { Markdown, Select, defineTool } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type Detail, type DocumentFile } from "../data/api";
import { prefs } from "../prefs";
import { Blank, downloadText, projectOf, useDetail, usePanelState, when } from "./lib";

/**
 * A reader for a project's Markdown files. Two tools share it: Documents (brief, landscape,
 * notes, log) and Reviews (verification and referee reports).
 */

const stateSchema = z.object({ path: z.string().max(300).nullable() });
type State = z.infer<typeof stateSchema>;
interface TextFile {
  path: string;
  changed: string;
  text: string;
}

const offered = (d: Detail, reviews: boolean) => d.documents.filter((f) => (f.group === "Reviews") === reviews);
const chosen = (files: DocumentFile[], state: State) => files.find((f) => f.path === state.path) ?? files[0];

function reader(reviews: boolean) {
  return function Documents() {
    const { id, detail: d, blank } = useDetail();
    const [state, setState] = usePanelState<State>();
    const files = d ? offered(d, reviews) : [];
    const file = chosen(files, state);
    const text = useApi<TextFile>(id && file ? paths.file(id, file.path) : null);
    if (!d || !id) return blank;
    return (
      <div className="sb-panel">
        <div className="wb-toolhead">
          {file ? (
            <Select
              value={file.path}
              aria-label={reviews ? "Review" : "Document"}
              options={files.map((f) => ({ value: f.path, label: f.name, group: reviews ? undefined : f.group, hint: when(f.changed, false) }))}
              onChange={(path) => setState({ path })}
            />
          ) : (
            <strong>{reviews ? "Reviews" : "Documents"}</strong>
          )}
          {file && <span>{file.path}</span>}
          <span className="sb-grow" />
          {text.data && (
            <button className="wb-button" onClick={() => downloadText(file!.path.split("/").pop()!, text.data!.text, "text/markdown")}>
              .md
            </button>
          )}
        </div>
        <div className="sb-scroll">
          {!file ? (
            <Blank>{reviews ? "No review yet. The verifier and the referee write their reports into reviews/." : "No document yet. A study starts with research/brief.md."}</Blank>
          ) : text.data ? (
            <article className="sb-doc">
              <Markdown text={text.data.text} />
            </article>
          ) : (
            <Blank>{text.error ?? "Loading…"}</Blank>
          )}
        </div>
      </div>
    );
  };
}

const describe = (reviews: boolean) => (state: State, { links }: { links: Record<string, unknown> }) => {
  const id = projectOf(links);
  const d = id ? api.peek<Detail>(paths.project(id)) : undefined;
  if (!d || !id) return { project: id, loaded: false };
  const files = offered(d, reviews);
  const file = chosen(files, state);
  const text = file ? api.peek<TextFile>(paths.file(id, file.path))?.text : undefined;
  return {
    project: id,
    open: file?.path ?? null,
    available: files.map((f) => ({ path: f.path, group: f.group, changed: f.changed, bytes: f.bytes })),
    note: "Open another file with panel.setState { path }." + (text && text.length > prefs.textCap ? ` The text is cut after ${prefs.textCap} characters.` : ""),
    markdown: text?.slice(0, prefs.textCap),
  };
};

export const documentsTool = defineTool<State>({
  id: "documents",
  title: "Documents",
  glyph: "¶",
  category: "Study",
  version: 1,
  stateSchema,
  defaultState: () => ({ path: null }),
  links: ["project"],
  component: reader(false),
  describe: describe(false),
});

export const reviewsTool = defineTool<State>({
  id: "reviews",
  title: "Reviews",
  glyph: "✓",
  category: "Evidence",
  version: 1,
  stateSchema,
  defaultState: () => ({ path: null }),
  links: ["project"],
  component: reader(true),
  describe: describe(true),
});
