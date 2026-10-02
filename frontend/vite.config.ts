import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately on port 8000; Vite forwards /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
