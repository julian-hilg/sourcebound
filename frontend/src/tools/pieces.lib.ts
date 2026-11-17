import { api, paths, useApi, type Piece, type Pieces } from "../data/api";
import { projectOf, useProject } from "./lib";

/** Shared by the four piece panels (list, editor, preview, schedule): which pieces, which one, when to post. */

export function usePieces(): { project: string | null; data: Pieces | undefined; error: string | undefined } {
  const { id, list } = useProject();
  const entry = useApi<Pieces>(id ? paths.pieces(id) : null);
  return { project: id, data: entry.data, error: list.error ?? entry.error };
}

export const piecesOf = (links: Record<string, unknown>): { project: string | null; data: Pieces | undefined } => {
  const project = projectOf(links);
  return { project, data: project ? api.peek<Pieces>(paths.pieces(project)) : undefined };
};

/** The piece the link group selected, else the first one. */
export const pickPiece = (data: Pieces | undefined, linked: unknown): Piece | undefined => data?.pieces.find((p) => p.id === linked) ?? data?.pieces[0];

const pad = (n: number) => String(n).padStart(2, "0");
/** "2026-11-20 08:30" in local time, the form the schedule field takes. */
export const stamp = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const STAMP = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$/;

/** The next usual posting day and time on which nothing else of this project is scheduled. */
export function nextSlot(pieces: Piece[], days: number[], time: string, now = new Date()): string {
  const [h, m] = time.split(":").map(Number) as [number, number];
  const taken = new Set(pieces.filter((p) => p.status === "scheduled" && p.scheduled_at).map((p) => stamp(new Date(p.scheduled_at!)).slice(0, 10)));
  const wanted = days.length ? days : [1, 2, 3, 4, 5];
  for (let n = 0; n < 120; n++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + n, h, m);
    if (d > now && wanted.includes(d.getDay()) && !taken.has(stamp(d).slice(0, 10))) return stamp(d);
  }
  return stamp(new Date(now.getTime() + 86_400_000));
}

/** A piece for an agent: the card, where its renders are, and the text up to a cap. */
export const pieceCard = ({ text, renders, ...card }: Piece, textCap: number) => ({
  ...card,
  characters: text.length,
  text: text.slice(0, textCap),
  renders: renders.map((r) => ({ template: r.template, kind: r.kind, at: r.at, files: r.files, shows_older_values_of: r.stale })),
});
