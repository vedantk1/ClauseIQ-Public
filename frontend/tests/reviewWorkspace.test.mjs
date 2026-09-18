import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

function loadModule(path, imports = {}, globals = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, React, Error, console, setTimeout, clearTimeout, ...globals,
    require(name) { assert.ok(name in imports, `Unexpected dependency: ${name}`); return imports[name]; },
  });
  return exports;
}

const clone = value => JSON.parse(JSON.stringify(value));
const brief = { perspective: "neutral", role: "", priorities: "" };
const customer = { perspective: "customer", role: "Example Customer", priorities: "Exit continuity" };
function initial() {
  return { document_id: "doc-1", source_revision_id: "source-1", revision: 0, brief: clone(brief), fixture_available: true,
    runs: [{ id: "run-1", kind: "fixture", source_revision_id: "source-1", created_at: "2026-01-01", context: clone(customer),
      fixture_version: "fixture-v1", overview: "Selected synthetic overview", findings: [{ id: "finding-1", title: "Archive exit",
        facts: "A conditional extension.", interpretation: "This may preserve continuity.", uncertainty: "No notice date supplied.",
        next_step: "Check scope.", suggested_question: "Can the Archive extension be confirmed?", evidence: [] }] }],
    personal: { "run-1": { drafts: {}, saved_questions: {}, markers: {}, opened_finding_ids: [],
      position: { view: "findings", finding_id: "finding-1", evidence_span_id: null } } } };
}

function apply(workspace, operation) {
  const next = clone(workspace);
  next.revision += 1;
  if (operation.type === "set_brief") next.brief = clone(operation.brief);
  else {
    const personal = next.personal[operation.run_id];
    if (operation.type === "set_draft") personal.drafts[operation.finding_id] = operation.text;
    if (operation.type === "save_question") personal.saved_questions[operation.finding_id] = {
      id: personal.saved_questions[operation.finding_id]?.id || "question-1", text: operation.text, saved_at: "2026-01-01",
    };
    if (operation.type === "set_marker") personal.markers[operation.finding_id] = operation.marker;
    if (operation.type === "set_position") personal.position = clone(operation.position);
  }
  return next;
}

function harness({ delayed = false } = {}) {
  let server = initial();
  let timerId = 0;
  const timers = new Map();
  const calls = [];
  let failure = null;
  const state = loadModule("../src/components/workspace/workspaceState.ts", {}, {
    setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const transport = {
    async load() { return clone(server); },
    async update(documentId, revision, operation) {
      const call = { documentId, revision, operation: clone(operation) }; calls.push(call);
      if (failure) { const error = failure; failure = null; throw error; }
      const commit = () => {
        if (revision !== server.revision) throw Object.assign(new Error("Changed elsewhere"), { code: "REVISION_CONFLICT" });
        server = apply(server, operation); return clone(server);
      };
      if (!delayed) return commit();
      return new Promise((resolve, reject) => { call.finish = () => { try { resolve(commit()); } catch (error) { reject(error); } }; });
    },
    async fixture(documentId, revision) { calls.push({ documentId, revision, fixture: true }); return clone(server); },
  };
  const controller = new state.ReviewWorkspaceController("doc-1", transport, 500);
  return { state, controller, calls, transport,
    timers: () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(callback => callback()); },
    failNext(error) { failure = error; }, server: () => server, setServer(value) { server = value; },
  };
}
const settle = async () => { for (let index = 0; index < 12; index += 1) await Promise.resolve(); };

test("drafts debounce to latest text, show pending immediately and never add saved questions", async () => {
  const h = harness(); await h.controller.load();
  h.controller.setDraft("run-1", "finding-1", "a");
  h.controller.setDraft("run-1", "finding-1", "latest");
  assert.equal(h.calls.length, 0);
  assert.equal(h.controller.getSnapshot().pending, 1);
  assert.equal(h.state.hasUnconfirmedChanges(h.controller.getSnapshot()), true);
  h.timers(); await settle();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].operation.text, "latest");
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "latest");
  assert.deepEqual(h.server().personal["run-1"].saved_questions, {});
  assert.equal(h.state.hasUnconfirmedChanges(h.controller.getSnapshot()), false);
});

