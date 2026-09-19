import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { appHeaderHarness } from "./appHeaderHarness.mjs";

function loadModule(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, React,
    require(name) { assert.ok(name in imports, `Unexpected dependency: ${name}`); return imports[name]; },
  });
  return exports;
}

const stateHelpers = loadModule("../src/components/workspace/workspaceState.ts");
const controls = loadModule("../src/components/workspace/WorkspaceControls.tsx", {
  react: React, "./workspaceState": stateHelpers,
});
const generation = loadModule("../src/components/workspace/ReviewGenerationControls.tsx", {
  react: React, "./workspaceState": stateHelpers, "./WorkspaceControls": controls,
  "@/components/ui/Modal": () => null, "@/context/WorkspaceContext": { useWorkspace: () => ({}) },
});
const brief = { perspective: "provider", role: "Supplier", priorities: "Retain work" };
const run = { id: "example-1", kind: "fixture", status: "ready", created_at: "2026-01-01",
  context: { perspective: "customer", role: "Example Customer", priorities: "Exit" }, findings: [], overview: "" };
const saved = { workspace: { brief }, status: "saved", pending: 0, briefDraft: null,
  localDrafts: {}, localAskDrafts: {}, error: null, reviewAction: { status: "idle" }, askAction: { status: "idle" } };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("compact save feedback hides only a confirmed clean save", () => {
  const html = state => render(controls.SaveFeedback, { state, compact: true, onReload() {}, onRetry() {} });
  assert.equal(html(saved), "");
  assert.match(html({ ...saved, pending: 1 }), /Saving changes/);
  assert.match(html({ ...saved, status: "saving" }), /Saving changes/);
  assert.match(html({ ...saved, status: "loading" }), /Loading saved workspace/);
  assert.match(html({ ...saved, briefDraft: { ...brief, priorities: "A new priority" } }), /Brief edits have not been saved/);
  assert.match(html({ ...saved, status: "failed" }), /Retry pending changes/);
  assert.match(html({ ...saved, status: "conflict" }), /Reload saved state; keep my drafts/);
  assert.doesNotMatch(html({ ...saved, status: "conflict" }), /Retry pending changes/);
  assert.match(html({ ...saved, status: "review" }), /Apply my pending changes/);
  assert.match(html({ ...saved, pending: 1, askAction: { status: "uncertain" } }), /waiting while the AI outcome is resolved/);
});

test("compact save indicator never presents pending or conflicting edits as saved", () => {
  const html = state => render(controls.WorkspaceSaveIndicator, { state });
  assert.match(html(saved), /Saved locally/);
  for (const state of [
    { ...saved, pending: 1 }, { ...saved, status: "saving" }, { ...saved, status: "conflict" },
    { ...saved, status: "review" }, { ...saved, status: "failed" }, { ...saved, status: "loading" },
    { ...saved, briefDraft: { ...brief, priorities: "Changed" } }, { ...saved, workspace: null },
  ]) assert.doesNotMatch(html(state), />Saved locally</);
});

function headerHarness(theme = "black") {
  let toggles = 0;
  const module = loadModule("../src/components/workspace/WorkspaceHeader.tsx", {
    react: React, "./workspaceState": stateHelpers, "./WorkspaceControls": controls,
    "@/components/shell/AppHeader": appHeaderHarness({ nextThemeLabel: theme === "black" ? "Graphite" : "Black", toggleTheme() { toggles += 1; } }),
  });
  return { Header: module.WorkspaceHeader, toggles: () => toggles };
}

function nodes(node) {
  if (!node || typeof node !== "object") return [];
  const children = typeof node.type === "function" ? [node.type(node.props)] : React.Children.toArray(node.props?.children);
  return [node, ...children.flatMap(nodes)];
}

test("workspace header uses the selected run perspective and real file without presenting fixture as AI", () => {
  const { Header } = headerHarness();
  const html = render(Header, { documentId: "doc-1", filename: "Synthetic long agreement.pdf", run, state: saved, onLeave() {} });
  assert.match(html, /Synthetic long agreement.pdf/);
  assert.match(html, /Customer perspective/);
  assert.doesNotMatch(html, /Provider perspective/);
  assert.match(html, /Synthetic example/);
  assert.doesNotMatch(html, /AI review/);
  assert.match(html, /<details class="more"><summary>/);
  assert.match(html, /Earlier review/);
});

