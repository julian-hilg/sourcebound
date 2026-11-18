import { useSetting, useWerkbank } from "@werkbank/framework";
import { useEffect, useRef } from "react";
import { api, paths, useApi, useOnline, type Pieces } from "./data/api";
import { show } from "./tools/lib";

/** Status bar item: whether the Sourcebound service (`sb ui`) answers. Clicking reloads the data. */
export function ServiceStatus() {
  const wb = useWerkbank();
  const online = useOnline();
  return (
    <>
      <FollowFocus />
      <NewBuild />
      <button className={`wb-status-button${online === false ? " wb-status-warn" : ""}`} title="The local Sourcebound service that reads the project files. Click to reload." onClick={() => void wb.run("data.refresh")}>
        {online === false ? "data: not reachable (start sb ui)" : online ? "data: live" : "data: connecting"}
      </button>
    </>
  );
}

/** The main script this page was loaded with ("index-….js"); none while developing (the dev server). */
const LOADED = (() => {
  const src = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]')?.src ?? "";
  return src.split("/").pop() || null;
})();

/**
 * After `sb update` or a rebuild the service serves a new build, but an open page keeps running the old
 * one until it reloads. This says so in the status bar, with the reload one click away.
 */
function NewBuild() {
  const entry = useApi<{ build?: string | null }>(LOADED ? paths.health : null, 30_000);
  const served = entry.data?.build;
  if (!LOADED || !served || served === LOADED) return null;
  return (
    <button className="wb-status-button wb-status-warn" title={`This page runs ${LOADED}; the service now serves ${served}. Your layout and settings are kept.`} onClick={() => location.reload()}>
      new version: reload
    </button>
  );
}

/** A focus from shortly before the app was opened still counts: "make a post, then open the app". */
const RECENT_MS = 10 * 60 * 1000;

interface Focus {
  project: string;
  piece: string;
  why: string;
  at: string;
}

/**
 * Shows the piece an agent is working on. `sb piece open ID` and every render of a piece write the
 * focus (<data root>/activity/focus.json); a newer one selects that project and piece for the
 * linked panels and brings up its slides (or its post preview). Off under Settings, Pieces.
 */
function FollowFocus() {
  const wb = useWerkbank();
  const [follow] = useSetting<boolean>("pieces.follow");
  const [workspace] = useSetting<string>("pieces.followWorkspace");
  const entry = useApi<{ focus: Focus | null }>(follow ? paths.focus : null, 3000);
  const seen = useRef(Date.now() - RECENT_MS);
  const focus = entry.data?.focus;
  useEffect(() => {
    if (!follow || !focus) return;
    const at = Date.parse(focus.at);
    if (!(at > seen.current)) return;
    seen.current = at;
    void (async () => {
      // No Pieces panel here: the post studio has room for the slides (the selection survives the switch).
      if (!wb.openPanelOf("pieces")) await wb.run("workspace.preset", { name: workspace || "Post studio" });
      await wb.run("link.publish", { group: "1", topic: "project", value: focus.project });
      await wb.run("link.publish", { group: "1", topic: "piece", value: focus.piece });
      // a piece with slides opens on its slides, any other on its post preview
      const piece = (await api.fetch<Pieces>(paths.pieces(focus.project))).pieces.find((p) => p.id === focus.piece);
      await show(wb, "pieces", { link: "1", patch: { tab: piece?.data?.slides ? "slides" : "preview" } });
    })();
  }, [wb, follow, focus, workspace]);
  return null;
}
