import type { ReactNode } from "react";

/**
 * A list and the detail of what is selected in it, in one panel. Side by side when the panel
 * is wide, stacked when it is narrow; the panel's own width decides, not the window's.
 * Use when the detail is short enough to live next to the list; open a second panel
 * (linked by a topic) when it is not.
 */
export function SplitPane({ list, detail, listWidth = 320, label }: { list: ReactNode; detail: ReactNode | null; listWidth?: number; label?: string }) {
  return (
    <div className="kit-split">
      <div className="kit-split-inner" style={{ ["--kit-split-list" as string]: `${listWidth}px` }}>
        <div className="kit-split-list">{list}</div>
        {detail !== null && (
          <div className="kit-split-detail" role="region" aria-label={label}>
            {detail}
          </div>
        )}
      </div>
    </div>
  );
}

/** A panel's frame: fixed head (toolhead, notices), scrolling body. */
export function PanelBody({ head, children, flush = false }: { head?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <div className="kit-panel">
      {head}
      <div className="kit-panel-body" data-flush={flush || undefined}>
        {children}
      </div>
    </div>
  );
}
