import { defineTool } from "@werkbank/framework";
import { Suspense, lazy } from "react";
import { z } from "zod";
import { api, paths, type DeliverableFolder, type Detail, type Handover, type PieceRender } from "../data/api";
import { prefs } from "../prefs";
import { parse } from "../reader/markup";
import { Blank, projectOf } from "./lib";

/**
 * The deliverable reader: a study's paper, note or report rendered from the format-neutral
 * handover (`sb handover`), in a layout close to the LaTeX one, so it can be read without a
 * TeX installation. The view brings the Markdown and mathematics renderers and loads on demand.
 */

export const stateSchema = z.object({
  deliverable: z.string().max(80).nullable(),
  /** What is shown: "text" (the reader), "pdf" (the LaTeX build) or "render:<template>" (a Word, slides or other render). */
  view: z.string().max(120).nullable().optional(),
});
export type State = z.infer<typeof stateSchema>;

const View = lazy(() => import("./deliverable.view"));

export const chosen = (handover: Handover, state: State) =>
  handover.handover?.deliverables.find((d) => d.name === state.deliverable) ?? handover.handover?.deliverables[0];

/** How the kind of a render is named. */
export const FORMAT_NAMES: Record<string, string> = { docx: "Word", pptx: "PowerPoint", slides: "Slides", markdown: "Markdown", text: "Text" };

/** One way to look at a deliverable: the reader, the LaTeX PDF, or one render per template. */
export interface Format {
  value: string;
  label: string;
  kind: "text" | "pdf" | "render";
  /** The file shown, relative to the project. */
  file?: string;
  render?: PieceRender;
}

export function formatsOf(folder: DeliverableFolder | undefined): Format[] {
  const main = (r: PieceRender) => r.files.find((f) => /\.(docx|pptx|pdf)$/i.test(f)) ?? r.files[0];
  return [
    { value: "text", label: "Text", kind: "text" },
    ...(folder?.pdf ? [{ value: "pdf", label: "PDF", kind: "pdf" as const, file: folder.pdf }] : []),
    ...(folder?.renders ?? []).map((r) => ({ value: `render:${r.template}`, label: `${FORMAT_NAMES[r.kind] ?? r.kind} · ${r.template}`, kind: "render" as const, file: main(r), render: r })),
  ];
}

export const folderOf = (detail: Detail | undefined, name: string | undefined) => detail?.deliverable_folders.find((f) => f.name === name);

export const deliverableTool = defineTool<State>({
  id: "deliverable",
  title: "Deliverable",
  glyph: "❡",
  category: "Deliverables",
  version: 1,
  stateSchema,
  defaultState: () => ({ deliverable: null, view: "text" }),
  links: ["project", "result"],
  component: () => (
    <Suspense fallback={<Blank>Loading the reader…</Blank>}>
      <View />
    </Suspense>
  ),
  describe: (state, { links }) => {
    const id = projectOf(links);
    const h = id ? api.peek<Handover>(paths.handover(id)) : undefined;
    if (!h) return { project: id, loaded: false };
    if (!h.built || !h.handover) return { project: id, handover: "not built", note: "Build it with the sb.handover command (it writes dist/handover in the project, so it needs the person's approval)." };
    const d = chosen(h, state);
    if (!d) return { project: id, handover: { built_at: h.at, stale: h.stale }, deliverables: [], note: "The project has no deliverable folder yet." };
    const formats = formatsOf(folderOf(id ? api.peek<Detail>(paths.project(id)) : undefined, d.name));
    const shown = formats.find((x) => x.value === (state.view ?? "text")) ?? formats[0]!;
    const formatList = formats.map((x) => ({ view: x.value, label: x.label, file: x.file ?? null, rendered_at: x.render?.at ?? null, numbers_changed_since: x.render?.stale ?? [] }));
    if (shown.kind !== "text")
      return {
        project: id,
        deliverable: d.name,
        showing: shown.label,
        file: shown.file,
        formats: formatList,
        note: `The panel shows ${shown.file} as the page renders it. Switch with the panel state's view (text, pdf, render:<template>); render again with deliverable.render.`,
      };
    const paper = parse(d, h);
    const results = h.results ?? {};
    const text = d.sections
      .map((s) => (h.sections?.[s.file] ?? "").replace(/\{\{result:([^}]+)\}\}/g, (_m, key: string) => String(results[key.trim()]?.display ?? `?${key}`)))
      .join("\n\n");
    return {
      project: id,
      deliverable: d.name,
      showing: "Text",
      formats: formatList,
      available: h.handover.deliverables.map((x) => x.name),
      title: d.title ?? h.handover.title,
      subtitle: d.subtitle,
      date: d.date,
      handover: { built_at: h.at, stale: h.stale, changed_since: h.changed_since, commit: h.handover.commit },
      problems: [...h.handover.problems, ...paper.missing.map((k) => `result ${k} is used but not recorded`)],
      latex_commands_not_converted: d.unconverted,
      sections_edited_by_a_person: h.edited_by_person,
      words: paper.words,
      outline: paper.outline.map((o) => `${o.number} ${o.text}`),
      sections: d.sections.map((s) => ({ file: s.file, source: s.source, appendix: s.appendix, results: s.results, citations: s.citations, tables: s.tables, figures: s.figures })),
      references: paper.cited,
      note: "The text is the handover's Markdown with recorded numbers filled in; citations are [@key]." + (text.length > prefs.textCap ? ` Cut after ${prefs.textCap} characters.` : ""),
      text: text.slice(0, prefs.textCap),
    };
  },
});
