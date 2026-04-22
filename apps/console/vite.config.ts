import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const BACKEND_HTTP = "http://localhost:8090";
const BACKEND_WS = "ws://localhost:8090";

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  test: {
    include: ["src/**/*.{test,spec}.{js,ts}"],
    environment: "node",
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/healthz": BACKEND_HTTP,
      "/version": BACKEND_HTTP,
      "/api": BACKEND_HTTP,
      "/ws": { target: BACKEND_WS, ws: true },
    },
  },
});
