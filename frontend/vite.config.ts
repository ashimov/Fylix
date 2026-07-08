import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// Single source of truth for the version badge rendered in AppFooter.
// Read at build time so the bundle carries the exact package.json value.
const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("./package.json", import.meta.url)), "utf-8"),
) as { version: string };

export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "https://localhost", changeOrigin: true, secure: false },
      "/t": { target: "https://localhost", changeOrigin: true, secure: false },
      "/s": { target: "https://localhost", changeOrigin: true, secure: false },
      "/healthz": { target: "https://localhost", changeOrigin: true, secure: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["vue", "vue-router", "pinia", "vue-i18n"],
          tus: ["tus-js-client"],
        },
      },
    },
  },
});
