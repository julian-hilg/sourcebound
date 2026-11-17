import type { Handover, HandoverDeliverable, Reference, WebSource } from "../data/api";

/**
 * Turns the handover's Markdown into what the reader draws: numbered blocks, and prose in which
 * recorded numbers, citations and cross-references have become links the reader understands.
 * No React here; `document.test`-style checks can run it on plain strings.
 *
 * Handover notation (see `sb handover`): {{result:key}}, [@key; @other, p. 3], {{table:name}},
 * ![caption](figures/name.pdf){#label}, {{ref:label}}, `: caption {#label}`, $…$ and $$…$$.
 */

export type Block =
  | { type: "heading"; level: 1 | 2 | 3; text: string; number: string; label: string | null; anchor: string }
  | { type: "figure"; file: string; caption: string; number: number; label: string | null; anchor: string }
  | { type: "table"; name: string | null; markdown: string | null; caption: string; note: string; number: number; label: string | null; anchor: string }
  | { type: "prose"; markdown: string };

export interface Section {
  file: string;
  source: string;
  appendix: boolean;
  abstract: boolean;
  blocks: Block[];
}

export interface Paper {
  sections: Section[];
  outline: { anchor: string; number: string; text: string; level: number }[];
  /** Cited keys in the order of the reference list. */
  cited: string[];
  footnotes: string[];
  /** Result keys the text uses that were never recorded. */
  missing: string[];
  words: number;
}

interface Target {
  name: string;
  number: string;
  anchor: string;
}

// ---- citations -----------------------------------------------------------------

/** The family name; an institution (its words joined by no-break spaces) stays whole. */
const surname = (name: string) => (name.includes(",") ? name.split(",")[0]! : name.trim().split(" ").pop()!).trim();

/** "Lu et al." from a BibLaTeX author field ("Last, First and Last, First"). */
export function authors(field: string | undefined): string {
  const names = (field ?? "").split(/\s+and\s+/).map((n) => n.trim()).filter(Boolean);
  if (names.length === 0) return "";
  if (names.length === 1) return surname(names[0]!);
  if (names.length === 2) return `${surname(names[0]!)} and ${surname(names[1]!)}`;
  return `${surname(names[0]!)} et al.`;
}

export interface Sources {
  references: Record<string, Reference>;
  web: Record<string, WebSource>;
}

/** Who and when, for an author-year citation; null if the key is neither in the bibliography nor a web source. */
export function citeParts(key: string, sources: Sources): { who: string; year: string } | null {
  const ref = sources.references[key];
  if (ref) return { who: authors(ref.author ?? ref.editor) || ref.title || key, year: ref.year || "n.d." };
  const web = sources.web[key];
  if (web) return { who: (web.author ?? "").replace(/[{}]/g, "") || web.publisher || web.title || key, year: (web.date ?? "").slice(0, 4) || "n.d." };
  return null;
}

/** One entry of the reference list, as Markdown. */
export function referenceLine(key: string, sources: Sources): string {
  const ref = sources.references[key];
  if (ref) {
    const names = (ref.author ?? ref.editor ?? "").split(/\s+and\s+/).filter(Boolean);
    const who = names.length > 6 ? `${names.slice(0, 6).join("; ")} et al.` : names.join("; ");
    const where = ref.journaltitle ?? ref.journal ?? ref.booktitle;
    const issue = [ref.volume, ref.number ? `(${ref.number})` : ""].join("");
    const link = ref.doi ? `https://doi.org/${ref.doi}` : ref.url;
    return [
      `${who || ref.title || key} (${ref.year || "n.d."}).`,
      who && ref.title ? `${ref.title}.` : "",
      where ? `*${where}*${issue ? ` ${issue}` : ""}${ref.pages ? `, ${ref.pages}` : ""}.` : (ref.publisher ?? ref.institution) ? `${ref.publisher ?? ref.institution}.` : "",
      link ? `<${link}>` : "",
    ].filter(Boolean).join(" ");
  }
  const web = sources.web[key];
  if (web) {
    const parts = citeParts(key, sources)!;
    return [`${parts.who} (${parts.year}).`, web.title ? `${web.title}.` : "", web.url ? `<${web.url}>` : "", web.accessed ? `Archived ${web.accessed.slice(0, 10)} (${key}).` : `(${key}).`].filter(Boolean).join(" ");
  }
  return `${key}: not in references.bib and not a web source of this project.`;
}

// ---- inline --------------------------------------------------------------------

