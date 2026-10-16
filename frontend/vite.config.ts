import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.MEDDEFENDER_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: false },
    },
  },
  preview: { port: 4173 },
  build: { chunkSizeWarningLimit: 1800, sourcemap: false },
});
