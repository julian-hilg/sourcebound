import { useWerkbank } from "@werkbank/framework";
import { useOnline } from "./data/api";

/** Status bar item: whether the Sourcebound service (`sb ui`) answers. Clicking reloads the data. */
export function ServiceStatus() {
  const wb = useWerkbank();
  const online = useOnline();
  return (
    <button className={`wb-status-button${online === false ? " wb-status-warn" : ""}`} title="The local Sourcebound service that reads the project files. Click to reload." onClick={() => void wb.run("data.refresh")}>
      {online === false ? "data: not reachable (start sb ui)" : online ? "data: live" : "data: connecting"}
    </button>
  );
}
