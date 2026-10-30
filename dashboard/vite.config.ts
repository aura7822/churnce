import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the browser talks to Vite, Vite forwards /api (including the WebSocket) to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.CHURNCE_API ?? "http://localhost:8000", changeOrigin: true, ws: true } },
  },
  build: { sourcemap: true, target: "es2022" },
});
