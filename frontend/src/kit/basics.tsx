import { useEffect, useState, type ReactNode } from "react";
import { copy } from "./format";

/**
 * Small display elements used by every data panel. They take props only, draw with the
 * framework's tokens and `wb-*` classes, and know nothing about the app they are in.
 */

export type Tone = "good" | "bad" | "warn" | "accent" | undefined;

/**
 * A status as a word in a tone. Use for a state a person scans a column for
 * (supported, failed, due). The word always carries the meaning; the colour only repeats it.
 */
export function StatusPill({ tone, children, title, outlined = false }: { tone?: Tone; children: ReactNode; title?: string; outlined?: boolean }) {
  return (
    <span className="kit-pill" data-tone={tone} data-outlined={outlined || undefined} title={title}>
      {children}
    </span>
  );
}

/** A dot that says "ok / not ok / unknown" next to a name in a list. Always pair it with text. */
export function StatusDot({ tone, label }: { tone?: Tone; label: string }) {
  return <span className="kit-dot" data-tone={tone} role="img" aria-label={label} title={label} />;
}

export interface Fact {
  label: ReactNode;
  value: ReactNode;
  /** Shown as a tooltip on the row. */
  title?: string;
}

/** Label and value pairs in two columns. Use for the properties of one selected thing. */
export function KeyValue({ items, dense = false }: { items: (Fact | false | null | undefined)[]; dense?: boolean }) {
  return (
    <dl className="kit-kv" data-dense={dense || undefined}>
      {items.filter((x): x is Fact => Boolean(x)).map((item, i) => (
        <div key={i} title={item.title}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface Tile {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: Tone;
  onClick?: () => void;
}

/** A row of headline numbers. Use at the top of a dashboard; three to eight tiles. */
export function StatTiles({ tiles }: { tiles: Tile[] }) {
  return (
    <div className="wb-kpis kit-tiles">
      {tiles.map((t) => {
        const body = (
          <>
            <div className="wb-kpi-label">{t.label}</div>
            <div className="wb-kpi-value kit-tile-value" data-tone={t.tone}>
              {t.value}
            </div>
            {t.hint !== undefined && (
              <div className="wb-kpi-label kit-ellipsis" title={t.hint}>
                {t.hint}
              </div>
            )}
          </>
        );
        return t.onClick ? (
          <button key={t.label} className="wb-kpi kit-tile-button" onClick={t.onClick}>
            {body}
          </button>
        ) : (
          <div key={t.label} className="wb-kpi">
            {body}
          </div>
        );
      })}
    </div>
  );
}

/** What a panel shows when it has nothing to show: one sentence, and at most one thing to do about it. */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="wb-empty kit-empty">
      <p>{children}</p>
      {action}
    </div>
  );
}

/** A section heading inside a scrolling panel, with an optional count and controls at the right. */
export function Section({ title, count, aside, children }: { title: string; count?: number | string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="kit-section">
      <h3>
        <span>{title}</span>
        {count !== undefined && <span className="kit-count">{count}</span>}
        <span className="kit-grow" />
        {aside}
      </h3>
      {children}
    </section>
  );
}

/** A button that copies text and says so for a moment. */
export function CopyButton({ text, label = "Copy", className = "wb-button" }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 1400);
    return () => clearTimeout(timer);
  }, [state]);
  return (
    <button type="button" className={className} onClick={() => void copy(text).then((ok) => setState(ok ? "done" : "failed"))}>
      {state === "done" ? "Copied" : state === "failed" ? "Not copied" : label}
    </button>
  );
}

/**
 * A command for a terminal, shown in the mono face with a copy button. Use where the app tells
 * a person what to run instead of running it for them (installers, decisions that are theirs).
 */
export function CommandLine({ command, note }: { command: string; note?: ReactNode }) {
  return (
    <div className="kit-command">
      <code>{command}</code>
      <CopyButton text={command} />
      {note && <span className="wb-dim">{note}</span>}
    </div>
  );
}

/** Program output or any preformatted text, wrapped, with an optional copy button. */
export function CodeBlock({ text, copyable = false, maxHeight }: { text: string; copyable?: boolean; maxHeight?: number }) {
  return (
    <div className="kit-code">
      {copyable && <CopyButton text={text} className="wb-button kit-code-copy" />}
      <pre style={maxHeight ? { maxHeight, overflow: "auto" } : undefined}>{text}</pre>
    </div>
  );
}

/**
 * A button that asks once more before it acts: the first click turns it into "Really? Yes / No".
 * Use for an action with an effect outside the app when the person asked for a confirmation.
 * With `confirm={false}` it is an ordinary button.
 */
export function ConfirmButton({ children, question, onConfirm, confirm = true, disabled, title, tone }: { children: ReactNode; question: string; onConfirm: () => void; confirm?: boolean; disabled?: boolean; title?: string; tone?: "warn" }) {
  const [asking, setAsking] = useState(false);
  if (!asking)
    return (
      <button type="button" className="wb-button" data-tone={tone} disabled={disabled} title={title} onClick={() => (confirm ? setAsking(true) : onConfirm())}>
        {children}
      </button>
    );
  return (
    <span className="kit-confirm" role="group" aria-label={question}>
      <span>{question}</span>
      <button type="button" className="wb-button" data-tone={tone} onClick={() => (setAsking(false), onConfirm())}>
        Yes
      </button>
      <button type="button" className="wb-button" onClick={() => setAsking(false)}>
        No
      </button>
    </span>
  );
}

/** Colour swatches with their names. The colours are data (a design's palette), passed in as values. */
export function Swatches({ colors, size = 18 }: { colors: Record<string, string> | string[]; size?: number }) {
  const entries = Array.isArray(colors) ? colors.map((c) => [c, c] as const) : Object.entries(colors);
  return (
    <span className="kit-swatches">
      {entries.map(([name, value]) => (
        <span key={name} className="kit-swatch" title={`${name}: ${value}`} style={{ background: value, width: size, height: size }} role="img" aria-label={`${name} ${value}`} />
      ))}
    </span>
  );
}
