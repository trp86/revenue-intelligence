/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // e2e/.data holds the walkthrough's DuckDB files; watching them fails while the API has them open
  server: { port: 5173, strictPort: true, watch: { ignored: ["**/e2e/.data/**", "**/test-results/**"] } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
