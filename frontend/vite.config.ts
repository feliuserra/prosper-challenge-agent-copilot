import { defineConfig } from "vite";

// Everything the page talks to lives on the Pipecat runner (one process, ADR 0005).
// Proxying keeps the browser on a single origin, so there is no CORS to configure.
const runner = "http://localhost:7860";

export default defineConfig({
  server: {
    proxy: {
      "/start": runner,
      "/sessions": runner,
      "/api": runner,
      "/composer": runner,
    },
  },
});
