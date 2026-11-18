import { copyText } from "@werkbank/framework";
import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { paths, useApi } from "../data/api";
import { EmptyState } from "../kit";
import { type DocPage, type State } from "./documentation";
import { usePanelState } from "./lib";

/** A prompt to copy: the text as it is, and a button that puts it on the clipboard. */
function Prompt({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="sb-prompt">
      <p>{text}</p>
      <button
        type="button"
        className="wb-button"
        onClick={() => {
          copyText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

const COMPONENTS: Components = {
  code({ className, children }) {
    const text = String(children ?? "").replace(/\n$/, "");
    if (/language-prompt/.test(className ?? "")) return <Prompt text={text} />;
    return <code className={className}>{children}</code>;
  },
  // A prompt block arrives inside <pre>; drop the <pre> around it so it is not shown as code.
  pre({ children }) {
    return <>{children}</>;
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    );
  },
};

export default function DocumentationView() {
  const [state, setState] = usePanelState<State>();
  const entry = useApi<{ pages: DocPage[] }>(paths.docs);
  const pages = entry.data?.pages;
  if (!pages) return <EmptyState>{entry.error ?? "Loading…"}</EmptyState>;
  const page = pages.find((p) => p.id === state.page) ?? pages[0];
  const own = pages.filter((p) => p.origin === "sourcebound");
  const fromPacks = pages.filter((p) => p.origin === "pack");
  const item = (p: DocPage) => (
    <li key={p.id}>
      <button type="button" className="wb-list-item" aria-current={p.id === page?.id || undefined} onClick={() => setState({ page: p.id })}>
        {p.title}
      </button>
    </li>
  );
  return (
    <div className="sb-docs">
      <nav className="sb-docs-nav" aria-label="Pages">
        <ul>{own.map(item)}</ul>
        {fromPacks.length > 0 && (
          <>
            <p className="sb-docs-group">From packs</p>
            <ul>{fromPacks.map(item)}</ul>
          </>
        )}
      </nav>
      <article className="sb-docs-page sb-scroll">
        {page ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
            {page.text}
          </ReactMarkdown>
        ) : (
          <EmptyState>No page.</EmptyState>
        )}
      </article>
    </div>
  );
}
