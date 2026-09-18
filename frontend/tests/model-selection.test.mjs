import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/modelSelection.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const helpers = {};
vm.runInNewContext(compiled, { exports: helpers });

const models = [
  { id: "current-fixture", legacy: false },
  { id: "cheap-fixture", legacy: false },
  { id: "old-fixture", legacy: true },
];

test("current catalog choices do not recommend legacy models", () => {
  const visible = helpers.getSelectableModels(models, "current-fixture");
  assert.deepEqual(Array.from(visible, (model) => model.id), ["current-fixture", "cheap-fixture"]);
  assert.equal(models.length, 3);
});

test("a saved legacy model remains visible without rewriting the selection", () => {
  const visible = helpers.getSelectableModels(models, "old-fixture");
  assert.deepEqual(Array.from(visible, (model) => model.id), ["current-fixture", "cheap-fixture", "old-fixture"]);
  assert.equal(helpers.getModelSelectionError(models, "old-fixture", "cheap-fixture"), null);
});

test("unknown or missing models need explicit replacement instead of a silent default", () => {
  for (const selectedId of ["", "unknown-fixture"]) {
    assert.match(helpers.getModelSelectionError(models, selectedId, "cheap-fixture"), /Choose an available review model/);
    const visible = helpers.getSelectableModels(models, selectedId);
    assert.equal(visible.some((model) => model.id === selectedId), false);
  }
});

test("the separate classifier must also be a known catalog model", () => {
  assert.match(helpers.getModelSelectionError(models, "current-fixture", "unknown-fixture"), /under Advanced/);
  assert.equal(helpers.getModelSelectionError(models, "current-fixture", "cheap-fixture"), null);
  assert.equal(helpers.getModelSelectionError(models, "cheap-fixture", "old-fixture"), null);
});

test("small USD reference prices retain cents and sub-cent precision", () => {
  assert.equal(helpers.formatModelRate(0.05), "$0.05");
  assert.equal(helpers.formatModelRate(0.2), "$0.20");
  assert.equal(helpers.formatModelRate(0.005), "$0.005");
  assert.equal(helpers.formatModelRate(12), "$12.00");
});