const escape = (text: string) => text.replace(/([\\[\]*_`<>])/g, "\\$1");
const PROTECTED = /(```[\s\S]*?```|`[^`\n]*`|\$\$[\s\S]*?\$\$|(?<![\\$])\$(?!\s)[^$\n]*?(?<![\\\s])\$)/g;
const CITE_KEY = /(?<![\w@])@([A-Za-z][\w:.-]*\w)/g;

interface Context {
  results: NonNullable<Handover["results"]>;
  sources: Sources;
  targets: Map<string, Target>;
  cited: Set<string>;
  missing: Set<string>;
  footnotes: string[];
}

/** The text between a `^[` and its matching `]`. */
function footnoteEnd(text: string, start: number): number {
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === "[") depth++;
    else if (text[i] === "]" && --depth === 0) return i;
  }
  return -1;
}

function inline(text: string, ctx: Context): string {
  // Footnotes first: their text is prose of its own.
  let out = "";
  for (let at = 0; ; ) {
    const start = text.indexOf("^[", at);
    const end = start === -1 ? -1 : footnoteEnd(text, start + 1);
    if (end === -1) {
      out += text.slice(at);
      break;
    }
    ctx.footnotes.push(inline(text.slice(start + 2, end), ctx));
    out += `${text.slice(at, start)}[${ctx.footnotes.length}](#sb-fn:${ctx.footnotes.length})`;
    at = end + 1;
  }
  const display = (key: string) => {
    const r = ctx.results[key];
    if (!r) ctx.missing.add(key);
    return r ? String(r.display) : `?${key}`;
  };
  const cite = (key: string, textual: boolean, locator = ""): string | null => {
    const parts = citeParts(key, ctx.sources);
    if (!parts) return null;
    ctx.cited.add(key);
    const label = textual ? `${parts.who} (${parts.year}${locator})` : `${parts.who} ${parts.year}${locator}`;
    return `[${escape(label)}](#sb-cite:${key})`;
  };
  return out
    .split(PROTECTED)
    .map((part, i) => {
      // Odd parts are code or mathematics: nothing becomes a link there; numbers are filled in as plain text.
      if (i % 2) return part.startsWith("```") ? part : part.replace(/\{\{result:([^}]+)\}\}/g, (_m, key: string) => display(key.trim()));
      return part
        .replace(/\{\{result:([^}]+)\}\}/g, (_m, key: string) => `[${escape(display(key.trim()))}](#sb-result:${key.trim()})`)
        .replace(/(\b(?:Section|Sections|Figure|Figures|Table|Tables|Appendix|Fig\.|Tab\.|Sec\.)[\s ]+)?\{\{ref:([^}]+)\}\}/gi, (_m, lead: string | undefined, label: string) => {
          const target = ctx.targets.get(label.trim());
          if (!target) return `${lead ?? ""}[${escape(label)}](#sb-ref:${label.trim()})`;
          return `[${escape(lead ? `${lead}${target.number}` : `${target.name} ${target.number}`)}](#sb-ref:${label.trim()})`;
        })
        .replace(/\[([^[\]]*@[A-Za-z][^[\]]*)\](?!\()/g, (whole, body: string) => {
          const items = body.split(";").map((item) => {
            const m = /^(.*?)@([A-Za-z][\w:.-]*\w)(.*)$/.exec(item.trim());
            const link = m ? cite(m[2]!, false, m[3]!.trim() ? `${m[3]!.trim().startsWith(",") ? "" : " "}${m[3]!.trim()}` : "") : null;
            return m && link ? `${m[1]}${link}` : null;
          });
          return items.every(Boolean) ? `(${items.join("; ")})` : whole;
        })
        .replace(CITE_KEY, (whole, key: string) => cite(key, true) ?? whole);
    })
    .join("");
}

// ---- blocks --------------------------------------------------------------------

/** Paragraphs of a Markdown text; a fenced code block stays one paragraph. */
function paragraphs(text: string): string[] {
  const out: string[] = [];
  let current: string[] = [];
  let fenced = false;
  const flush = () => {
    if (current.some((l) => l.trim())) out.push(current.join("\n").replace(/^\n+|\s+$/g, ""));
    current = [];
  };
  for (const line of text.split("\n")) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    if (!fenced && !line.trim()) flush();
    else current.push(line);
  }
  flush();
  return out;
}

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const isNote = (p: string | undefined): p is string => Boolean(p && /^\*[^*][\s\S]*\*$/.test(p) && !p.slice(1, -1).includes("*"));
const isPipeTable = (p: string | undefined): p is string => Boolean(p && p.startsWith("|") && /\n\|[\s:|-]+\|/.test(p));

