import { useSyncExternalStore } from "react";

/**
 * The person's preferences as plain values, kept current from the settings (see `app.ts`).
 * Code outside React (formatters, `describe`, the data store) reads `prefs`; panels re-render
 * when one changes because `useApi` subscribes to the version below.
 */
export const prefs = {
  locale: "en-GB",
  isoDates: true,
  relativeTimes: true,
  firstProject: "",
  rowCap: 100,
  textCap: 30_000,
  /** What a new Fetch log panel shows first. */
  fetchOutcome: "all" as "all" | "refused",
  /** Reload intervals in milliseconds, per class of data. */
  every: { project: 6000, activity: 2000, jobs: 15_000, system: 60_000 },
};

let version = 0;
const listeners = new Set<() => void>();

export function setPrefs(next: Partial<typeof prefs>): void {
  Object.assign(prefs, next);
  version++;
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));
export const usePrefsVersion = () => useSyncExternalStore(subscribe, () => version);
