import { defineTool } from "@werkbank/framework";
import { Suspense, lazy } from "react";
import { z } from "zod";
import { api, paths } from "../data/api";
import { prefs } from "../prefs";
import { Blank } from "./lib";

/**
 * How to work with Sourcebound: example prompts to give an agent (start a study or a desk, make a
 * post from a file, change a slide) and the commands. The pages are Markdown served by `sb ui`:
 * Sourcebound's own, then those an installed pack brought (docs/<id>.md in the pack). A code block
 * marked `prompt` is shown with a copy button.
 */

export interface DocPage {
  id: string;
  title: string;
  origin: "sourcebound" | "pack";
  order: number;
  text: string;
}

const stateSchema = z.object({ page: z.string().max(80).nullable() });
export type State = z.infer<typeof stateSchema>;

const View = lazy(() => import("./documentation.view"));

export const documentationTool = defineTool<State>({
  id: "documentation",
  title: "Documentation",
  glyph: "?",
  category: "Help",
  version: 1,
  stateSchema,
  defaultState: () => ({ page: null }),
  links: [],
  component: () => (
    <Suspense fallback={<Blank>Loading…</Blank>}>
      <View />
    </Suspense>
  ),
  describe: (state) => {
    const pages = api.peek<{ pages: DocPage[] }>(paths.docs)?.pages;
    if (!pages) return { loaded: false };
    const page = pages.find((p) => p.id === state.page) ?? pages[0];
    return {
      pages: pages.map((p) => ({ id: p.id, title: p.title, from: p.origin === "pack" ? "an installed pack" : "Sourcebound" })),
      showing: page ? { id: page.id, title: page.title, text: page.text.slice(0, prefs.textCap) } : null,
      note: "Example prompts and commands. Code blocks marked `prompt` are prompts a person copies to an agent.",
    };
  },
});
