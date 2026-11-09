import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies /api to the Python server: start it with
// `python -m vic2toolmod gui --port 8799 --no-browser` and open
// http://localhost:5173/?token=<token printed by the server>.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../vic2toolmod/server/static_build",
    emptyOutDir: true,
    chunkSizeWarningLimit: 6000,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8799" },
  },
});