export function parse(deliverable: HandoverDeliverable, handover: Handover): Paper {
  const texts = handover.sections ?? {};
  const targets = new Map<string, Target>();
  const sections: Section[] = [];
  const counters = [0, 0, 0];
  let top = "";
  let chapters = 0;
  let appendices = 0;
  let figures = 0;
  let tables = 0;
  const used = new Set<string>();
  const anchor = (wanted: string) => {
    let a = wanted || "block";
    for (let n = 2; used.has(a); n++) a = `${wanted}-${n}`;
    used.add(a);
    return a;
  };
  const target = (label: string | null, name: string, number: string, a: string) => label && targets.set(label, { name, number, anchor: a });

  // Pass 1: blocks and their numbers, so a reference can point forwards.
  for (const s of deliverable.sections) {
    const paras = paragraphs(texts[s.file] ?? "");
    const blocks: Block[] = [];
    const prose = (markdown: string) => {
      const last = blocks.at(-1);
      if (last?.type === "prose") last.markdown += `\n\n${markdown}`;
      else blocks.push({ type: "prose", markdown });
    };
    let abstract = false;
    for (let i = 0; i < paras.length; i++) {
      const p = paras[i]!;
      const heading = /^(#{1,3}) (.+?)(?:\s*\{#([^}]+)\})?$/.exec(p);
      const figure = /^!\[([\s\S]*)\]\(figures\/([^)\s]+)\)(?:\{#([^}]+)\})?$/.exec(p);
      const tableRef = /^\{\{table:([^}]+)\}\}$/.exec(p);
      if (heading && !p.includes("\n")) {
        const level = heading[1]!.length as 1 | 2 | 3;
        const text = heading[2]!.trim();
        if (level === 1 && /^abstract$/i.test(text) && sections.length === 0) {
          abstract = true;
          continue;
        }
        if (level === 1) {
          top = s.appendix ? String.fromCharCode(65 + appendices++) : String(++chapters);
          counters[1] = counters[2] = 0;
        } else {
          counters[level - 1]!++;
          if (level === 2) counters[2] = 0;
        }
        const number = [top, ...counters.slice(1, level)].join(".");
        const a = anchor(heading[3] ?? slug(text));
        target(heading[3] ?? null, s.appendix ? "Appendix" : "Section", number, a);
        blocks.push({ type: "heading", level, text, number, label: heading[3] ?? null, anchor: a });
      } else if (figure) {
        const a = anchor(figure[3] ?? `figure-${figures + 1}`);
        target(figure[3] ?? null, "Figure", String(++figures), a);
        blocks.push({ type: "figure", file: figure[2]!, caption: figure[1]!.replace(/\s+/g, " "), number: figures, label: figure[3] ?? null, anchor: a });
      } else if (tableRef || p.startsWith(": ")) {
        // A table is a reference to a CSV or a pipe table, with its caption and note next to it in any order.
        let name = tableRef ? tableRef[1]!.trim() : null;
        let caption = tableRef ? "" : p;
        let note = "";
        let markdown: string | null = null;
        for (let next = paras[i + 1]; ; next = paras[i + 1]) {
          if (!caption && next?.startsWith(": ")) caption = next;
          else if (!note && isNote(next)) note = next.slice(1, -1);
          else if (!name && !markdown && isPipeTable(next)) markdown = next;
          else if (!name && !markdown && next && /^\{\{table:([^}]+)\}\}$/.test(next)) name = next.slice(8, -2).trim();
          else break;
          i++;
        }
        const label = /\{#([^}]+)\}\s*$/.exec(caption)?.[1] ?? null;
        const a = anchor(label ?? `table-${tables + 1}`);
        target(label, "Table", String(++tables), a);
        blocks.push({ type: "table", name, markdown, caption: caption.replace(/^: /, "").replace(/\s*\{#[^}]+\}\s*$/, "").replace(/\s+/g, " "), note: note.replace(/\s+/g, " "), number: tables, label, anchor: a });
      } else if (/^\$\$[\s\S]*\$\$$/.test(p)) {
        prose(`$$\n${p.slice(2, -2).trim()}\n$$`);
      } else prose(p);
    }
    sections.push({ file: s.file, source: s.source, appendix: s.appendix, abstract, blocks });
  }

  // Pass 2: numbers, citations and references inside the text.
  const ctx: Context = {
    results: handover.results ?? {},
    sources: { references: handover.references ?? {}, web: handover.web_sources ?? {} },
    targets,
    cited: new Set(),
    missing: new Set(),
    footnotes: [],
  };
  let words = 0;
  for (const s of sections)
    for (const b of s.blocks) {
      if (b.type === "prose") {
        words += b.markdown.split(/\s+/).filter(Boolean).length;
        b.markdown = inline(b.markdown, ctx);
      } else if (b.type === "heading") b.text = inline(b.text, ctx);
      else {
        b.caption = inline(b.caption, ctx);
        if (b.type === "table") {
          b.note = inline(b.note, ctx);
          if (b.markdown) b.markdown = inline(b.markdown, ctx);
        }
      }
    }
  const label = (key: string) => {
    const parts = citeParts(key, ctx.sources);
    return parts ? `${parts.who} ${parts.year}`.toLowerCase() : key.toLowerCase();
  };
  return {
    sections,
    outline: sections.flatMap((s) => s.blocks.flatMap((b) => (b.type === "heading" ? [{ anchor: b.anchor, number: b.number, text: b.text, level: b.level }] : []))),
    cited: [...ctx.cited].sort((a, b) => label(a).localeCompare(label(b))),
    footnotes: ctx.footnotes,
    missing: [...ctx.missing].sort(),
    words,
  };
}

/** Where a cross-reference points, for the reader's scrolling. */
export function anchorOf(paper: Paper, label: string): string | null {
  for (const s of paper.sections) for (const b of s.blocks) if (b.type !== "prose" && b.label === label) return b.anchor;
  return null;
}

/** Inline Markdown for a table cell or a caption taken from elsewhere (a CSV cell). */
export const inlineWith = (text: string, handover: Handover): string =>
  inline(text, { results: handover.results ?? {}, sources: { references: handover.references ?? {}, web: handover.web_sources ?? {} }, targets: new Map(), cited: new Set(), missing: new Set(), footnotes: [] });
