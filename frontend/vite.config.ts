import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The dev server proxies API calls to the backend, so the browser talks to a single origin.
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env };
  const apiTarget = env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      // Bind mounts from Windows/macOS hosts don't emit fs events inside Docker.
      watch: { usePolling: env.VITE_USE_POLLING === "true" },
      proxy: {
        // xfwd: send X-Forwarded-For so the API's per-IP rate limits see the real client.
        "/health": { target: apiTarget, changeOrigin: true, xfwd: true },
        "/api": { target: apiTarget, changeOrigin: true, xfwd: true },
      },
    },
  };
});
