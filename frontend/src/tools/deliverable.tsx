import { defineTool } from "@werkbank/framework";
import { Suspense, lazy } from "react";
import { z } from "zod";
import { api, paths, type Handover } from "../data/api";
import { prefs } from "../prefs";
import { parse } from "../reader/markup";
import { Blank, projectOf } from "./lib";

/**
 * The deliverable reader: a study's paper, note or report rendered from the format-neutral
 * handover (`sb handover`), in a layout close to the LaTeX one, so it can be read without a
 * TeX installation. The view brings the Markdown and mathematics renderers and loads on demand.
 */

export const stateSchema = z.object({ deliverable: z.string().max(80).nullable() });
export type State = z.infer<typeof stateSchema>;

const View = lazy(() => import("./deliverable.view"));

export const chosen = (handover: Handover, state: State) =>
  handover.handover?.deliverables.find((d) => d.name === state.deliverable) ?? handover.handover?.deliverables[0];

export const deliverableTool = defineTool<State>({
  id: "deliverable",
  title: "Deliverable",
  glyph: "❡",
  category: "Deliverables",
  version: 1,
  stateSchema,
  defaultState: () => ({ deliverable: null }),
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
    const paper = parse(d, h);
    const results = h.results ?? {};
    const text = d.sections
      .map((s) => (h.sections?.[s.file] ?? "").replace(/\{\{result:([^}]+)\}\}/g, (_m, key: string) => String(results[key.trim()]?.display ?? `?${key}`)))
      .join("\n\n");
    return {
      project: id,
      deliverable: d.name,
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
