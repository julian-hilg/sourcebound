import { defineTool, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { readCheck, runs, useRuns } from "../data/runs";
import { Blank, projectOf, useProject, when } from "./lib";

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

function Check() {
  const wb = useWerkbank();
  const { id } = useProject();
  const all = useRuns();
  const run = all.find((r) => r.project === id);
  const busy = all.some((r) => r.project === id && r.running);
  const start = (command: string, input: object = {}) => void wb.run(command, { project: id, ...input });
  const report = run?.output !== undefined && run.command.includes("check") ? readCheck(run.output) : null;
  return (
    <div className="sb-panel">
      <div className="wb-toolhead">
        <strong>Check</strong>
        <span>{id ?? "no project"}</span>
        <span className="sb-grow" />
        <button className="wb-button" disabled={!id || busy} title="Ledger, citations, results, typed numbers, contracts (sb check)" onClick={() => start("sb.check")}>
          Run check
        </button>
        <button className="wb-button" disabled={!id || busy} title="The same without asking Zotero for citation keys (sb check --offline)" onClick={() => start("sb.check", { offline: true })}>
          Offline
        </button>
        <button className="wb-button" disabled={!id || busy} title="Sections a person changed since the last agent commit (sb review-edits)" onClick={() => start("sb.reviewEdits")}>
          Review edits
        </button>
      </div>
      <div className="sb-scroll">
        {!run ? (
          <Blank>Nothing has been run for this project in this session. “Run check” runs sb check and shows what it reports.</Blank>
        ) : run.running ? (
          <Blank>Running sb {run.command.replace("-offline", " --offline")}…</Blank>
        ) : (
          <div className="sb-pad">
            <p>
              <code>{run.command.startsWith("sb ") ? run.command : `sb ${run.command}`}</code> <span className="wb-dim">{when(run.at)}</span>{" "}
              {run.error ? (
                <span className="sb-status" data-tone="bad">did not run</span>
              ) : report ? (
                <span className="sb-status" data-tone={report.errors.length ? "bad" : report.warnings.length ? "warn" : "good"}>
                  {report.errors.length} errors, {report.warnings.length} warnings
                </span>
              ) : (
                <span className="sb-status" data-tone={run.exit_code ? "bad" : "good"}>exit code {run.exit_code}</span>
              )}
            </p>
            {run.error && <p className="sb-notice" data-tone="bad">{run.error}</p>}
            {report ? (
              <>
                {report.errors.map((line, i) => (
                  <p key={`e${i}`} className="sb-notice" data-tone="bad">
                    Error: {line}
                  </p>
                ))}
                {report.warnings.map((line, i) => (
                  <p key={`w${i}`} className="sb-notice" data-tone="warn">
                    Warning: {line}
                  </p>
                ))}
                {report.errors.length + report.warnings.length === 0 && <p>Every claim, citation and result resolves.</p>}
              </>
            ) : (
              run.output && <pre className="sb-output">{run.output}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export const checkTool = defineTool<State>({
  id: "check",
  title: "Check",
  glyph: "✔",
  category: "Study",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  links: ["project"],
  component: Check,
  describe: (_state, { links }) => {
    const id = projectOf(links);
    const run = runs.latest(id);
    return {
      project: id,
      note: "Run a check with the sb.check command; sb.reviewEdits lists sections a person edited.",
      last_run: run ? { command: run.command, at: run.at, running: run.running, exit_code: run.exit_code, error: run.error, ...(run.output ? readCheck(run.output) : {}), output: run.output?.slice(0, 20_000) } : null,
    };
  },
});
