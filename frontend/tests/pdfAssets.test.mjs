import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { before, test } from "node:test";

const frontend = fileURLToPath(new URL("..", import.meta.url));
const repository = dirname(frontend);
const require = createRequire(import.meta.url);
const distribution = dirname(require.resolve("pdfjs-dist/package.json"));
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const manifest = readJson(join(frontend, "package.json"));
const lock = readJson(join(frontend, "package-lock.json"));
const installed = readJson(join(distribution, "package.json"));
const generated = join(frontend, "public", "pdfjs", installed.version);

function filesWithin(directory, prefix = "") {
  return readdirSync(join(directory, prefix), { withFileTypes: true }).flatMap((entry) => {
    const relativePath = join(prefix, entry.name);
    return entry.isDirectory() ? filesWithin(directory, relativePath) : [relativePath];
  }).sort();
}

before(() => {
  // These are reproducible ignored assets, never fixture or application data.
  execFileSync(process.execPath, ["scripts/prepare-pdf-assets.mjs"], { cwd: frontend, stdio: "pipe" });
});

test("PDF.js is exactly pinned, lockfile-aligned and Apache-2.0 licensed", () => {
  assert.match(manifest.dependencies["pdfjs-dist"], /^\d+\.\d+\.\d+$/);
  assert.equal(installed.version, manifest.dependencies["pdfjs-dist"]);
  assert.equal(lock.packages[""].dependencies["pdfjs-dist"], installed.version);
  assert.equal(lock.packages["node_modules/pdfjs-dist"].version, installed.version);
  assert.equal(installed.license, "Apache-2.0");
  assert.equal(lock.packages["node_modules/pdfjs-dist"].license, "Apache-2.0");
  assert.match(readFileSync(join(distribution, "LICENSE"), "utf8"), /Apache License\s+Version 2\.0/);
});

test("the old React PDF Viewer dependency chain is absent", () => {
  for (const dependencies of [manifest.dependencies, manifest.devDependencies, manifest.optionalDependencies]) {
    assert.ok(Object.keys(dependencies ?? {}).every((name) => !name.startsWith("@react-pdf-viewer/")));
  }
  assert.ok(Object.keys(lock.packages).every((name) => !name.includes("node_modules/@react-pdf-viewer/")));
});

test("development and production builds prepare their local PDF assets", () => {
  assert.equal(manifest.scripts.predev, "node scripts/prepare-pdf-assets.mjs");
  assert.equal(manifest.scripts.prebuild, "node scripts/prepare-pdf-assets.mjs");
});

test("generated worker and license bytes match the installed locked distribution", () => {
  assert.deepEqual(readFileSync(join(generated, "pdf.worker.min.mjs")), readFileSync(join(distribution, "build/pdf.worker.min.mjs")));
  assert.deepEqual(readFileSync(join(generated, "LICENSE")), readFileSync(join(distribution, "LICENSE")));
});

for (const [source, target, extension] of [
  ["cmaps", "cmaps", ".bcmap"],
  ["standard_fonts", "standard_fonts", ".ttf"],
  ["wasm", "wasm", ".wasm"],
  ["iccs", "iccs", ".icc"],
  ["web/images", "images", ".svg"],
]) {
  test(`local PDF ${target} retain distribution resources and notices`, () => {
    const sourceDirectory = join(distribution, source);
    const targetDirectory = join(generated, target);
    const files = filesWithin(sourceDirectory);
    assert.ok(files.some((path) => path.endsWith(extension)), `Expected usable ${extension} resources`);
    assert.deepEqual(filesWithin(targetDirectory), files);
    for (const path of files) {
      const contents = readFileSync(join(targetDirectory, path));
      assert.ok(contents.length > 0, `${target}/${path} must not be empty`);
      assert.deepEqual(contents, readFileSync(join(sourceDirectory, path)), `${target}/${path} must be copied without alteration`);
    }
  });
}

test("generated PDF assets stay outside the tracked source snapshot", () => {
  const ignoreRules = readFileSync(join(repository, ".gitignore"), "utf8").split(/\r?\n/);
  assert.ok(ignoreRules.includes("/frontend/public/pdfjs/"));
  // Downloaded source archives need no Git executable to run the frontend tests.
  if (existsSync(join(repository, ".git"))) {
    const relativeWorker = `frontend/public/pdfjs/${installed.version}/pdf.worker.min.mjs`;
    const ignored = execFileSync("git", ["check-ignore", "--no-index", "--", relativeWorker], { cwd: repository, encoding: "utf8" });
    assert.equal(ignored.trim(), relativeWorker);
    assert.equal(execFileSync("git", ["ls-files", "--", "frontend/public/pdfjs"], { cwd: repository, encoding: "utf8" }).trim(), "");
  }
});
