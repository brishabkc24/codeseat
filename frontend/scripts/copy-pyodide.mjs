// Copies the Pyodide runtime out of node_modules into public/pyodide so the
// app serves Python from its own origin (no CDN needed in the classroom).
// Runs automatically after `npm install`.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "node_modules", "pyodide");
const target = join(root, "public", "pyodide");

if (!existsSync(source)) {
  console.log("copy-pyodide: pyodide is not installed yet, skipping");
  process.exit(0);
}

const wanted = /\.(js|mjs|wasm|zip|json)$/;
const skipped = new Set(["package.json", "console.html"]);

mkdirSync(target, { recursive: true });
let count = 0;
for (const name of readdirSync(source)) {
  if (!wanted.test(name) || skipped.has(name) || name.endsWith(".map")) continue;
  cpSync(join(source, name), join(target, name));
  count += 1;
}
console.log(`copy-pyodide: copied ${count} files to public/pyodide`);
