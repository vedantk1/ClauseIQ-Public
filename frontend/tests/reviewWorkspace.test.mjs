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
    async generate(documentId, revision, requestId, modelId) {
      calls.push({ documentId, revision, requestId, modelId, generate: true });
      if (!server.runs.some(run => run.id === requestId)) {
        server.revision += 1;
        server.runs.push({ ...clone(server.runs[0]), id: requestId, kind: "ai", status: "ready", context: clone(server.brief) });
        server.personal[requestId] = clone(state.emptyPersonal());
      }
      return clone(server);
    },
    async interrupt(documentId, revision, runId) {
      calls.push({ documentId, revision, runId, interrupt: true });
      server.revision += 1;
      server.runs.find(run => run.id === runId).status = "interrupted";
      return clone(server);
    },
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
    async post(path, body, options) { calls.push({ path, body, options }); return { success: true, data: initial() }; } };
  const { reviewWorkspaceApi } = loadModule("../src/lib/reviewWorkspaceApi.ts", { "@/lib/api": { default: api, __esModule: true } });
  await reviewWorkspaceApi.load("a/b");
  const operation = { type: "set_brief", brief };
  await assert.rejects(reviewWorkspaceApi.update("a/b", 7, operation), error => error.code === "REVISION_CONFLICT" && error.message === "Changed elsewhere");
  await reviewWorkspaceApi.fixture("a/b", 8);
  await reviewWorkspaceApi.generate("a/b", 9, "request-1", "test-model");
  await reviewWorkspaceApi.interrupt("a/b", 10, "run/a");
  assert.equal(calls[0], "/documents/a%2Fb/review-workspace");
  assert.equal(calls[1].body.expected_revision, 7);
  assert.equal(calls[1].body.operation, operation);
  assert.equal(calls[2].body.expected_revision, 8);
  assert.deepEqual(clone(calls[3].body), { expected_revision: 9, request_id: "request-1", model_id: "test-model" });
  assert.equal(calls[3].options.timeout, 210000);
  assert.equal(calls[4].path, "/documents/a%2Fb/review-workspace/runs/run%2Fa/interrupt");
  assert.equal(calls[4].body.expected_revision, 10);
});

const stateHelpers = loadModule("../src/components/workspace/workspaceState.ts");
const controls = loadModule("../src/components/workspace/WorkspaceControls.tsx", { react: React, "./workspaceState": stateHelpers });
const generationControls = loadModule("../src/components/workspace/ReviewGenerationControls.tsx", {
  react: React, "./workspaceState": stateHelpers, "./WorkspaceControls": controls,
  "@/components/ui/Modal": () => null,
  "@/context/WorkspaceContext": { useWorkspace: () => ({ settings: { has_api_key: true, model_id: "test-model" }, isLoading: false, error: null, refresh() {} }) },
});

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
    "./EvidenceSourcePane": { EvidenceSourcePane: () => null, DocumentSourceView: () => null, EvidenceList: () => null },
    "./ReviewGenerationControls": generationControls,
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

test("starting review confirms dirty brief and all draft timers before one paid request", async () => {
  const h = harness(); await h.controller.load();
  h.controller.setBriefDraft(customer);
  h.controller.setDraft("run-1", "finding-1", "Keep my wording");
  await h.controller.startReview("test-model", "attempt-1");
  assert.deepEqual(h.calls.map(call => call.operation?.type || "generate"), ["set_brief", "set_draft", "generate"]);
  assert.equal(h.calls[2].revision, 2);
  assert.equal(h.controller.getSnapshot().reviewAction.status, "idle");
  assert.deepEqual(h.server().runs.at(-1).context, customer);
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "Keep my wording");
  assert.deepEqual(h.server().personal["attempt-1"].drafts, {});
});

