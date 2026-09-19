import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

function loadModule(path, imports = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React,
      esModuleInterop: true,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    console,
    React,
    require(name) {
      assert.ok(name in imports, `Unexpected dependency: ${name}`);
      return imports[name];
    },
  });
  return exports;
}

const helpers = loadModule("../src/lib/sourceStatus.ts");
const stateModule = loadModule("../src/store/appState.tsx", { react: React });
const sourceMetadata = {
  source_revision_id: "source-1",
  source_sha256: "a".repeat(64),
  source_status: "stored",
  extraction_status: "complete",
  extraction_error: null,
  analysis_status: "not_started",
};

test("legacy documents with absent or null lifecycle metadata retain saved analysis", () => {
  for (const document of [{}, { source_revision_id: null, source_status: null, extraction_status: null, analysis_status: null }]) {
    assert.equal(helpers.hasCompletedAnalysis(document), true);
    assert.equal(helpers.getDocumentSourceStatus(document).label, "Complete");
  }
});

test("imported source and completed extraction are not completed analysis", () => {
  assert.equal(helpers.hasCompletedAnalysis(sourceMetadata), false);
  assert.equal(helpers.getDocumentSourceStatus(sourceMetadata).label, "Not yet reviewed");
  assert.equal(helpers.hasCompletedAnalysis({ source_revision_id: "source-1" }), false);
  assert.equal(helpers.hasCompletedAnalysis({ ...sourceMetadata, analysis_status: "ready" }), true);
});

test("each incomplete or failed stage has an honest non-complete status", () => {
  const states = [
    [{ source_status: "storing" }, "Saving original"],
    [{ source_status: "storage_failed" }, "Original not saved"],
    [{ extraction_status: "pending" }, "Preparing source text"],
    [{ extraction_status: "processing" }, "Preparing source text"],
    [{ extraction_status: "partial" }, "Incomplete source text"],
    [{ extraction_status: "unavailable" }, "No extractable text"],
    [{ extraction_status: "failed" }, "Text extraction failed"],
    [{ analysis_status: "processing" }, "Analysis in progress"],
    [{ analysis_status: "failed" }, "Analysis failed"],
  ];
  for (const [overrides, expected] of states) {
    const document = { ...sourceMetadata, ...overrides };
    assert.equal(helpers.hasCompletedAnalysis(document), false);
    assert.equal(helpers.getDocumentSourceStatus(document).label, expected);
    assert.notEqual(helpers.getDocumentSourceStatus(document).tone, "success");
  }
  assert.match(helpers.getDocumentSourceStatus({ ...sourceMetadata, extraction_status: "partial" }).message, /must not be treated as an absence of issues/);
});

test("source metadata is preserved without copying unrelated server fields", () => {
  const copied = helpers.pickSourceMetadata({ ...sourceMetadata, extraction_attempt_id: "internal-token", pdf_file_id: "internal-pointer" });
  assert.deepEqual({ ...copied }, sourceMetadata);
  assert.equal("extraction_attempt_id" in copied, false);
  assert.equal("pdf_file_id" in copied, false);
});

test("switching documents cannot retain prior source state, clauses or summaries", () => {
  const initial = stateModule.analysisReducer({}, { type: "ANALYSIS_RESET" });
  const imported = stateModule.analysisReducer(initial, {
    type: "ANALYSIS_SET_CURRENT_DOCUMENT", payload: { id: "import-1", ...sourceMetadata },
  });
  const legacy = stateModule.analysisReducer(imported, {
    type: "ANALYSIS_SET_CURRENT_DOCUMENT", payload: { id: "legacy-1", filename: "saved.pdf", summary: "Saved analysis" },
  });
  assert.equal(helpers.hasCompletedAnalysis(legacy.currentDocument), true);
  assert.equal(legacy.currentDocument.source_revision_id, undefined);
  const nextImport = stateModule.analysisReducer(legacy, {
    type: "ANALYSIS_SET_CURRENT_DOCUMENT", payload: { id: "import-2", ...sourceMetadata },
  });
  assert.equal(nextImport.currentDocument.summary, "");
  assert.equal(nextImport.currentDocument.clauses.length, 0);
});

function contextHarness(response) {
  let analysis = stateModule.analysisReducer({}, { type: "ANALYSIS_RESET" });
  let reads = 0;
  const api = {
    async get() { reads += 1; return { success: true, data: response }; },
  };
  const context = loadModule("../src/context/AnalysisContext.tsx", {
    react: { ...React, useCallback: (callback) => callback, useRef: (current) => ({ current }) },
    "../store/appState": { useAppState: () => ({ state: { analysis }, dispatch: (action) => { analysis = stateModule.analysisReducer(analysis, action); } }) },
    "../lib/api": { apiClient: api, handleAPIError() {} },
    "@/lib/documentsApi": { loadWorkspaceDocuments: async () => [] },
    "@/lib/sourceStatus": helpers,
  });
  return {
    value: () => context.AnalysisProvider({ children: null }).props.value,
    state: () => analysis,
    reads: () => reads,
  };
}

