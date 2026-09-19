import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadModule(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, AbortController, console,
    require(name) { assert.ok(name in imports, `Unexpected dependency: ${name}`); return imports[name]; },
  });
  return exports;
}

const readsModule = loadModule("../src/lib/workspaceReads.ts");
const tick = () => new Promise(resolve => setImmediate(resolve));
const source = { document_id: "fixture", source_revision_id: "revision", source_extraction: { pages: [] } };

function transportHarness() {
  const calls = [];
  const transport = Object.fromEntries(["source", "document"].map(resource => [resource,
    (id, options) => new Promise((resolve, reject) => calls.push({ resource, id, ...options, resolve, reject })),
  ]));
  return { transport, calls };
}

test("source success is available even when agreement metadata fails", async () => {
  const { calls, transport } = transportHarness();
  const reads = new readsModule.WorkspaceReads("fixture", transport);
  reads.load();
  calls[0].resolve(source);
  calls[1].reject(new Error("metadata failure"));
  await tick();
  const state = reads.getSnapshot();
  assert.equal(state.source, source);
  assert.equal(state.sourceStatus, "ready");
  assert.equal(state.metadataStatus, "error");
  assert.equal(state.sourceError, null);
  assert.equal(state.filename, "Agreement");
  assert.match(state.metadataError, /name/);
});

test("metadata success remains available after source failure", async () => {
  const { calls, transport } = transportHarness();
  const reads = new readsModule.WorkspaceReads("fixture", transport);
  reads.load();
  calls[0].reject(new Error("private source response"));
  calls[1].resolve({ id: "fixture", filename: "synthetic.pdf" });
  await tick();
  assert.equal(reads.getSnapshot().filename, "synthetic.pdf");
  assert.equal(reads.getSnapshot().metadataStatus, "ready");
  assert.equal(reads.getSnapshot().sourceStatus, "error");
  assert.equal(reads.getSnapshot().source, null);
  assert.doesNotMatch(reads.getSnapshot().sourceError, /private source response/);
});

test("manual retry performs only the failed read once, without automatically retrying failures", async () => {
  const { calls, transport } = transportHarness();
  const reads = new readsModule.WorkspaceReads("fixture", transport);
  reads.load();
  calls[0].reject(new Error("source failed"));
  calls[1].resolve({ id: "fixture", filename: "synthetic.pdf" });
  await tick();
  assert.equal(calls.length, 2);
  const retry = reads.retrySource();
  void reads.retrySource();
  assert.equal(reads.getSnapshot().sourceStatus, "loading");
  assert.equal(reads.getSnapshot().sourceError, null);
  assert.equal(reads.getSnapshot().metadataStatus, "ready");
  assert.equal(calls.length, 3);
  assert.equal(calls[2].resource, "source");
  calls[2].resolve(source);
  await retry;
  assert.equal(reads.getSnapshot().sourceStatus, "ready");
  assert.equal(calls.length, 3);
});

test("metadata can retry independently while source remains pending", async () => {
  const { calls, transport } = transportHarness();
  const reads = new readsModule.WorkspaceReads("fixture", transport);
  reads.load();
  calls[1].reject(new Error("metadata failed"));
  await tick();
  const retry = reads.retryMetadata();
  calls[2].resolve({ id: "fixture", filename: "synthetic.pdf" });
  await retry;
  assert.equal(reads.getSnapshot().metadataStatus, "ready");
  assert.equal(reads.getSnapshot().sourceStatus, "loading");
  calls[0].resolve(source);
  await tick();
  assert.equal(reads.getSnapshot().sourceStatus, "ready");
});

test("dispose aborts both reads and ignores late success and failure even if transport ignores abort", async () => {
  const { calls, transport } = transportHarness();
  const reads = new readsModule.WorkspaceReads("old", transport);
  let notifications = 0;
  reads.subscribe(() => notifications++);
  reads.load();
  const before = notifications;
  reads.dispose();
  assert.equal(calls.every(call => call.signal.aborted), true);
  calls[0].resolve(source);
  calls[1].reject(new Error("late failure"));
  await tick();
  assert.equal(notifications, before);
  assert.equal(reads.getSnapshot().source, null);
  await reads.retrySource();
  await reads.retryMetadata();
  assert.equal(calls.length, 2);
});

