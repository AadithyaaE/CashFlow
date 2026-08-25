// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, nitro (build-only using cloudflare as a default target),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// Vercel remains the default target (untouched). Docker's build sets
// NITRO_PRESET=node so the same `vite build` instead emits a standalone
// Node server under .output/ — Vercel's Build Output API layout isn't
// something a plain container can run directly.
const isNodeBuild = process.env.NITRO_PRESET === "node";

export default defineConfig({
  nitro: isNodeBuild
    ? { preset: "node" }
    : {
        preset: "vercel",
        // Emit straight into Vercel's Build Output API v3 layout so a plain
        // `vite build` on Vercel's own build machines (no Nitro deploy step)
        // is already a valid deployment — no separate `vercel build` needed.
        output: {
          dir: ".vercel/output",
          serverDir: ".vercel/output/functions/__server.func",
          publicDir: ".vercel/output/static",
        },
      },
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
});
