import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// These two headers make the page "cross-origin isolated". The Python runner
// needs that for SharedArrayBuffer, which is how input() can pause a program
// and wait for the student to type. Production hosting must send them too.
const isolation = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "require-corp",
};

const backend = "http://127.0.0.1:8020";
const proxy = {
  "/api": backend,
  "/ws": { target: backend, ws: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: isolation,
    proxy,
  },
  // `vite preview` serves the production build (with the service worker) on 4173.
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    headers: isolation,
    proxy,
  },
});
