import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API serves the built console from app/static/admin at /admin/ (and at
// the root of ADMIN_UI_HOST, which rewrites onto the same mount). Assets are
// therefore always addressed under /admin/, on either host.
export default defineConfig({
  base: "/admin/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // `make run` serves the API on :8000; proxying keeps the console on one
    // origin in development too, exactly as in production.
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    outDir: "../app/static/admin",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
});
