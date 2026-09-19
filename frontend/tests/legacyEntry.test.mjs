import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

function loadModule(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, React, require(name) {
    assert.ok(name in imports, `Unexpected dependency: ${name}`);
    return imports[name];
  } });
  return exports;
}

function nodes(element) {
  if (!React.isValidElement(element)) return [];
  return [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
}

test("retired upload bookmarks redirect to no-AI import without mounting a paid workflow", () => {
  const destinations = [];
  const LegacyAnalysis = loadModule("../src/app/legacy-analysis/page.tsx", {
    "next/navigation": { redirect: destination => destinations.push(destination) },
  }).default;
  LegacyAnalysis();
  assert.deepEqual(destinations, ["/import"]);
});

test("legacy document header offers only the current import entry point", () => {
  const destinations = [];
  const Button = () => null;
  const icon = () => null;
  const { DocumentsHeader } = loadModule("../src/components/documents/DocumentsHeader.tsx", {
    "next/navigation": { useRouter: () => ({ push: destination => destinations.push(destination) }) },
    "@/components/Button": Button,
    "lucide-react": { Upload: icon, RefreshCw: icon, Trash2: icon },
  });
  const buttons = nodes(DocumentsHeader({ documentsCount: 0 })).filter(element => element.type === Button);
  assert.equal(buttons.length, 1);
  assert.ok(React.Children.toArray(buttons[0].props.children).includes("Import agreement"));
  buttons[0].props.onClick();
  assert.deepEqual(destinations, ["/import"]);
});

test("legacy context still reads saved analysis but no longer offers document generation", async () => {
  const calls = [], actions = [];
  const { AnalysisProvider } = loadModule("../src/context/AnalysisContext.tsx", {
    react: { ...React, useCallback: callback => callback, useRef: value => ({ current: value }) },
    "../store/appState": { useAppState: () => ({
      state: { analysis: { documents: [], currentDocument: {}, isLoading: false, error: null } },
      dispatch: action => actions.push(action),
    }) },
    "../lib/api": { apiClient: { get: async path => {
      calls.push(path);
      return { success: true, data: { id: "saved-contract", filename: "synthetic.pdf", ai_full_summary: "Stored summary", clauses: [{ id: "saved-clause" }] } };
    } }, handleAPIError() { assert.fail("No API error expected"); } },
    "@/lib/documentsApi": { loadWorkspaceDocuments: async () => [] },
    "@/lib/sourceStatus": { hasCompletedAnalysis: () => false, pickSourceMetadata: () => ({}) },
  });
  const context = AnalysisProvider({ children: null }).props.value;
  assert.equal(context.analyzeDocument, undefined);
  assert.deepEqual(calls, []);
  await context.loadDocument("saved-contract");
  assert.deepEqual(calls, ["/documents/saved-contract"]);
  const saved = actions.find(action => action.type === "ANALYSIS_SET_CURRENT_DOCUMENT").payload;
  assert.equal(saved.summary, "Stored summary");
  assert.equal(saved.clauses[0].id, "saved-clause");
});

test("saved-result review keeps original access while new uploads use import", () => {
  const source = readFileSync(new URL("../src/app/review/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /legacy-analysis|analyzeDocument/);
  assert.match(source, /router\.push\("\/import"\)/);
  assert.match(source, /handleDownloadOriginalPdf/);
  assert.match(source, /if \(documentId && !analysisReady\)/);
  assert.match(source, /useUserInteractions/);
  assert.match(source, /ChatContent/);
});