test("loading preserves metadata and explicit same-ID loads refresh an unfinished import", async () => {
  const response = { id: "doc-1", filename: "synthetic.pdf", text: "Source text", ...sourceMetadata };
  const harness = contextHarness(response);
  await harness.value().loadDocument("doc-1");
  assert.deepEqual({ ...helpers.pickSourceMetadata(harness.state().currentDocument) }, sourceMetadata);
  response.analysis_status = "ready";
  await harness.value().loadDocument("doc-1");
  assert.equal(harness.reads(), 2);
  assert.equal(harness.state().currentDocument.analysis_status, "ready");
  await harness.value().loadDocument("doc-1");
  assert.equal(harness.reads(), 2);
});

test("saved legacy analysis preserves source metadata and summary without generation", async () => {
  const metadata = { ...sourceMetadata, analysis_status: "ready" };
  const harness = contextHarness({
    ...metadata, id: "doc-1", workspace_id: "local", filename: "synthetic.pdf",
    ai_full_summary: "Saved analysis", clauses: [], risk_summary: { high: 0, medium: 0, low: 0 }, text: "Source text",
  });
  await harness.value().loadDocument("doc-1");
  assert.deepEqual({ ...helpers.pickSourceMetadata(harness.state().currentDocument) }, metadata);
  assert.equal(harness.state().currentDocument.summary, "Saved analysis");
  assert.equal(harness.state().currentDocument.fullText, "Source text");
  assert.equal(harness.reads(), 1);
  assert.equal(harness.value().analyzeDocument, undefined);
});

test("library cards do not label imported documents Complete in either layout", () => {
  const element = ({ children }) => React.createElement("div", null, children);
  const icon = () => React.createElement("svg");
  const card = loadModule("../src/components/documents/DocumentCard.tsx", {
    react: React,
    "@/components/Button": element,
    "@/components/Card": element,
    "lucide-react": { FileText: icon, Clock: icon, CheckCircle: icon, RefreshCw: icon, Trash2: icon, Calendar: icon, AlertCircle: icon },
    "@/lib/sourceStatus": helpers,
    "@/utils/documentUtils": { formatDate: () => "Synthetic date", formatContractType: () => "Unclassified", getContractTypeColor: () => "", highlightSearchText: (text) => text },
  });
  for (const viewMode of ["grid", "list"]) {
    const html = renderToStaticMarkup(React.createElement(card.DocumentCard, {
      document: { id: "doc-1", filename: "synthetic.pdf", upload_date: "2026-01-01", ...sourceMetadata },
      searchQuery: "", isSelectMode: false, isSelected: false, isLoading: false, isDeleting: false, viewMode,
    }));
    assert.match(html, /Not yet reviewed/);
    assert.match(html, /View Document/);
    assert.doesNotMatch(html, /Complete|View Analysis/);
  }
});

test("import route mounts the focused import flow without the earlier analysis screen", () => {
  const page = loadModule("../src/app/import/page.tsx", {
    "@/components/documents/ImportAgreement": () => React.createElement("section", null, "Focused import flow"),
  });
  const html = renderToStaticMarkup(React.createElement(page.default));
  assert.equal(html, "<section>Focused import flow</section>");
});

test("unfinished review renders only source status and original access, never analysis or chat", () => {
  const initial = stateModule.analysisReducer({}, { type: "ANALYSIS_RESET" });
  const currentDocument = { ...initial.currentDocument, id: "doc-1", filename: "synthetic.pdf", ...sourceMetadata };
  const interactionScopes = [];
  const container = ({ children }) => React.createElement("div", null, children);
  const forbidden = () => { throw new Error("Unfinished source must not mount analysis UI"); };
  const review = loadModule("../src/app/review/page.tsx", {
    react: React,
    "next/navigation": { useRouter: () => ({ push() {} }), useSearchParams: () => new URLSearchParams("documentId=doc-1") },
    "@/context/AnalysisContext": { useAnalysis: () => ({ currentDocument, setSelectedClause() {}, async loadDocument() {} }) },
    "@/hooks/useDocumentViewing": { useDocumentViewing: () => ({ async trackDocumentView() {} }) },
    "@/hooks/useUserInteractions": { useUserInteractions: (scope) => { interactionScopes.push(scope); return { flaggedClauses: new Set() }; } },
    "@/hooks/useClauseFiltering": { useClauseFiltering: () => [] },
    "@/components/Card": container,
    "@/components/Button": container,
    "@/components/ui/Modal": forbidden,
    "@/components/PDFViewer": () => React.createElement("p", null, "Saved original viewer"),
    "@/components/ReviewSidebar": forbidden,
    "@/components/review/SummaryContent": forbidden,
    "@/components/review/ClausesContent": forbidden,
    "@/components/review/ChatContent": forbidden,
    "@/lib/toast": {},
    "@/lib/api": {},
    "@/lib/sourceStatus": helpers,
  });
  for (const extractionStatus of ["complete", "partial", "unavailable", "failed"]) {
    currentDocument.extraction_status = extractionStatus;
    const html = renderToStaticMarkup(React.createElement(review.default));
    assert.match(html, /Saved original viewer/);
    assert.match(html, /Download original PDF/);
    assert.doesNotMatch(html, /Export Analysis|Risk Summary|Chat with your document|Unfinished source must not mount/);
  }
  currentDocument.source_status = "storage_failed";
  const failedHtml = renderToStaticMarkup(React.createElement(review.default));
  assert.match(failedHtml, /Original not saved/);
  assert.doesNotMatch(failedHtml, /Saved original viewer|Download original PDF/);
  assert.ok(interactionScopes.every((scope) => scope === null));
});