test("writes are serialized with confirmed revisions and delayed replies cannot erase newer wording", async () => {
  const h = harness({ delayed: true }); await h.controller.load();
  h.controller.setDraft("run-1", "finding-1", "first"); h.timers();
  h.controller.setDraft("run-1", "finding-1", "newer"); h.timers();
  assert.equal(h.calls.length, 1);
  h.calls[0].finish(); await settle();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls.map(call => call.revision), [0, 1]);
  assert.equal(h.controller.getSnapshot().localDrafts[h.state.draftKey("run-1", "finding-1")], "newer");
  assert.equal(h.controller.getSnapshot().workspace.personal["run-1"].drafts["finding-1"], "first");
  h.calls[1].finish(); await settle();
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "newer");
  assert.equal(h.controller.getSnapshot().pending, 0);
});

test("question updates keep the old saved wording until confirmed and do not create duplicate entries", async () => {
  const h = harness({ delayed: true });
  h.setServer(apply(h.server(), { type: "save_question", run_id: "run-1", finding_id: "finding-1", text: "Saved before" }));
  await h.controller.load();
  h.controller.saveQuestion("run-1", "finding-1", "Explicit new question");
  assert.equal(h.controller.getSnapshot().workspace.personal["run-1"].saved_questions["finding-1"].text, "Saved before");
  h.calls[0].finish(); await settle();
  assert.equal(h.calls[1].operation.type, "save_question");
  assert.equal(h.controller.getSnapshot().workspace.personal["run-1"].saved_questions["finding-1"].text, "Saved before");
  h.controller.setDraft("run-1", "finding-1", "A still newer draft");
  h.calls[1].finish(); await settle();
  assert.equal(h.server().personal["run-1"].saved_questions["finding-1"].text, "Explicit new question");
  assert.equal(Object.keys(h.server().personal["run-1"].saved_questions).length, 1);
  assert.equal(h.server().personal["run-1"].saved_questions["finding-1"].id, "question-1");
  assert.equal(h.controller.getSnapshot().localDrafts[h.state.draftKey("run-1", "finding-1")], "A still newer draft");
});

test("conflicts freeze queued changes; reload preserves local drafts and requires explicit apply", async () => {
  const h = harness(); await h.controller.load();
  h.setServer(apply(h.server(), { type: "set_draft", run_id: "run-1", finding_id: "finding-1", text: "Other tab wording" }));
  h.controller.setDraft("run-1", "finding-1", "My wording"); h.timers(); await settle();
  assert.equal(h.controller.getSnapshot().status, "conflict");
  h.controller.enqueue({ type: "set_marker", run_id: "run-1", finding_id: "finding-1", marker: "revisit" });
  h.controller.retryPending(); await settle();
  assert.equal(h.calls.length, 1);
  await h.controller.reloadSaved(); await settle();
  const snapshot = h.controller.getSnapshot();
  assert.equal(snapshot.status, "review");
  assert.equal(snapshot.workspace.personal["run-1"].drafts["finding-1"], "Other tab wording");
  assert.equal(snapshot.localDrafts[h.state.draftKey("run-1", "finding-1")], "My wording");
  assert.equal(h.calls.length, 1);
  h.controller.retryPending(); await settle();
  assert.deepEqual(h.calls.map(call => call.revision), [0, 1, 2]);
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "My wording");
  assert.equal(h.server().personal["run-1"].markers["finding-1"], "revisit");
});

test("network failures retain wording and explicit retry still uses the last confirmed revision", async () => {
  const h = harness(); await h.controller.load();
  h.failNext(Object.assign(new Error("Network unavailable"), { code: "NETWORK_ERROR" }));
  h.controller.setDraft("run-1", "finding-1", "Keep me"); h.timers(); await settle();
  assert.equal(h.controller.getSnapshot().status, "failed");
  assert.equal(h.controller.getSnapshot().localDrafts[h.state.draftKey("run-1", "finding-1")], "Keep me");
  h.controller.retryPending(); await settle();
  assert.deepEqual(h.calls.map(call => call.revision), [0, 0]);
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "Keep me");
});