test("workspace header navigation is guarded and theme change reuses the current theme hook", () => {
  const h = headerHarness("graphite");
  const destinations = [];
  const tree = h.Header({ documentId: "doc/1", filename: "Example.pdf", run, state: saved,
    onLeave(destination) { destinations.push(destination); } });
  const buttons = nodes(tree).filter(node => node.type === "button");
  assert.equal(buttons.length, 8);
  buttons.forEach(button => button.props.onClick());
  assert.deepEqual(destinations, ["/documents", "/documents", "/settings", "/review?documentId=doc%2F1", "/legacy-analysis", "/analytics", "/about"]);
  assert.equal(h.toggles(), 1);
  assert.equal(buttons.find(button => button.props["aria-label"])?.props["aria-label"], "Switch to Black theme");
});

test("workspace header distinguishes not-reviewed and non-ready AI states", () => {
  const { Header } = headerHarness();
  const html = selected => render(Header, { documentId: "doc-1", filename: "Example.pdf", run: selected, state: saved, onLeave() {} });
  assert.match(html(null), /Not reviewed/);
  assert.doesNotMatch(html(null), /Customer perspective/);
  for (const status of ["processing", "incomplete", "failed", "interrupted"])
    assert.match(html({ ...run, kind: "ai", status }), new RegExp(`AI review — ${status}`));
});

test("compact provenance stays collapsed without hiding warnings", () => {
  const html = (selected, contextChanged = false) => render(generation.ReviewRunSummary, { run: selected, contextChanged, compact: true });
  const ready = html(run);
  assert.match(ready, /<details class="cw-provenance">/);
  assert.doesNotMatch(ready, /<details[^>]* open/);
  assert.match(ready, /not an AI-generated review/);
  assert.match(ready, /Example Customer/);
  assert.match(html(run, true).split("<details")[0], /saved brief differs/);
  for (const [status, message] of [["incomplete", /review is incomplete/], ["failed", /No usable review/],
    ["processing", /No final result/], ["interrupted", /run was abandoned/]])
    assert.match(html({ ...run, kind: "ai", status }).split("<details")[0], message);
  assert.match(html({ ...run, failure: { message: "Safe failure detail" } }).split("<details")[0], /Safe failure detail/);
});

test("compact provenance retains model, original context, usage caveat and bounded request details", () => {
  const html = render(generation.ReviewRunSummary, { compact: true, contextChanged: false,
    run: { ...run, kind: "ai", generation: { model_id: "test-model", endpoint: "chat_completions", reasoning_effort: "medium",
      prompt_version: "prompt-v1", schema_version: "schema-v1", extraction_version: "extractor-v1",
      estimated_input_tokens: 200, max_completion_tokens: 400, usage: null, duration_ms: 1250 } },
  });
  for (const text of ["test-model", "medium", "prompt-v1", "schema-v1", "extractor-v1", "200", "400", "1.3 seconds",
    "Provider usage unavailable; this does not mean no charge", "Example Customer"]) assert.ok(html.includes(text), text);
});

test("global navigation hides custom workspace and library shells while preserving legacy review behavior", () => {
  const html = pathname => {
    const Nav = loadModule("../src/components/ConditionalNavBar.tsx", {
      "next/navigation": { usePathname: () => pathname }, "./NavBar": () => React.createElement("nav", null, "Global navigation"),
    }).default;
    return render(Nav, {});
  };
  assert.equal(html("/workspace"), "");
  assert.equal(html("/review"), "");
  assert.equal(html("/review/details"), "");
  assert.match(html("/workspace-other"), /Global navigation/);
  assert.equal(html("/documents"), "");
  assert.match(html("/documents-other"), /Global navigation/);
  assert.equal(html("/import"), "");
  assert.match(html("/import-other"), /Global navigation/);
});
