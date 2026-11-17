import type { Tone } from "./basics";

/**
 * Things with a date and time, day by day: what is planned, what is overdue, where the gaps
 * are. Every day of the range is shown, also the empty ones, so a free slot is visible.
 * Use for a publishing schedule, job runs, deadlines. It is a list, not a calendar grid:
 * it reads in a narrow panel.
 */

export interface AgendaItem {
  id: string;
  /** ISO 8601 date and time. */
  at: string;
  title: string;
  hint?: string;
  tone?: Tone;
}

interface Props {
  items: AgendaItem[];
  /** How many days from today to lay out (items beyond are still listed). */
  days?: number;
  locale?: string;
  selected?: string | null;
  onPick?: (id: string) => void;
  /** Days of the week (0 = Sunday) to mark as preferred, e.g. usual posting days. */
  preferredDays?: number[];
  now?: Date;
}

const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function Agenda({ items, days = 14, locale = "en-GB", selected, onPick, preferredDays = [], now = new Date() }: Props) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const sorted = [...items].sort((a, b) => a.at.localeCompare(b.at));
  const overdue = sorted.filter((i) => new Date(i.at) < now);
  const upcoming = sorted.filter((i) => new Date(i.at) >= now);
  const lastDay = upcoming.length ? new Date(upcoming.at(-1)!.at) : today;
  const span = Math.max(days, Math.ceil((lastDay.getTime() - today.getTime()) / 86_400_000) + 1);
  const byDay = new Map<string, AgendaItem[]>();
  for (const i of upcoming) byDay.set(dayKey(new Date(i.at)), [...(byDay.get(dayKey(new Date(i.at))) ?? []), i]);
  const time = (iso: string) => new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const entry = (i: AgendaItem, withDate = false) => (
    <button key={i.id} className="kit-agenda-item" data-tone={i.tone} aria-current={i.id === selected || undefined} onClick={() => onPick?.(i.id)} title={i.hint}>
      <span className="wb-num">{withDate ? `${new Date(i.at).toLocaleDateString(locale, { day: "2-digit", month: "2-digit" })} ` : ""}{time(i.at)}</span>
      <span className="kit-agenda-title">{i.title}</span>
      {i.hint && <span className="wb-dim">{i.hint}</span>}
    </button>
  );
  return (
    <div className="kit-agenda" role="list" aria-label="Schedule">
      {overdue.length > 0 && (
        <div className="kit-agenda-day" data-overdue role="listitem">
          <div className="kit-agenda-date">Due</div>
          <div className="kit-agenda-items">{overdue.map((i) => entry(i, true))}</div>
        </div>
      )}
      {Array.from({ length: span }, (_x, n) => {
        const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + n);
        const list = byDay.get(dayKey(d)) ?? [];
        return (
          <div key={n} className="kit-agenda-day" data-empty={list.length === 0 || undefined} data-today={n === 0 || undefined} data-preferred={preferredDays.includes(d.getDay()) || undefined} role="listitem">
            <div className="kit-agenda-date">
              <span>{d.toLocaleDateString(locale, { weekday: "short" })}</span> <span className="wb-num">{d.toLocaleDateString(locale, { day: "2-digit", month: "2-digit" })}</span>
            </div>
            <div className="kit-agenda-items">{list.map((i) => entry(i))}</div>
          </div>
        );
      })}
    </div>
  );
}