test("a committed write with a lost response cannot silently replay or duplicate a saved question", async () => {
  const h = harness(); await h.controller.load();
  const update = h.transport.update;
  let loseResponse = true;
  h.transport.update = async (...args) => {
    const result = await update(...args);
    if (loseResponse) { loseResponse = false; throw Object.assign(new Error("Response lost"), { code: "NETWORK_ERROR" }); }
    return result;
  };
  h.controller.saveQuestion("run-1", "finding-1", "Keep one question"); await settle();
  assert.equal(h.server().revision, 1);
  assert.equal(h.controller.getSnapshot().workspace.revision, 0);
  h.controller.retryPending(); await settle();
  assert.equal(h.controller.getSnapshot().status, "conflict");
  assert.equal(h.server().revision, 1);
  await h.controller.reloadSaved();
  assert.equal(h.controller.getSnapshot().status, "review");
  h.controller.retryPending(); await settle();
  assert.equal(Object.keys(h.server().personal["run-1"].saved_questions).length, 1);
  assert.equal(h.server().personal["run-1"].saved_questions["finding-1"].text, "Keep one question");
});

test("flushing before a guarded leave sends pending drafts and does not mark them confirmed early", async () => {
  const h = harness({ delayed: true }); await h.controller.load();
  h.controller.setDraft("run-1", "finding-1", "Before leaving");
  assert.equal(h.state.hasUnconfirmedChanges(h.controller.getSnapshot()), true);
  h.controller.flushDrafts();
  assert.equal(h.calls.length, 1);
  assert.equal(h.state.hasUnconfirmedChanges(h.controller.getSnapshot()), true);
  h.calls[0].finish(); await settle();
  assert.equal(h.state.hasUnconfirmedChanges(h.controller.getSnapshot()), false);
});

test("reloading does not flush draft timers into an automatic write or erase unsaved brief edits", async () => {
  const h = harness(); await h.controller.load();
  h.controller.setDraft("run-1", "finding-1", "Unconfirmed");
  h.controller.setBriefDraft({ ...brief, priorities: "My unsaved priority" });
  await h.controller.reloadSaved(); await settle();
  assert.equal(h.calls.length, 0);
  assert.equal(h.controller.getSnapshot().status, "review");
  assert.equal(h.controller.getSnapshot().briefDraft.priorities, "My unsaved priority");
});

test("disposing a workspace cancels its debounce and cannot write into another document", async () => {
  const h = harness(); await h.controller.load();
  h.controller.setDraft("run-1", "finding-1", "Unconfirmed before close");
  h.controller.dispose(); h.timers(); await settle();
  assert.equal(h.calls.length, 0);
});

test("source matching requires exact revision, span, page and Unicode code-point slice", () => {
  const { evidenceMatches } = harness().state;
  const source = { id: "doc-1", source_revision_id: "source-1", source_extraction: { pages: [{ page_number: 2, text: "🙂 obligation", spans: [{ id: "span-1", start: 2, end: 12, text: "obligation" }] }] } };
  const evidence = { source_revision_id: "source-1", page_number: 2, span_id: "span-1", quote: "obligation", label: "Rule" };
  assert.equal(evidenceMatches(evidence, source), true);
  for (const change of [{ source_revision_id: "other" }, { page_number: 1 }, { span_id: "missing" }, { quote: "Obligation" }]) {
    assert.equal(evidenceMatches({ ...evidence, ...change }, source), false);
  }
});

test("unmatched evidence renders an explicit limitation and cannot jump to a guessed location", () => {
  const helpers = harness().state;
  const controlsForEvidence = loadModule("../src/components/workspace/WorkspaceControls.tsx", {
    react: React, "./workspaceState": helpers,
  });
  const { EvidenceSourcePane } = loadModule("../src/components/workspace/EvidenceSourcePane.tsx", {
    react: React, "@/components/PDFViewer": () => null, "./workspaceState": helpers,
    "./WorkspaceControls": controlsForEvidence,
  });
  const finding = { ...initial().runs[0].findings[0], evidence: [{ source_revision_id: "source-1",
    span_id: "not-found", page_number: 25, quote: "Unmatched excerpt", label: "Possible exception" }] };
  const html = renderToStaticMarkup(React.createElement(EvidenceSourcePane, { finding, source: null, onOpen() {} }));
  assert.match(html, /Quote could not be matched/);
  assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /Finding verified/);
});

