import { copyText, defineTool, openContextMenu, useSetting, useWerkbank } from "@werkbank/framework";
import { useState } from "react";
import { z } from "zod";
import { api, paths, useApi, type Job, type JobRun, type Jobs } from "../data/api";
import { CodeBlock, CommandLine, ConfirmButton, EmptyState, KeyValue, Section, SplitPane, StatusDot, StatusPill } from "../kit";
import { prefs } from "../prefs";
import { ago, showTable, tone, usePanelState, when } from "./lib";

/**
 * Jobs: pipelines that run again and again and keep a lake table current (continuous
 * collection, "pseudo-APIs"). Sourcebound has no daemon: the system's scheduler calls
 * `sb job run --due`. A job is added and edited as a file; here it can be watched and run once.
 */

const stateSchema = z.object({ selected: z.string().max(80).nullable() });
type State = z.infer<typeof stateSchema>;

const state_ = (j: Job) => (j.error ? "broken" : !j.enabled ? "off" : j.due ? "due" : j.last_status === "failed" ? "failed" : j.last_status ? "ok" : "never ran");

function JobsPanel() {
  const wb = useWerkbank();
  const [state, setState] = usePanelState<State>();
  const [confirm] = useSetting<boolean>("confirm.jobRun");
  const entry = useApi<Jobs>(paths.jobs, prefs.every.jobs);
  const [running, setRunning] = useState<string | null>(null);
  const [last, setLast] = useState<JobRun | { job: string; error: string } | null>(null);
  const d = entry.data;
  if (!d) return <EmptyState>{entry.error ?? "Loading…"}</EmptyState>;
  const job = d.jobs.find((j) => j.id === state.selected) ?? null;
  const run = async (id: string) => {
    setRunning(id);
    const outcome = await wb.run("job.run", { id });
    setRunning(null);
    setLast(outcome.ok ? (outcome.value as JobRun) : { job: id, error: outcome.error });
  };
  const list = (
    <nav aria-label="Jobs">
      {d.jobs.map((j) => (
        <button
          key={j.id}
          className="wb-list-item sb-list-row"
          aria-current={j.id === state.selected || undefined}
          onClick={() => setState({ selected: j.id })}
          onContextMenu={(e) => openContextMenu(wb, e, [{ label: "Copy id", run: () => copyText(j.id) }, j.run ? { label: "Copy what it runs", run: () => copyText(j.run!) } : null])}
        >
          <StatusDot tone={j.error || j.last_status === "failed" ? "bad" : j.due ? "warn" : j.last_status === "ok" ? "good" : undefined} label={state_(j)} />
          <span className="sb-list-name" title={j.title}>
            {j.title}
          </span>
          <span className="wb-dim">{j.error ? "broken" : `every ${j.every}`}</span>
        </button>
      ))}
      {d.jobs.length === 0 && (
        <div className="sb-pad">
          <p className="wb-hint">
            No job yet. A job runs a pipeline on a schedule, so a source without an API becomes a table that stays current: the pipeline fetches under the fetcher's rules,
            parses and upserts; projects read the table with snapshots.
          </p>
          <CommandLine command={'sb job add ID --run "pipelines/x/pipeline.py" --every 6h --table schema.table'} />
        </div>
      )}
    </nav>
  );
  const runs = d.log.filter((r) => !job || r.job === job.id);
  const detail = (
    <div className="sb-pad">
      {job ? (
        <>
          <p>
            <strong>{job.title}</strong> <code>{job.id}</code> <StatusPill tone={tone(state_(job) === "ok" ? "ok" : state_(job) === "failed" || state_(job) === "broken" ? "failed" : state_(job) === "due" ? "review" : undefined)}>{state_(job)}</StatusPill>
          </p>
          {job.error && <p className="sb-notice" data-tone="bad">{job.error}</p>}
          <KeyValue
            items={[
              { label: "Runs", value: <code>{job.run}</code> },
              { label: "Every", value: job.every },
              { label: "Keeps current", value: job.table ? <button className="sb-ref" onClick={() => void showTable(wb, job.table!)}>{job.table}</button> : "–" },
              { label: "Reads", value: job.source || "–" },
              { label: "Last run", value: job.last_run ? `${when(job.last_run)} (${ago(job.last_run)}), ${job.last_status}, ${job.last_seconds} s` : "never" },
              { label: "Next run", value: !job.enabled ? "switched off" : job.due ? "due now" : when(job.next_run) },
            ]}
          />
          {job.last_status === "failed" && job.last_message && <CodeBlock text={job.last_message} maxHeight={160} />}
          <p>
            <ConfirmButton confirm={confirm} question="Run it now? It fetches from the web." disabled={Boolean(job.error) || running !== null} onConfirm={() => void run(job.id)} title="Runs the job once, outside its schedule (sb job run)">
              {running === job.id ? "Running…" : "Run now"}
            </ConfirmButton>
          </p>
          {last && last.job === job.id && ("error" in last ? <p className="sb-notice" data-tone="bad">{last.error}</p> : <p className="sb-notice" data-tone={last.status === "ok" ? undefined : "bad"}>Ran in {last.seconds} s: {last.status}. {last.blocked ? "A host refused and was stopped; look before running again." : ""}</p>)}
        </>
      ) : (
        <p className="wb-hint">Select a job to see what it runs. Jobs are files in the registry; edit them there.</p>
      )}
      <Section title={job ? "Runs of this job" : "Recent runs"} count={runs.length}>
        <table className="wb-table sb-table">
          <tbody>
            {runs.slice(0, 40).map((r, i) => (
              <tr key={`${r.at}${i}`} title={r.message}>
                <td className="wb-num">{when(r.at)}</td>
                {!job && <td>{r.job}</td>}
                <td>
                  <StatusPill tone={r.status === "ok" ? "good" : "bad"}>{r.status}</StatusPill>
                </td>
                <td className="wb-num">{r.seconds} s</td>
                <td className="sb-wrap wb-dim">{r.status === "ok" ? "" : r.message.split("\n").at(-1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.length === 0 && <p className="wb-hint">No run recorded.</p>}
      </Section>
      <Section title="Running on a schedule" aside={<button className="wb-button" onClick={() => copyText(d.schedule_hint)}>Copy</button>}>
        <CodeBlock text={d.schedule_hint} maxHeight={200} />
      </Section>
    </div>
  );
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Jobs</strong>
        <span>
          {d.jobs.length} jobs{d.jobs.some((j) => j.due) ? `, ${d.jobs.filter((j) => j.due).length} due` : ""}
        </span>
      </div>
      <SplitPane list={list} detail={detail} listWidth={260} label="Job" />
    </div>
  );
}

export const jobsTool = defineTool<State>({
  id: "jobs",
  title: "Jobs",
  glyph: "↻",
  category: "Data",
  version: 1,
  stateSchema,
  defaultState: () => ({ selected: null }),
  component: JobsPanel,
  describe: (state) => {
    const d = api.peek<Jobs>(paths.jobs);
    if (!d) return { loaded: false };
    return {
      selected: state.selected,
      note: "Run one with job.run { id } (needs the person's approval: it fetches from the web). A job whose host was stopped fails and waits for the person; never retry it.",
      jobs: d.jobs,
      recent_runs: d.log.slice(0, 20),
    };
  },
});
