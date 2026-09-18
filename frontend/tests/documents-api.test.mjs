import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadLibrary(get) {
  const source = readFileSync(new URL("../src/lib/documentsApi.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    require: (name) => {
      assert.equal(name, "@/lib/api");
      return { default: { get } };
    },
  });
  return exports.loadWorkspaceDocuments;
}

test("workspace document lists preserve more than fifty documents", async () => {
  const documents = Array.from({ length: 75 }, (_, index) => ({
    id: `fixture-${index}`, filename: `agreement-${index}.pdf`,
    upload_date: "2026-01-01T00:00:00Z", contract_type: null,
  }));
  const load = loadLibrary(async (endpoint) => {
    assert.equal(endpoint, "/documents/");
    return { success: true, data: { documents } };
  });
  const result = await load();
  assert.equal(result, documents);
  assert.equal(result.length, 75);
  assert.equal(result.at(-1).id, "fixture-74");
});

test("a failed or malformed library response is not shown as an empty library", async () => {
  const failed = loadLibrary(async () => ({ success: false, error: { message: "Workspace unavailable" } }));
  await assert.rejects(failed(), /Workspace unavailable/);
  const malformed = loadLibrary(async () => ({ success: true, data: {} }));
  await assert.rejects(malformed(), /unexpected response/);
});