test("double click cannot reserve two paid attempts while saves or generation are in flight", async () => {
  const h = harness({ delayed: true }); await h.controller.load();
  h.controller.setBriefDraft(customer);
  const first = h.controller.startReview("test-model", "attempt-1");
  const duplicate = h.controller.startReview("test-model", "attempt-2");
  assert.equal(h.controller.getSnapshot().reviewAction.status, "preparing");
  assert.equal(h.calls.length, 1);
  h.calls[0].finish(); await first; await duplicate;
  assert.equal(h.calls.filter(call => call.generate).length, 1);
  assert.equal(h.calls.find(call => call.generate).requestId, "attempt-1");
});

test("failed or conflicted brief save blocks paid work and keeps the unsaved brief", async () => {
  for (const code of ["NETWORK_ERROR", "REVISION_CONFLICT"]) {
    const h = harness(); await h.controller.load();
    h.controller.setBriefDraft(customer);
    h.failNext(Object.assign(new Error("Not saved"), { code }));
    await h.controller.startReview("test-model", "attempt-1");
    assert.equal(h.calls.filter(call => call.generate).length, 0);
    assert.equal(h.controller.getSnapshot().reviewAction.status, "idle");
    assert.match(h.controller.getSnapshot().reviewAction.error, /not started/);
    assert.equal(h.controller.getSnapshot().briefDraft.priorities, customer.priorities);
  }
});

test("editing the brief while its save is pending does not send a stale perspective", async () => {
  const h = harness({ delayed: true }); await h.controller.load();
  h.controller.setBriefDraft(customer);
  const start = h.controller.startReview("test-model", "attempt-1");
  h.controller.setBriefDraft({ ...customer, perspective: "provider" });
  h.calls[0].finish(); await start;
  assert.equal(h.calls.filter(call => call.generate).length, 0);
  assert.equal(h.controller.getSnapshot().briefDraft.perspective, "provider");
});

test("provider response preserves edits made meanwhile and requires explicit application", async () => {
  const h = harness(); await h.controller.load();
  const generate = h.transport.generate;
  let finish;
  h.transport.generate = (...args) => new Promise(resolve => { finish = async () => resolve(await generate(...args)); });
  const start = h.controller.startReview("test-model", "attempt-1"); await settle();
  assert.equal(h.controller.getSnapshot().reviewAction.status, "generating");
  h.controller.setDraft("run-1", "finding-1", "Edited while generating"); h.timers();
  h.controller.setBriefDraft({ ...brief, priorities: "New local priorities" });
  assert.equal(h.calls.length, 0);
  finish(); await start;
  assert.equal(h.controller.getSnapshot().status, "review");
  assert.equal(h.controller.getSnapshot().localDrafts[h.state.draftKey("run-1", "finding-1")], "Edited while generating");
  assert.equal(h.controller.getSnapshot().briefDraft.priorities, "New local priorities");
  assert.equal(h.calls.length, 1);
  h.controller.retryPending(); await settle();
  assert.equal(h.server().personal["run-1"].drafts["finding-1"], "Edited while generating");
  assert.equal(h.server().runs.length, 2);
});

test("lost paid response never joins ordinary retry queue; GET recovers the same recorded run", async () => {
  const h = harness(); await h.controller.load();
  const generate = h.transport.generate;
  h.transport.generate = async (...args) => {
    await generate(...args);
    throw Object.assign(new Error("Response lost"), { code: "NETWORK_ERROR" });
  };
  await h.controller.startReview("test-model", "attempt-1");
  assert.equal(h.controller.getSnapshot().reviewAction.status, "uncertain");
  h.controller.retryPending(); await settle();
  await h.controller.startReview("test-model", "attempt-2");
  await h.controller.retryReviewRequest();
  assert.equal(h.calls.length, 1);
  await h.controller.reloadSaved();
  assert.equal(h.controller.getSnapshot().reviewAction.status, "idle");
  assert.equal(h.controller.getSnapshot().workspace.runs.at(-1).id, "attempt-1");
  assert.equal(h.calls.length, 1);
});

