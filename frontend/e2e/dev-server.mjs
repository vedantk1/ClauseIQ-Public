import { spawn, execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { fileURLToPath } from "node:url";

const realStack = process.env.CLAUSEIQ_REALSTACK_BROWSER === "1";
const port = realStack ? "3101" : "3100";
const apiOrigin = realStack ? "http://127.0.0.1:8101" : "http://127.0.0.1:3100";
const outputDirectory = realStack ? ".next-e2e-real" : ".next-e2e";
if (process.env.CLAUSEIQ_E2E !== "1" || process.env.NEXT_PUBLIC_API_URL !== apiOrigin) {
  throw new Error("Use the browser test commands so the isolated output and permitted API origin are configured.");
}

// Next always writes next-env.d.ts in the project root, even with a separate
// tsconfig/distDir. Preserve that generated file so testing beside npm run dev
// does not leave the ordinary workspace pointing at test-only route types.
const directory = fileURLToPath(new URL("..", import.meta.url));
const generatedTypes = fileURLToPath(new URL("../next-env.d.ts", import.meta.url));
function readTypes() {
  try { return readFileSync(generatedTypes); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}
const previousTypes = readTypes();
execFileSync(process.execPath, ["scripts/prepare-pdf-assets.mjs"], { cwd: directory, stdio: "inherit" });
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", port], {
  cwd: directory, stdio: "inherit", env: process.env,
});
let stopping = false;
let forceStop;
function stop(signal) {
  if (stopping) return;
  stopping = true;
  child.kill(signal);
  forceStop = setTimeout(() => child.kill("SIGKILL"), 3_000);
  forceStop.unref();
}
process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
child.once("exit", code => {
  clearTimeout(forceStop);
  const current = readTypes();
  // Another ordinary dev/build process may already have restored its own path.
  // Do not overwrite that concurrent update.
  if (current?.toString("utf8").includes(`path="./${outputDirectory}/types/routes.d.ts"`)) {
    if (previousTypes) writeFileSync(generatedTypes, previousTypes);
    else unlinkSync(generatedTypes);
  }
  process.exitCode = stopping ? 0 : (code ?? 1);
});
child.once("error", error => { console.error(error.message); process.exitCode = 1; });
