import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Shell } from "@werkbank/framework";
import "@werkbank/framework/styles.css";
import "./kit/kit.css";
import "./theme.css";
import "./app.css";
import { werkbank } from "./app";
import { api } from "./data/api";
import { ServiceStatus } from "./ServiceStatus";

// After `sb update` or a rebuild, a page that was open asks for the old build's parts, which are gone:
// load the new build once instead of showing "failed to fetch dynamically imported module". The
// workspace and settings are in the browser, so nothing is lost; a second failure within a minute
// is shown as it is, so a broken build cannot reload forever.
window.addEventListener("vite:preloadError", (event) => {
  const key = "sb-reloaded-for-new-build";
  let last = 0;
  try {
    last = Number(sessionStorage.getItem(key) ?? 0);
    if (Date.now() - last < 60_000) return;
    sessionStorage.setItem(key, String(Date.now()));
  } catch {
    // no session storage: reload anyway, once per page
  }
  event.preventDefault();
  location.reload();
});

// Handles for poking at the app from the browser console.
Object.assign(window, { werkbank, api });

// The agent bridge, always through the page's own address: the dev server and `sb ui` both pass the
// connection on and name the app's folder, where the bridge keeps the conversations (frontend/.werkbank/).
// ?bridge=ws://… overrides it (then everything stays in this browser).
const bridgeUrl =
  new URLSearchParams(location.search).get("bridge") ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/__bridge`;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Shell werkbank={werkbank} bridgeUrl={bridgeUrl} status={<ServiceStatus />} />
  </StrictMode>,
);
