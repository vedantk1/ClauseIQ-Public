import { cpSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const distribution = dirname(require.resolve("pdfjs-dist/package.json"));
const { version } = JSON.parse(readFileSync(join(distribution, "package.json"), "utf8"));
if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error("Unexpected PDF.js version");
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(frontend, "public", "pdfjs", version);
mkdirSync(target, { recursive: true });

// Generate from the installed, locked distribution. Never fetch runtime assets
// from a CDN or check generated third-party binaries into the source repository.
cpSync(join(distribution, "build/pdf.worker.min.mjs"), join(target, "pdf.worker.min.mjs"));
cpSync(join(distribution, "LICENSE"), join(target, "LICENSE"));
for (const resource of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
  cpSync(join(distribution, resource), join(target, resource), { recursive: true });
}
cpSync(join(distribution, "web/images"), join(target, "images"), { recursive: true });
console.log(`Prepared same-origin PDF.js ${version} assets.`);
