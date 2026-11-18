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

// Handles for poking at the app from the browser console.
Object.assign(window, { werkbank, api });

// The agent bridge: through the dev server's own address while developing; directly when `sb ui`
// serves the built app (the bridge accepts pages from this machine). ?bridge=ws://… overrides it.
const bridgeUrl =
  new URLSearchParams(location.search).get("bridge") ??
  (import.meta.env.DEV ? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/__bridge` : "ws://127.0.0.1:8787");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Shell werkbank={werkbank} bridgeUrl={bridgeUrl} status={<ServiceStatus />} />
  </StrictMode>,
);
