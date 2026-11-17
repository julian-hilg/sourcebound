import { defineTool, useLink, useSetting, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { Agenda, EmptyState, Section } from "../kit";
import { prefs } from "../prefs";
import { weekdays } from "../settings";
import { Status } from "./lib";
import { nextSlot, piecesOf, usePieces } from "./pieces.lib";

/**
 * When the pieces of a project are meant to go out: scheduled pieces day by day, the usual
 * posting days marked, and what is approved but has no date yet. Scheduling records an
 * intention; publishing is done by the person, outside this app.
 */

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

function SchedulePanel() {
  const wb = useWerkbank();
  const { project, data, error } = usePieces();
  const [selected, setSelected] = useLink<string | null>("piece");
  const [days] = useSetting<string>("pieces.postingDays");
  const [time] = useSetting<string>("pieces.postingTime");
  const [span] = useSetting<number>("pieces.scheduleDays");
  if (!data || !project) return <EmptyState>{error ?? "Loading…"}</EmptyState>;
  const scheduled = data.pieces.filter((p) => p.status === "scheduled" && p.scheduled_at);
  const waiting = data.pieces.filter((p) => p.status === "approved");
  const review = data.pieces.filter((p) => p.status === "review");
  const due = scheduled.filter((p) => new Date(p.scheduled_at!) <= new Date());
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Schedule</strong>
        <span>
          {scheduled.length} scheduled{due.length ? `, ${due.length} due` : ""}, {waiting.length} approved without a date
        </span>
        <span className="kit-grow" />
        <span className="wb-dim" title="Settings → Pieces">
          usually {days} at {time}
        </span>
      </div>
      {due.length > 0 && (
        <p className="sb-notice" data-tone="warn">
          {due.length === 1 ? "One piece is" : `${due.length} pieces are`} due. Publish, then mark as published in the Piece panel. Nothing is posted from this app.
        </p>
      )}
      <div className="sb-scroll">
        <Agenda
          items={scheduled.map((p) => ({ id: p.id, at: p.scheduled_at!, title: p.title, hint: [p.kind, p.channel].filter(Boolean).join(" · "), tone: new Date(p.scheduled_at!) <= new Date() ? "warn" : undefined }))}
          days={span}
          locale={prefs.locale}
          selected={selected}
          onPick={(id) => setSelected(id)}
          preferredDays={weekdays(days)}
        />
        <div className="sb-pad">
          <Section title="Approved, no date yet" count={waiting.length}>
            {waiting.length === 0 && <p className="wb-hint">Nothing waits for a date.</p>}
            {waiting.map((p) => (
              <p key={p.id} className="wb-row wb-wrap">
                <button className="sb-ref" onClick={() => setSelected(p.id)}>
                  {p.title}
                </button>
                <button className="wb-button" title="Schedules it for the next usual posting day with nothing else on it" onClick={() => void wb.run("piece.decide", { project, id: p.id, status: "scheduled", scheduled_at: nextSlot(data.pieces, weekdays(days), time) })}>
                  Next free slot: {nextSlot(data.pieces, weekdays(days), time)}
                </button>
              </p>
            ))}
          </Section>
          <Section title="In review" count={review.length}>
            {review.length === 0 && <p className="wb-hint">Nothing waits for your review.</p>}
            {review.map((p) => (
              <p key={p.id}>
                <button className="sb-ref" onClick={() => setSelected(p.id)}>
                  {p.title}
                </button>{" "}
                <Status value={p.status} />
              </p>
            ))}
          </Section>
        </div>
      </div>
    </div>
  );
}

export const scheduleTool = defineTool<State>({
  id: "schedule",
  title: "Schedule",
  glyph: "◷",
  category: "Pieces",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  links: ["project", "piece"],
  component: SchedulePanel,
  describe: (_state, { links }) => {
    const { project, data } = piecesOf(links);
    if (!data) return { project, loaded: false };
    const card = (p: (typeof data.pieces)[number]) => ({ id: p.id, title: p.title, kind: p.kind, channel: p.channel, status: p.status, scheduled_at: p.scheduled_at ?? null });
    return {
      project,
      selected: links.piece ?? null,
      note: "Scheduling records when the person intends to publish; it is set with piece.decide (their approval). Nothing is posted by the app.",
      now: new Date().toISOString(),
      scheduled: data.pieces.filter((p) => p.status === "scheduled").sort((a, b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at))).map(card),
      approved_without_date: data.pieces.filter((p) => p.status === "approved").map(card),
      in_review: data.pieces.filter((p) => p.status === "review").map(card),
      published: data.pieces.filter((p) => p.status === "published").slice(-20).map((p) => ({ ...card(p), published_at: p.published_at, url: p.url })),
    };
  },
});
