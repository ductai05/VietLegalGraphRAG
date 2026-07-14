import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Single-page app. Backend stays external and is reached via API_BASE
// (see src/lib/api.js) — no proxy needed for the static build itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173
  },
  build: {
    outDir: "dist"
  }
});
