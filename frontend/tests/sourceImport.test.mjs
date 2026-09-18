import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function importer(response) {
  const calls = [];
  const source = readFileSync(new URL("../src/lib/sourceImport.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require(name) {
    assert.equal(name, "@/lib/api");
    return { default: { async uploadFile(...args) { calls.push(args); return response; } } };
  } });
  return { ...exports, calls };
}

test("key-free import uses only the source endpoint, including incomplete extraction", async () => {
  const module = importer({ success: true, data: { id: "doc-1", source_status: "stored", extraction_status: "partial" } });
  const file = { name: "synthetic.pdf" };
  assert.equal((await module.importSource(file)).id, "doc-1");
  assert.deepEqual(module.calls, [["/documents/import", file]]);
});

test("import failure preserves a known record for recovery", async () => {
  const module = importer({ success: false, error: { message: "Source processing could not be saved.", details: { document_id: "doc-1" } } });
  await assert.rejects(module.importSource({}), error => error instanceof module.SourceImportError && error.documentId === "doc-1");
});

test("uncertain import never fabricates a document or automatically retries", async () => {
  const module = importer({ success: false });
  await assert.rejects(module.importSource({}), error => error.documentId === undefined && /Check the library/.test(error.message));
  assert.equal(module.calls.length, 1);
});
