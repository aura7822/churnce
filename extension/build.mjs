// Bundles each entry point into dist/ and copies the static files. Run: npm run build, then load dist/ as an unpacked extension.
import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });

await build({
  entryPoints: {
    background: "src/background/index.ts",
    popup: "src/popup/popup.ts",
    settings: "src/settings/settings.ts",
  },
  bundle: true,
  format: "esm",
  target: "chrome120",
  outdir: "dist",
  sourcemap: true,
  logLevel: "info",
});
// Content scripts are injected as classic scripts, so that bundle must not use ESM syntax at the top level.
await build({ entryPoints: { content: "src/content/index.ts" }, bundle: true, format: "iife", target: "chrome120", outdir: "dist", sourcemap: true });

cpSync("manifest.json", "dist/manifest.json");
cpSync("src/popup/popup.html", "dist/popup.html");
cpSync("src/settings/settings.html", "dist/settings.html");
cpSync("src/shared/ui.css", "dist/ui.css");
