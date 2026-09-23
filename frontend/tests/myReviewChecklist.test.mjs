import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

function load(path, imports = {}) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) { assert.ok(name in imports, name); return imports[name]; },
    fetch() { assert.fail("Checklist must not call paid APIs"); } });
  return exports;
}
const helpers = load("../src/components/workspace/workspaceState.ts");
function text(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node !== "object") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  return text(node.props?.children);
}
function nodes(node) {
  if (!React.isValidElement(node)) return [];
  return [node, ...(typeof node.type === "function" ? [node.type(node.props)] : React.Children.toArray(node.props.children)).flatMap(nodes)];
}
function harness() {
  const slots = []; let cursor = 0;
  const calls = [];
  const run = { id: "run-1", source_revision_id: "source-1", findings: [
    { id: "f1", title: "Exit plan", evidence: [] }, { id: "f2", title: "Liability", evidence: [] }, { id: "f3", title: "Payment", evidence: [] },
  ] };
  const personal = { ...helpers.emptyPersonal(), saved_questions: { f1: { text: "Saved question?" }, orphan: { text: "Wrong run" } },
    drafts: { f1: "Recoverable edited wording", f2: "Marker-only draft" }, markers: { f1: "revisit", f2: "reviewed_by_me", orphan: "revisit" } };
  const state = { workspace: { runs: [run] }, status: "saved", pending: 0, localDrafts: {}, reviewAction: { status: "idle" }, askAction: { status: "idle" } };
  const Export = () => null;
  const Modal = props => props.isOpen ? React.createElement("div", { role: "dialog" }, props.title, props.children, props.footer) : null;
  const props = { filename: "contract.pdf", run, personal, source: null, state,
    controller: {
      setDraft(...args) { calls.push(["draft", ...args]); state.localDrafts[helpers.draftKey(args[0], args[1])] = args[2]; },
      flushDrafts() { calls.push(["flush"]); }, saveQuestion(...args) { calls.push(["save", ...args]); },
      removeQuestion(...args) { calls.push(["remove", ...args]); }, enqueue(operation) { calls.push(["operation", JSON.parse(JSON.stringify(operation))]); },
    }, onFinding(id) { calls.push(["finding", id]); }, onSource(...args) { calls.push(["source", ...args]); }, onExplore() { calls.push(["explore"]); } };
  const { MyReview } = load("../src/components/workspace/MyReview.tsx", {
    react: { ...React, useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial;
      return [slots[index], update => { slots[index] = typeof update === "function" ? update(slots[index]) : update; }]; } },
    "lucide-react": { ArrowRight: () => null, FileText: () => null }, "@/components/ui/Modal": Modal,
    "./workspaceState": helpers, "./WorkspaceControls": { Action: props => React.createElement("button", { type: "button", ...props }),
      markerLabels: { not_marked: "Not marked", revisit: "Revisit", reviewed_by_me: "Reviewed by me" } },
    "./ReviewBriefExport": { ReviewBriefExport: Export }, "./MyReview.module.css": { review: "my-review" },
  });
  const tree = () => { cursor = 0; return MyReview(props); };
  const button = label => { const result = nodes(tree()).find(node => node.type === "button" && text(node) === label); assert.ok(result, label); return result; };
  return { props, calls, tree, button, click(label) { button(label).props.onClick(); },
    html: () => renderToStaticMarkup(tree()),
    textarea: () => nodes(tree()).find(node => node.type === "textarea"),
    export: () => nodes(tree()).find(node => node.type === Export).props,
    select: () => nodes(tree()).find(node => node.type === "select"),
  };
}

test("checklist filters all findings without filtering confirmed export or mutating saved data", () => {
  const h = harness(); const before = JSON.stringify(h.props.personal);
  assert.match(h.html(), /Exit plan/); assert.match(h.html(), /Liability/); assert.doesNotMatch(h.html(), /Payment/);
  h.click("All findings3"); assert.match(h.html(), /Payment/);
  assert.doesNotMatch(h.html(), /Wrong run|Recoverable edited wording|Marker-only draft/);
  h.click("Saved questions1");
  assert.match(h.html(), /Exit plan/); assert.doesNotMatch(h.html(), /Liability|Payment/);
  h.click("Revisit1");
  assert.match(h.html(), /Exit plan/); assert.doesNotMatch(h.html(), /Liability|Payment/);
  assert.equal(h.export().personal, h.props.personal); assert.equal(h.export().run, h.props.run);
  assert.equal(h.export().compact, true);
  h.click("All findings3"); assert.match(h.html(), /Liability/);
  assert.equal(JSON.stringify(h.props.personal), before); assert.deepEqual(h.calls, []);
});

