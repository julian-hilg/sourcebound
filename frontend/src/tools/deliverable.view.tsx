import { Select, useLink, useSetting, useToolState, useWerkbank } from "@werkbank/framework";
import "katex/dist/katex.min.css";
import { useMemo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { paths, useApi, type Handover } from "../data/api";
import { ConfirmButton } from "../kit";
import { anchorOf, inlineWith, parse, referenceLine, type Block, type Paper, type Section } from "../reader/markup";
import { chosen, type State } from "./deliverable";
import { Blank, useProject, when } from "./lib";

const REMARK = [remarkGfm, remarkMath];
const REHYPE = [rehypeKatex];
/** A cell that reads as a number (or as "no value"): such columns are set flush right. */
const NUMERIC = /^(?:[\s+\-−–]?[\d.,\s]+(?:[%‰]|\s?[a-zA-Zµ€$]{1,4})?|[–—-])$/;

/** What the reader needs to turn the links made by `markup.ts` into things a person can use. */
interface Reading {
  handover: Handover;
  paper: Paper;
  selected: string | null;
  pickResult: (key: string) => void;
  jump: (anchor: string | null) => void;
}

function components(r: Reading, inlineOnly: boolean): Components {
  return {
    a({ href, children }) {
      const [kind, key = ""] = (href ?? "").split(/:(.*)/s);
      if (kind === "#sb-result") {
        const result = r.handover.results?.[key];
        const p = result?.provenance;
        const data = Object.entries(p?.data ?? {}).map(([table, snapshot]) => `${table}@${snapshot}`).join(", ");
        const title = result
          ? [`${key} = ${result.display}${result.unit ? ` ${result.unit}` : ""}`, result.hypothesis ? `hypothesis ${result.hypothesis}` : "no hypothesis (descriptive or exploratory)", `recorded by ${p?.script ?? "?"} at commit ${p?.git ?? "none"}`, data ? `data ${data}` : "", p?.at ? when(p.at) : "", result.note ?? ""].filter(Boolean).join("\n")
          : `${key} is used here but was never recorded`;
        return (
          <button className="sb-number" data-missing={!result || undefined} data-selected={key === r.selected || undefined} title={title} onClick={() => r.pickResult(key)}>
            {children}
          </button>
        );
      }
      if (kind === "#sb-cite")
        return (
          <a className="sb-cite" href={href} title={referenceLine(key, { references: r.handover.references ?? {}, web: r.handover.web_sources ?? {} }).replace(/[*<>]/g, "")} onClick={(e) => (e.preventDefault(), r.jump(`ref-${key}`))}>
            {children}
          </a>
        );
      if (kind === "#sb-ref")
        return (
          <a className="sb-cite" href={href} onClick={(e) => (e.preventDefault(), r.jump(anchorOf(r.paper, key)))}>
            {children}
          </a>
        );
      if (kind === "#sb-fn")
        return (
          <sup>
            <a className="sb-cite" href={href} onClick={(e) => (e.preventDefault(), r.jump(`fn-${key}`))}>
              {children}
            </a>
          </sup>
        );
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
    ...(inlineOnly ? { p: ({ children }) => <>{children}</> } : {}),
  };
}

function Text({ markdown, reading, inline = false }: { markdown: string; reading: Reading; inline?: boolean }) {
  const parts = useMemo(() => components(reading, inline), [reading, inline]);
  return (
    <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE} components={parts}>
      {markdown}
    </ReactMarkdown>
  );
}

/** A figure as an image. A PDF figure needs a converter on the machine (pdftoppm or sips); without one it is offered as a file. */
function FigureImage({ project, file, number }: { project: string; file: string; number: number }) {
  const [failed, setFailed] = useState(false);
  const path = `dist/handover/figures/${file}`;
  if (failed)
    return (
      <p className="sb-missing">
        This figure cannot be shown as an image here (a PDF figure needs pdftoppm on the machine that runs sb ui).{" "}
        <a href={paths.raw(project, path)} target="_blank" rel="noreferrer">
          Open {file}
        </a>
      </p>
    );
  return <img src={paths.raw(project, path, true)} alt={`Figure ${number}`} loading="lazy" onError={() => setFailed(true)} />;
}

function BlockView({ block: b, reading, project }: { block: Block; reading: Reading; project: string }) {
  if (b.type === "prose") return <Text markdown={b.markdown} reading={reading} />;
  if (b.type === "heading") {
    const Tag = `h${b.level + 1}` as "h2" | "h3" | "h4";
    return (
      <Tag data-anchor={b.anchor}>
        <span className="sb-secno">{b.number}</span>
        <Text markdown={b.text} reading={reading} inline />
      </Tag>
    );
  }
  if (b.type === "figure")
    return (
      <figure data-anchor={b.anchor}>
        <FigureImage project={project} file={b.file} number={b.number} />
        <figcaption>
          <strong>Figure {b.number}.</strong> <Text markdown={b.caption} reading={reading} inline />
        </figcaption>
      </figure>
    );
  const table = b.name ? reading.handover.tables?.[b.name] : undefined;
  const right = table?.columns.map((_c, i) => table.rows.length > 0 && table.rows.every((row) => !row[i]?.trim() || NUMERIC.test(row[i]!)));
  return (
    <figure className="sb-float-table" data-anchor={b.anchor}>
      <figcaption>
        <strong>Table {b.number}.</strong> <Text markdown={b.caption} reading={reading} inline />
      </figcaption>
      {table ? (
        <table>
          <thead>
            <tr>
              {table.columns.map((c, i) => (
                <th key={i} data-right={right?.[i] || undefined}>
                  <Text markdown={inlineWith(c, reading.handover)} reading={reading} inline />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, n) => (
              <tr key={n}>
                {row.map((cell, i) => (
                  <td key={i} data-right={right?.[i] || undefined}>
                    <Text markdown={inlineWith(cell, reading.handover)} reading={reading} inline />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : b.markdown ? (
        <Text markdown={b.markdown} reading={reading} />
      ) : (
        <p className="sb-missing">{b.name ? `tables/${b.name}.csv is not in the handover.` : "This table has no body in the handover."}</p>
      )}
      {b.note && (
        <p className="sb-tablenote">
          <Text markdown={b.note} reading={reading} inline />
        </p>
      )}
    </figure>
  );
}

export default function DeliverableView() {
  const wb = useWerkbank();
  const { id, list } = useProject();
  const [state, setState] = useToolState<State>();
  const [selected, setResult] = useLink<string | null>("result");
  const [font] = useSetting<string>("reader.font");
  const [mark] = useSetting<boolean>("reader.markNumbers");
  const [width] = useSetting<string>("reader.width");
  const [fontSize] = useSetting<number>("reader.fontSize");
  const [showEdited] = useSetting<boolean>("reader.showEdited");
  const [showReferences] = useSetting<boolean>("reader.showReferences");
  const [confirmHandover] = useSetting<boolean>("confirm.handover");
  const entry = useApi<Handover>(id ? paths.handover(id) : null);
  const page = useRef<HTMLDivElement | null>(null);
  const h = entry.data;
  const d = h?.built ? chosen(h, state) : undefined;
  const paper = useMemo(() => (h && d ? parse(d, h) : null), [h, d]);
  const reading = useMemo<Reading | null>(
    () =>
      h && paper
        ? {
            handover: h,
            paper,
            selected: selected ?? null,
            pickResult: (key) => setResult(key),
            jump: (anchor) => anchor && page.current?.querySelector(`[data-anchor="${CSS.escape(anchor)}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" }),
          }
        : null,
    // setResult is stable per panel; a new selection re-marks the numbers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [h, paper, selected],
  );
  if (!id) return <Blank>{list.error ?? "No project selected."}</Blank>;
  if (!h) return <Blank>{entry.error ?? "Loading…"}</Blank>;
  const rebuild = () => void wb.run("sb.handover", { project: id });
  if (!h.built || !h.handover)
    return (
      <Blank>
        This project has no handover yet. It is the format-neutral copy of the deliverables that this reader shows.
        <br />
        <button className="wb-button" onClick={rebuild}>
          Build it (sb handover)
        </button>
      </Blank>
    );
  if (!d || !paper || !reading) return <Blank>The project has no deliverable yet. The writer agent creates one under deliverables/ once results exist.</Blank>;
  const problems = [...h.handover.problems, ...paper.missing.map((k) => `result ${k} is used but not recorded`), ...(d.unconverted.length ? [`LaTeX commands shown as written: ${d.unconverted.join(" ")}`] : [])];
  const edited = new Set(showEdited ? (h.edited_by_person ?? []) : []);
  const sources = { references: h.references ?? {}, web: h.web_sources ?? {} };
  const section = (s: Section) => {
    const body = s.blocks.map((b, i) => <BlockView key={i} block={b} reading={reading} project={id} />);
    const flag = edited.has(s.source) && (
      <p className="sb-edited" title="Changed since the last agent commit. Agents must not regenerate this section (sb review-edits).">
        edited by a person · {s.source}
      </p>
    );
    return s.abstract ? (
      <section key={s.file} className="sb-abstract" data-anchor="abstract">
        {flag}
        <p className="sb-abstract-title">Abstract</p>
        {body}
        {d.keywords && (
          <p>
            <strong>Keywords:</strong> {d.keywords}
          </p>
        )}
      </section>
    ) : (
      <section key={s.file}>
        {flag}
        {body}
      </section>
    );
  };
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        {h.handover.deliverables.length > 1 ? (
          <Select value={d.name} aria-label="Deliverable" options={h.handover.deliverables.map((x) => ({ value: x.name, label: x.name }))} onChange={(deliverable) => setState({ deliverable })} />
        ) : (
          <strong>{d.name}</strong>
        )}
        <Select value="" placeholder="Go to section" aria-label="Go to section" options={paper.outline.map((o) => ({ value: o.anchor, label: `${o.number} ${o.text.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")}` }))} onChange={(anchor) => reading.jump(anchor)} />
        <span>{paper.words.toLocaleString("en")} words</span>
        <span className={h.stale ? "wb-warn" : undefined} title={h.stale ? `Changed since: ${(h.changed_since ?? []).join(", ")}` : undefined}>
          handover of {when(h.at)}
          {h.stale ? ": older than the text or results" : ""}
        </span>
        <span className="sb-grow" />
        <ConfirmButton confirm={confirmHandover} question="Rewrite dist/handover?" title="Run sb handover: rewrites dist/handover from the current sections and results" onConfirm={rebuild}>
          Rebuild
        </ConfirmButton>
      </div>
      {problems.map((line) => (
        <p key={line} className="sb-notice" data-tone="warn">
          {line}
        </p>
      ))}
      <div className="sb-scroll sb-desk" ref={page}>
        <article className="sb-paper" data-font={font} data-width={width} data-mark={mark || undefined} lang={h.handover.lang} style={{ fontSize }}>
          <header>
            <h1>{d.title ?? h.handover.title}</h1>
            {d.subtitle && <p className="sb-subtitle">{d.subtitle}</p>}
            {(d.author || d.date) && <p className="sb-byline">{[d.author, d.date].filter(Boolean).join(" · ")}</p>}
          </header>
          {paper.sections.filter((s) => !s.appendix).map(section)}
          {paper.footnotes.length > 0 && (
            <section className="sb-footnotes">
              <ol>
                {paper.footnotes.map((note, i) => (
                  <li key={i} data-anchor={`fn-${i + 1}`}>
                    <Text markdown={note} reading={reading} inline />
                  </li>
                ))}
              </ol>
            </section>
          )}
          {showReferences && paper.cited.length > 0 && (
            <section className="sb-references">
              <h2>References</h2>
              {paper.cited.map((key) => (
                <p key={key} data-anchor={`ref-${key}`}>
                  <Text markdown={referenceLine(key, sources)} reading={reading} inline />
                </p>
              ))}
            </section>
          )}
          {paper.sections.filter((s) => s.appendix).map(section)}
        </article>
      </div>
    </div>
  );
}
