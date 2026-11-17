import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Sourcebound service (`sb ui`) answers /api; in development the dev server forwards to it.
const API = `http://127.0.0.1:${process.env.SB_UI_PORT ?? 5210}`;

export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ["react", "react-dom"] },
  server: {
    port: 5200,
    proxy: {
      // The app reaches the agent bridge and the data service through its own address.
      "/__bridge": { target: "ws://127.0.0.1:8787", ws: true, rewriteWsOrigin: false },
      "/api": { target: API, changeOrigin: false },
    },
  },
});