test("inline edit resumes recovery draft and cancel preserves confirmed question and draft", () => {
  const h = harness(); h.click("Edit question");
  assert.equal(h.textarea().props.value, "Recoverable edited wording");
  h.textarea().props.onChange({ target: { value: "My new wording 🧭" } });
  assert.equal(h.textarea().props.value, "My new wording 🧭");
  h.click("Cancel editing");
  assert.equal(h.textarea(), undefined); assert.equal(h.props.personal.saved_questions.f1.text, "Saved question?");
  assert.match(h.html(), /saved question is unchanged; the draft remains available/);
  h.click("Edit question"); assert.equal(h.textarea().props.value, "My new wording 🧭");
  assert.deepEqual(h.calls, [["draft", "run-1", "f1", "My new wording 🧭"], ["flush"]]);
});

test("only deliberate save dispatches exact draft wording and does not optimistically replace confirmed work", () => {
  const h = harness(); h.click("Edit question"); h.click("Save question");
  assert.deepEqual(h.calls, [["save", "run-1", "f1", "Recoverable edited wording"]]);
  assert.equal(h.props.personal.saved_questions.f1.text, "Saved question?");
  assert.match(h.html(), /Question update requested/);
  const add = harness(); add.click("Add question");
  assert.equal(add.textarea().props.value, "Marker-only draft");
  add.click("Save question"); assert.deepEqual(add.calls, [["save", "run-1", "f2", "Marker-only draft"]]);
});

test("blank and unchanged question edits cannot be saved", () => {
  const h = harness(); h.click("Edit question");
  for (const value of ["", "  ", "Saved question?"]) {
    h.props.state.localDrafts[helpers.draftKey("run-1", "f1")] = value;
    assert.equal(h.button("Save question").props.disabled, true); h.click("Save question");
  }
  assert.deepEqual(h.calls, []);
});

test("removal requires an in-app confirmation and leaves saved work unchanged until confirmed server response", () => {
  const h = harness(); h.click("Remove saved question");
  assert.match(h.html(), /role="dialog"/); assert.match(h.html(), /existing draft stays available, including an empty draft/);
  assert.deepEqual(h.calls, []); h.click("Keep saved question"); assert.doesNotMatch(h.html(), /role="dialog"/);
  h.click("Remove saved question"); h.click("Remove question");
  assert.deepEqual(h.calls, [["remove", "run-1", "f1"]]);
  assert.equal(h.props.personal.saved_questions.f1.text, "Saved question?");
  assert.equal(h.props.personal.drafts.f1, "Recoverable edited wording"); assert.equal(h.props.personal.markers.f1, "revisit");
  assert.doesNotMatch(h.html(), /role="dialog"/);
});

test("direct markers are run-scoped and invalid enum values never dispatch", () => {
  const h = harness(); h.select().props.onChange({ target: { value: "reviewed_by_me" } });
  h.select().props.onChange({ target: { value: "invalid" } });
  assert.deepEqual(h.calls, [["operation", { type: "set_marker", run_id: "run-1", finding_id: "f1", marker: "reviewed_by_me" }]]);
  assert.equal(h.props.personal.markers.f1, "revisit");
});

test("loading, failed, conflict, pending and paid states fence direct mutation handlers", () => {
  for (const mutate of [
    ...["loading", "failed", "conflict", "review", "saving"].map(status => h => { h.props.state.status = status; }),
    h => { h.props.state.pending = 1; }, h => { h.props.state.reviewAction.status = "generating"; },
    h => { h.props.state.askAction.status = "uncertain"; }, h => { h.props.run.status = "processing"; },
    h => { h.props.state.workspace.ask_turns = [{ status: "processing" }]; },
  ]) {
    const h = harness(); h.click("Edit question"); h.click("Remove saved question"); mutate(h);
    assert.equal(h.button("Save question").props.disabled, true); h.click("Save question");
    assert.equal(h.button("Remove question").props.disabled, true); h.click("Remove question");
    assert.equal(h.select().props.disabled, true); h.select().props.onChange({ target: { value: "reviewed_by_me" } });
    assert.deepEqual(h.calls, [], mutate.toString());
  }
});

test("no run hides stale personal work and empty filters remain explicit", () => {
  const h = harness(); h.props.run = null;
  assert.match(h.html(), /No review run yet/); assert.doesNotMatch(h.html(), /Saved question\?|Wrong run/);
  const empty = harness(); empty.props.personal.markers = {}; empty.click("Revisit0");
  assert.match(empty.html(), /Nothing marked for revisit/);
  empty.props.personal.saved_questions = {}; empty.click("Saved questions0"); assert.match(empty.html(), /No saved questions in this run/);
});

test("server removal reveals Add question and the preserved draft without restoring saved/export state", () => {
  const h = harness(); h.click("Remove saved question"); h.click("Remove question");
  delete h.props.personal.saved_questions.f1;
  h.click("Add question"); assert.equal(h.textarea().props.value, "Recoverable edited wording");
  assert.equal(h.export().personal.saved_questions.f1, undefined);
  assert.equal(h.props.personal.markers.f1, "revisit");
});