test("an unrecorded uncertain attempt requires read-only refresh and explicit same-id replay", async () => {
  const h = harness(); await h.controller.load();
  const generate = h.transport.generate;
  const attempts = [];
  let fail = true;
  h.transport.generate = async (...args) => {
    attempts.push(args);
    if (fail) { fail = false; throw new Error("Connection failed"); }
    return generate(...args);
  };
  await h.controller.startReview("original-model", "attempt-1");
  await h.controller.retryReviewRequest();
  assert.equal(attempts.length, 1);
  await h.controller.reloadSaved();
  assert.equal(h.controller.getSnapshot().reviewAction.canRetryRequest, true);
  h.controller.setBriefDraft(customer);
  h.controller.retryPending(); await settle();
  assert.equal(attempts.length, 1);
  await h.controller.retryReviewRequest();
  assert.deepEqual(attempts[1], attempts[0]);
  assert.equal(h.controller.getSnapshot().briefDraft.perspective, "customer");
  assert.equal(h.server().runs.length, 2);
});

test("definitive preflight rejections permit a new attempt only after saved-state refresh", async () => {
  for (const code of ["REVISION_CONFLICT", "REVIEW_MODEL_CHANGED", "API_KEY_REQUIRED", "REVIEW_INPUT_REJECTED"]) {
    const h = harness(); await h.controller.load();
    h.transport.generate = async () => { throw Object.assign(new Error("Preflight rejected"), { code }); };
    await h.controller.startReview("test-model", "attempt-1");
    assert.equal(h.controller.getSnapshot().reviewAction.requestRejected, true);
    assert.equal(h.controller.getSnapshot().reviewAction.status, "uncertain");
    await h.controller.reloadSaved();
    assert.equal(h.controller.getSnapshot().reviewAction.status, "idle");
    assert.equal(h.controller.getSnapshot().reviewAction.canRetryRequest, false);
  }
});

test("unconfirmed final save never becomes a safe preflight failure", async () => {
  const h = harness(); await h.controller.load();
  h.transport.generate = async () => { throw Object.assign(new Error("Result save unconfirmed"), { code: "REVIEW_SAVE_UNCONFIRMED" }); };
  await h.controller.startReview("test-model", "attempt-1");
  await h.controller.reloadSaved();
  assert.equal(h.controller.getSnapshot().reviewAction.status, "uncertain");
  assert.equal(h.controller.getSnapshot().reviewAction.requestRejected, false);
});

test("reopening a processing run never generates, blocks a new attempt, and can be interrupted explicitly", async () => {
  const h = harness();
  const current = h.server(); current.runs[0].kind = "ai"; current.runs[0].status = "processing";
  await h.controller.load();
  await h.controller.startReview("test-model", "attempt-1");
  assert.equal(h.calls.length, 0);
  await h.controller.reloadSaved();
  assert.equal(h.calls.length, 0);
  await h.controller.interruptRun("run-1");
  assert.equal(h.calls[0].interrupt, true);
  assert.equal(h.controller.getSnapshot().workspace.runs[0].status, "interrupted");
});

test("recovered processing result keeps local drafts frozen for explicit compare and apply", async () => {
  const h = harness(); await h.controller.load();
  h.transport.generate = async (_doc, _revision, requestId) => {
    const server = h.server(); server.revision += 1;
    server.runs.push({ ...clone(server.runs[0]), id: requestId, kind: "ai", status: "processing" });
    throw new Error("Outcome unavailable");
  };
  await h.controller.startReview("test-model", "attempt-1");
  h.controller.setDraft("run-1", "finding-1", "Local after timeout");
  await h.controller.reloadSaved();
  assert.equal(h.controller.getSnapshot().status, "review");
  assert.equal(h.controller.getSnapshot().reviewAction.status, "idle");
  assert.equal(h.calls.length, 0);
  assert.equal(h.controller.getSnapshot().localDrafts[h.state.draftKey("run-1", "finding-1")], "Local after timeout");
});