function hookHarness() {
  const { calls, transport } = transportHarness();
  const slots = [];
  const effects = [];
  const controllers = [];
  let cursor = 0;
  let effectCursor = 0;
  let scheduled = [];
  class Controller {
    constructor(id) {
      this.id = id;
      this.state = { localDrafts: { finding: "unsaved review draft" }, localAskDrafts: { finding: "unsent Ask" },
        briefDraft: { priorities: "personal brief" }, workspace: { saved_questions: ["confirmed saved question"] } };
      this.loads = 0;
      controllers.push(this);
    }
    getSnapshot() { return this.state; }
    subscribe(listener) { this.listener = listener; return () => { this.listener = null; }; }
    load() { this.loads++; }
    dispose() { this.disposed = true; }
  }
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useEffect(effect, deps) {
      const index = effectCursor++;
      if (!effects[index] || deps.some((value, i) => value !== effects[index].deps[i])) {
        scheduled.push(() => { effects[index]?.cleanup(); effects[index] = { deps, cleanup: effect() }; });
      }
    },
    useCallback(callback) { return callback; },
  };
  const { useReviewWorkspace } = loadModule("../src/hooks/useReviewWorkspace.ts", {
    react,
    "@/lib/reviewWorkspaceApi": { reviewWorkspaceApi: transport },
    "@/lib/workspaceReads": readsModule,
    "@/components/workspace/workspaceState": { ReviewWorkspaceController: Controller },
  });
  return { calls, controllers,
    render(id) { cursor = 0; effectCursor = 0; return useReviewWorkspace(id); },
    effects() { const pending = scheduled; scheduled = []; pending.forEach(effect => effect()); },
    unmount() { effects.forEach(effect => effect.cleanup()); },
  };
}

test("read retry preserves controller identity, drafts, confirmed questions and brief without reloading saved work", async () => {
  const h = hookHarness();
  h.render("fixture"); h.effects();
  h.calls[0].reject(new Error("source failed"));
  h.calls[1].resolve({ id: "fixture", filename: "synthetic.pdf" });
  await tick();
  const before = h.render("fixture"); h.effects();
  before.retrySource();
  h.calls[2].resolve(source);
  await tick();
  const after = h.render("fixture"); h.effects();
  assert.equal(after.controller, before.controller);
  assert.equal(after.state, before.state);
  assert.equal(after.state.localDrafts.finding, "unsaved review draft");
  assert.equal(after.state.localAskDrafts.finding, "unsent Ask");
  assert.equal(after.state.workspace.saved_questions[0], "confirmed saved question");
  assert.equal(after.state.briefDraft.priorities, "personal brief");
  assert.equal(after.controller.loads, 1);
  assert.equal(h.controllers.length, 1);
  assert.equal(after.sourceStatus, "ready");
  h.unmount();
});

test("document changes fence old data before effects and reject late previous-document results", async () => {
  const h = hookHarness();
  h.render("first"); h.effects();
  const transitioning = h.render("second");
  assert.equal(transitioning.controller, null);
  assert.equal(transitioning.state, null);
  assert.equal(transitioning.source, null);
  assert.equal(transitioning.filename, "Agreement");
  transitioning.retrySource();
  assert.equal(h.calls.length, 2);
  h.effects();
  assert.equal(h.controllers[0].disposed, true);
  assert.equal(h.calls[0].signal.aborted, true);
  assert.equal(h.calls[1].signal.aborted, true);
  h.calls[0].resolve(source);
  h.calls[1].resolve({ id: "first", filename: "old.pdf" });
  h.calls[2].resolve({ ...source, document_id: "second" });
  h.calls[3].resolve({ id: "second", filename: "new.pdf" });
  await tick();
  const state = h.render("second"); h.effects();
  assert.equal(state.filename, "new.pdf");
  assert.equal(state.source.document_id, "second");
  assert.equal(state.controller, h.controllers[1]);
  h.unmount();
});

test("workspace API read wrappers pass cancellation and one common timeout without writes", async () => {
  const calls = [];
  const { reviewWorkspaceApi, WORKSPACE_READ_TIMEOUT_MS } = loadModule("../src/lib/reviewWorkspaceApi.ts", {
    "@/lib/api": { default: { async get(...args) { calls.push(args); return { success: true, data: source }; } } },
  });
  const controller = new AbortController();
  await reviewWorkspaceApi.source("fixture", { signal: controller.signal });
  await reviewWorkspaceApi.document("fixture", { signal: controller.signal });
  assert.equal(calls.length, 2);
  for (const [, params, options] of calls) {
    assert.equal(params, undefined);
    assert.equal(options.signal, controller.signal);
    assert.equal(options.timeout, WORKSPACE_READ_TIMEOUT_MS);
  }
  assert.equal(calls[0][2].diagnosticScope, "workspace-source");
  assert.equal(calls[1][2].diagnosticScope, "workspace-metadata");
  await reviewWorkspaceApi.load("fixture");
  assert.equal(calls.length, 3);
  assert.equal(calls[2][2].timeout, WORKSPACE_READ_TIMEOUT_MS);
  assert.equal(calls[2][2].diagnosticScope, "workspace-state");
});
