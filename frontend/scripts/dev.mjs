// Starts the app, the agent bridge and the Sourcebound data service together (for work on the frontend).
// To use the frontend, `sb ui` is enough: it serves the built app and starts the bridge.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

const port = process.env.SB_UI_PORT ?? "5210";
// The checkout's own environment if there is one, else whatever `sb` is on the PATH.
const sb = ["../.venv/bin/sb", "../.venv/Scripts/sb.exe"].find((p) => existsSync(p)) ?? "sb";
const shell = process.platform === "win32";
const children = [
  spawn(sb, ["ui", "--no-open", "--no-bridge", "--port", port], { stdio: "inherit" }),
  spawn("npx", ["werkbank-bridge", "--hub"], { stdio: "inherit", shell }),
  spawn("npx", ["vite"], { stdio: "inherit", shell }),
];
const stop = () => children.forEach((child) => child.kill("SIGTERM"));
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
children.forEach((child) => child.on("exit", (code) => (stop(), process.exit(code ?? 0))));