test("run labels distinguish legacy fixtures and incomplete, failed, interrupted and processing AI runs", () => {
  assert.equal(stateHelpers.runLabel(initial().runs[0]), "Synthetic example — available");
  for (const status of ["incomplete", "failed", "interrupted", "processing"]) {
    assert.equal(stateHelpers.runLabel({ ...initial().runs[0], kind: "ai", status }), `AI review — ${status}`);
  }
});

test("empty-run Findings navigation cannot enqueue an invalid position; other views clear dangling evidence", () => {
  const run = { ...initial().runs[0], findings: [] };
  assert.equal(stateHelpers.safeReviewPosition(run, "findings", null, null), null);
  assert.equal(stateHelpers.safeReviewPosition(run, "findings", "old-finding", "old-span"), null);
  assert.deepEqual(clone(stateHelpers.safeReviewPosition(run, "document", "old-finding", "old-span")), {
    view: "document", finding_id: null, evidence_span_id: null,
  });
});

test("new-run positions never reuse an evidence span from an unrelated finding", () => {
  const run = initial().runs[0];
  run.findings[0].evidence = [{ span_id: "current-span" }];
  assert.deepEqual(clone(stateHelpers.safeReviewPosition(run, "findings", "finding-1", "old-span")), {
    view: "findings", finding_id: "finding-1", evidence_span_id: null,
  });
  assert.equal(stateHelpers.safeReviewPosition(run, "document", "finding-1", "current-span").evidence_span_id, "current-span");
});

test("AI overview render exposes incomplete status, provenance, coverage and retained old run selection", () => {
  const workspace = initial();
  workspace.runs.push({ ...clone(workspace.runs[0]), id: "run-2", kind: "ai", status: "incomplete", context: brief,
    overview_items: [{ text: "Source-backed overview", evidence: [] }],
    coverage: { page_count: 3, extracted_pages: [1, 3], omitted_pages: [2], input_scope: "all_extracted_text", limitations: ["Page 2 has no extractable text."] },
    generation: { model_id: "test-model", endpoint: "chat.completions", reasoning_effort: "low", prompt_version: "review-v1", schema_version: "review-v1", extraction_version: "extract-v1", estimated_input_tokens: 1000, max_completion_tokens: 2000, usage: null, duration_ms: 2000 },
  });
  const html = renderWorkspace("overview", { workspace });
  assert.match(html, /AI review — incomplete/);
  assert.match(html, /This review is incomplete/);
  assert.match(html, /Source-backed overview/);
  assert.match(html, /Pages omitted from review input: 2/);
  assert.match(html, /Synthetic example — available/);
  assert.match(html, /Prompt: review-v1/);
  assert.match(html, /usage unavailable; this does not mean no charge/);
  assert.doesNotMatch(html, /Example agreement overview/);
});

test("not-found findings expose reviewed scope and do not imply absence from missing materials", () => {
  const workspace = initial(); workspace.runs[0].kind = "ai";
  workspace.runs[0].findings[0].basis = "not_found";
  workspace.runs[0].findings[0].coverage_basis = "Pages 1 and 3 only";
  const html = renderWorkspace("findings", { workspace });
  assert.match(html, /Not found within the reviewed scope/);
  assert.match(html, /Pages 1 and 3 only/);
  assert.match(html, /not proof of absence/);
  assert.match(html, /AI-suggested wording/);
});

test("uncertain request controls expose read-only recovery and charge warning, not generic paid auto-retry", () => {
  const state = { workspace: initial(), status: "saved", pending: 0, briefDraft: null,
    reviewAction: { status: "uncertain", error: "Outcome unknown", canRetryRequest: false } };
  const html = renderToStaticMarkup(React.createElement(generationControls.ReviewGenerationControls, { state, controller: {}, sourceReady: true, onSettings() {} }));
  assert.match(html, /Check saved review state/);
  assert.match(html, /charges may apply/);
  assert.doesNotMatch(html, /Retry this request with the same ID/);
  assert.match(html, /Selected model/);
  assert.match(html, /test-model/);
});
