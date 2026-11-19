import react from "@vitejs/plugin-react";
import { bridgeProxy } from "@werkbank/bridge/vite";
import { defineConfig } from "vite";

// The Sourcebound service (`sb ui`) answers /api; in development the dev server forwards to it.
const API = `http://127.0.0.1:${process.env.SB_UI_PORT ?? 5210}`;

export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ["react", "react-dom"] },
  server: {
    port: 5200,
    strictPort: true,
    proxy: {
      // The app reaches the agent bridge and the data service through its own address; bridgeProxy also
      // names this folder to the bridge, which keeps the conversations in .werkbank/ here.
      ...bridgeProxy(),
      "/api": { target: API, changeOrigin: false },
    },
  },
});
