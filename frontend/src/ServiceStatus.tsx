import { useSetting, useWerkbank } from "@werkbank/framework";
import { useEffect, useRef } from "react";
import { paths, useApi, useOnline } from "./data/api";
import { show } from "./tools/lib";

/** Status bar item: whether the Sourcebound service (`sb ui`) answers. Clicking reloads the data. */
export function ServiceStatus() {
  const wb = useWerkbank();
  const online = useOnline();
  return (
    <>
      <FollowFocus />
      <button className={`wb-status-button${online === false ? " wb-status-warn" : ""}`} title="The local Sourcebound service that reads the project files. Click to reload." onClick={() => void wb.run("data.refresh")}>
        {online === false ? "data: not reachable (start sb ui)" : online ? "data: live" : "data: connecting"}
      </button>
    </>
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
 * linked panels and brings up the post preview. Off under Settings, Pieces.
 */
function FollowFocus() {
  const wb = useWerkbank();
  const [follow] = useSetting<boolean>("pieces.follow");
  const [deskWorkspace] = useSetting<string>("projects.deskWorkspace");
  const entry = useApi<{ focus: Focus | null }>(follow ? paths.focus : null, 3000);
  const seen = useRef(Date.now() - RECENT_MS);
  const focus = entry.data?.focus;
  useEffect(() => {
    if (!follow || !focus) return;
    const at = Date.parse(focus.at);
    if (!(at > seen.current)) return;
    seen.current = at;
    void (async () => {
      // No Pieces panel here: the desk workspace has room for the preview (the selection survives the switch).
      if (!wb.openPanelOf("pieces")) await wb.run("workspace.preset", { name: deskWorkspace || "Desk" });
      await wb.run("link.publish", { group: "1", topic: "project", value: focus.project });
      await wb.run("link.publish", { group: "1", topic: "piece", value: focus.piece });
      await show(wb, "pieces", { link: "1", patch: { tab: "preview" } });
    })();
  }, [wb, follow, focus, deskWorkspace]);
  return null;
}
