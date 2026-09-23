import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../src/lib/readerViewState.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const view = { version: 1, pageNumber: 24, location: { pageNumber: 24, left: 2, top: 341 }, zoom: "page-width", mode: "single" };
function load(storage) { const exports = {}; vm.runInNewContext(code, { exports, window: { get localStorage() { if (storage instanceof Error) throw storage; return storage; } } }); return exports; }
const plain = value => JSON.parse(JSON.stringify(value));

test("reader bookmarks restore across module/browser reopening and contain only whitelisted preferences", () => {
  const values = new Map(); const storage = { setItem: (key, value) => values.set(key, value), getItem: key => values.get(key) };
  load(storage).rememberReaderView('["doc","revision"]', { ...view, sourceText: "Do not persist", key: "Do not persist" });
  assert.deepEqual(plain(load(storage).readReaderView('["doc","revision"]')), view);
  assert.equal(load(storage).readReaderView('["doc","other-revision"]'), null);
  assert.equal(load(storage).readReaderView('["other-document","revision"]'), null);
  assert.doesNotMatch([...values.values()][0], /Do not persist|sourceText/);
});

test("denied, quota-limited or unavailable storage falls back to same-session memory", () => {
  for (const storage of [undefined, new Error("denied"), { getItem() { throw Error(); }, setItem() { throw Error(); } }]) {
    const api = load(storage);
    assert.equal(api.readReaderView("new"), null);
    api.rememberReaderView("new", view);
    assert.deepEqual(plain(api.readReaderView("new")), view);
  }
});

test("invalid and obsolete state is ignored, including unbounded numeric preferences", () => {
  for (const invalid of [null, {}, { ...view, version: 0 }, { ...view, pageNumber: 0 }, { ...view, pageNumber: 2.5 },
    { ...view, zoom: -1 }, { ...view, zoom: Infinity }, { ...view, zoom: "unknown" }, { ...view, mode: "unknown" }]) {
    assert.equal(load().validReaderView(invalid), null);
  }
  assert.equal(load({ getItem: () => "not json" }).readReaderView("new"), null);
  assert.equal(load().validReaderView({ ...view, location: { pageNumber: 1, left: 0, top: 0 } }).location, undefined);
});
