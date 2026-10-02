import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Everything the page talks to lives on the Pipecat runner (one process, ADR 0005).
// Proxying keeps the browser on a single origin, so there is no CORS to configure.
// RUNNER_URL overrides it, e.g. to run a second backend next to `make dev`.
const runner = process.env.RUNNER_URL ?? "http://localhost:7860";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/start": runner,
      "/sessions": runner,
      "/api": runner,
      "/composer": runner,
    },
  },
});
