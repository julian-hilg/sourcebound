import { useLink, useToolState, type Werkbank } from "@werkbank/framework";
import { createContext, useContext, type ReactNode } from "react";
import { api, paths, useApi, type Detail, type Entry, type Summary } from "../data/api";
import { EmptyState, StatusPill } from "../kit";
import { prefs } from "../prefs";

/** Helpers shared by the panels: which project a panel shows, empty states, dates, exports. */

interface ProjectList {
  projects: Summary[];
}

/** The project a panel shows when none was chosen: the first one the service lists. */
export const projectOf = (links: Record<string, unknown>): string | null =>
  (typeof links.project === "string" && links.project) || firstOf(api.peek<ProjectList>(paths.projects)?.projects);

/** The project to show when none is selected: the one named in the settings if it exists, else the first listed. */
const firstOf = (projects: Summary[] | undefined): string | null =>
  (projects?.find((p) => p.id === prefs.firstProject) ?? projects?.[0])?.id ?? null;

/** The panel's project: the one its link group selected, else the first one. */
export function useProject(): { id: string | null; select: (id: string) => void; list: Entry<ProjectList> } {
  const [linked, select] = useLink<string | null>("project");
  const list = useApi<ProjectList>(paths.projects);
  return { id: linked || firstOf(list.data?.projects), select, list };
}

/** The selected project's data, and the node to show instead while there is none. */
export function useDetail(): { id: string | null; detail: Detail | undefined; blank: ReactNode } {
  const { id, list } = useProject();
  const entry = useApi<Detail>(id ? paths.project(id) : null);
  const blank = entry.data ? null : (
    <Blank>
      {list.error ?? entry.error ?? (id === null && list.data ? "No project found. Create one with `sb new`, or start `sb ui` inside a project." : "Loading…")}
    </Blank>
  );
  return { id, detail: entry.data, blank };
}

export const Blank = ({ children }: { children: ReactNode }) => <EmptyState>{children}</EmptyState>;

/** "2026-11-16 17:02" in local time, from an ISO timestamp. */
export function when(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (!prefs.isoDates) return withTime ? d.toLocaleString(prefs.locale, { dateStyle: "medium", timeStyle: "short" }) : d.toLocaleDateString(prefs.locale, { dateStyle: "medium" });
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return withTime ? `${day} ${pad(d.getHours())}:${pad(d.getMinutes())}` : day;
}

/** "3 min ago" for recent times, the date otherwise. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "–";
  if (!prefs.relativeTimes) return when(iso);
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!(seconds >= 0)) return when(iso);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 36 * 3600) return `${Math.round(seconds / 3600)} h ago`;
  return when(iso, false);
}

/** "4 supported, 1 open" from counts per status. */
export const counts = (by: Record<string, number> | undefined): string =>
  Object.entries(by ?? {})
    .map(([status, n]) => `${n} ${status}`)
    .join(", ") || "none";

/** How a status reads: good (settled in favour), bad (refuted, changed), warn (needs attention) or neutral. */
export const tone = (status: string | undefined): "good" | "bad" | "warn" | undefined =>
  status === "supported" || status === "unchanged" || status === "done" || status === "ok" || status === "published" || status === "approved" || status === "active"
    ? "good"
    : status === "refuted" || status === "changed" || status === "failed"
      ? "bad"
      : status === "open" || status === "contested" || status === "inconclusive" || status === "frozen without hash" || status === "review" || status === "scheduled" || status === "candidate" || status === "paused"
        ? "warn"
        : undefined;

export const Status = ({ value }: { value: string | undefined }) => <StatusPill tone={tone(value)}>{value ?? "?"}</StatusPill>;

// ---- exports ------------------------------------------------------------------

export function downloadText(name: string, text: string, mime = "text/plain"): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

type Cell = string | number | boolean | null | undefined;

/** RFC 4180: quote a field when it has a comma, quote or line break. */
export function toCsv(headers: string[], rows: Cell[][]): string {
  const cell = (v: Cell) => {
    const text = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

export const downloadCsv = (name: string, headers: string[], rows: Cell[][]) => downloadText(name, toCsv(headers, rows), "text/csv");

/** Case-insensitive "all words occur" match for the panels' search fields. */
export const matches = (query: string, ...fields: (string | null | undefined)[]): boolean => {
  const text = fields.join(" ").toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => text.includes(word));
};

/** A count or measure in the person's number format. */
export const num = (v: number | null | undefined, digits = 0): string => (v === null || v === undefined ? "–" : v.toLocaleString(prefs.locale, { maximumFractionDigits: digits }));

/**
 * Go to the open panel of a tool, or open one when none is open. A second panel of the same tool opens only when
 * the person drags the tool from the Tools list into the layout, as a click there does. `patch` is merged over the
 * panel's state, the new one's or the open one's, so a hand-off such as a statement for the SQL console keeps that
 * console's history. For a hub, `patch` picks the tab (`{ tab: "claims" }`) and may set a part's state.
 */
export const show = async (wb: Werkbank, toolId: string, { patch, link }: { patch?: Record<string, unknown>; link?: "1" } = {}) => {
  let id = wb.openPanelOf(toolId);
  if (!id) {
    await wb.run("panel.open", { toolId, ...(link ? { link } : {}) });
    id = wb.openPanelOf(toolId);
  }
  if (!id) return;
  if (patch) await wb.run("panel.setState", { id, patch });
  return wb.run("panel.focus", { id });
};

/** Show a panel in the link group the workspaces use, so a new one follows the current selection. */
export const openLinked = (wb: Werkbank, toolId: string) => show(wb, toolId, { link: "1" });

/** Select a lake table for linked panels and bring up the Lake panel. */
export const showTable = async (wb: Werkbank, table: string) => {
  await wb.run("link.publish", { group: "1", topic: "table", value: table });
  await openLinked(wb, "lake");
};

/** Which part of a hub a component is drawn in (see `hub.tsx`); null outside a hub. */
export const HubPart = createContext<string | null>(null);

/**
 * A panel's persisted state. Inside a hub each part keeps its own state under its key in the hub's state, so the
 * same component works as a part of a hub and on its own.
 */
export function usePanelState<S>(): [S, (next: S) => void] {
  const part = useContext(HubPart);
  const [state, setState] = useToolState<Record<string, unknown>>();
  if (!part) return [state as S, setState as (next: S) => void];
  return [state[part] as S, (next: S) => setState((current) => ({ ...current, [part]: next }))];
}