test("API mutations carry expected revisions, preserve errors and encode document identity", async () => {
  const calls = [];
  const api = { async get(path) { calls.push(path); return { success: true, data: initial() }; },
    async put(path, body) { calls.push({ path, body }); return { success: false, error: { code: "REVISION_CONFLICT", message: "Changed elsewhere" } }; },
    async post(path, body) { calls.push({ path, body }); return { success: true, data: initial() }; } };
  const { reviewWorkspaceApi } = loadModule("../src/lib/reviewWorkspaceApi.ts", { "@/lib/api": { default: api, __esModule: true } });
  await reviewWorkspaceApi.load("a/b");
  const operation = { type: "set_brief", brief };
  await assert.rejects(reviewWorkspaceApi.update("a/b", 7, operation), error => error.code === "REVISION_CONFLICT" && error.message === "Changed elsewhere");
  await reviewWorkspaceApi.fixture("a/b", 8);
  assert.equal(calls[0], "/documents/a%2Fb/review-workspace");
  assert.equal(calls[1].body.expected_revision, 7);
  assert.equal(calls[1].body.operation, operation);
  assert.equal(calls[2].body.expected_revision, 8);
});

const stateHelpers = loadModule("../src/components/workspace/workspaceState.ts");
const controls = loadModule("../src/components/workspace/WorkspaceControls.tsx", { react: React, "./workspaceState": stateHelpers });

test("saving feedback is honest during debounce, brief editing and conflict recovery", () => {
  const savedState = { workspace: initial(), status: "saved", pending: 0, localDrafts: {}, briefDraft: null, error: null };
  function html(state) { return renderToStaticMarkup(React.createElement(controls.SaveFeedback, { state, onReload() {}, onRetry() {} })); }
  assert.match(html({ ...savedState, pending: 1 }), /Saving changes/);
  assert.match(html({ ...savedState, briefDraft: customer }), /Brief edits have not been saved/);
  assert.match(html({ ...savedState, status: "conflict" }), /No conflicting edits were applied/);
  assert.match(html({ ...savedState, status: "review" }), /Apply my pending changes/);
});

function renderWorkspace(view, overrides = {}) {
  const workspace = initial();
  workspace.personal["run-1"].opened_finding_ids = ["finding-1"];
  workspace.personal["run-1"].saved_questions["finding-1"] = { id: "question-1", text: "Previously saved question", saved_at: "2026-01-01" };
  workspace.personal["run-1"].drafts["finding-1"] = "A recovered draft";
  const state = { workspace, status: "saved", pending: 0, localDrafts: {}, briefDraft: null, error: null, ...overrides };
  const component = loadModule("../src/components/workspace/ReviewWorkspace.tsx", {
    react: { ...React, useState: value => [value === "overview" ? view : value, () => {}] },
    "next/link": ({ children, ...props }) => React.createElement("a", props, children),
    "next/navigation": { useRouter: () => ({ push() {} }) },
    "@/components/ui/Modal": () => null,
    "@/hooks/useReviewWorkspace": { useReviewWorkspace: () => ({ controller: {}, state, source: null, filename: "synthetic.pdf", sourceError: null }) },
    "./workspaceState": stateHelpers, "./WorkspaceControls": controls,
    "./EvidenceSourcePane": { EvidenceSourcePane: () => null, DocumentSourceView: () => null },
  }).default;
  return renderToStaticMarkup(React.createElement(component, { documentId: "doc-1" }));
}

test("workspace render labels fixture and context mismatch; reopening defaults to overview with explicit resume", () => {
  const html = renderWorkspace("overview");
  assert.match(html, /Synthetic example — not an AI-generated review/);
  assert.match(html, /saved brief differs/);
  assert.match(html, /Continue from saved position/);
  assert.match(html, /Last saved position: Findings/);
  assert.match(html, /not review completeness/);
});

test("finding render keeps draft and saved question distinct and does not turn opened into reviewed", () => {
  const html = renderWorkspace("findings");
  assert.match(html, /A recovered draft/);
  assert.match(html, /Previously saved question/);
  assert.match(html, /Not marked · Opened/);
  assert.match(html, /Ask — not available yet/);
  assert.match(html, /No answer will be generated here/);
});

test("My review contains confirmed saved questions and independent marker groups, not draft wording", () => {
  const html = renderWorkspace("my_review");
  assert.match(html, /Previously saved question/);
  assert.doesNotMatch(html, /A recovered draft/);
  assert.match(html, /Revisit/);
  assert.match(html, /Reviewed by me/);
  assert.match(html, /Nothing marked here yet/);
});
