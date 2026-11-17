import { useSyncExternalStore } from "react";
import type { RunResult } from "./api";

/**
 * Output of the `sb` commands run from the app, newest first. It lives for the session only:
 * the commands' effects are in the project files, this is just what they printed.
 */
export interface Run extends Partial<RunResult> {
  project: string;
  command: string;
  running: boolean;
  error?: string;
}

class Runs {
  private list: Run[] = [];
  private listeners = new Set<() => void>();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };
  all = () => this.list;
  latest = (project: string | null) => this.list.find((r) => r.project === project);

  start(project: string, command: string): Run {
    const run: Run = { project, command, running: true };
    this.list = [run, ...this.list].slice(0, 20);
    this.listeners.forEach((l) => l());
    return run;
  }

  finish(run: Run, outcome: Partial<Run>): void {
    this.list = this.list.map((r) => (r === run ? { ...r, ...outcome, running: false } : r));
    this.listeners.forEach((l) => l());
  }
}

export const runs = new Runs();
export const useRuns = () => useSyncExternalStore(runs.subscribe, runs.all);

/** What `sb check` reported, from its output: the lines by severity and the totals. */
export function readCheck(output: string): { errors: string[]; warnings: string[] } {
  const lines = output.split("\n");
  return {
    errors: lines.filter((l) => l.startsWith("ERROR:")).map((l) => l.slice(6).trim()),
    warnings: lines.filter((l) => l.startsWith("warning:")).map((l) => l.slice(8).trim()),
  };
}
