import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function load(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require(name) {
    assert.ok(name in imports, `Unexpected dependency: ${name}`);
    return imports[name];
  } });
  return exports;
}
const state = load("../src/components/workspace/workspaceState.ts");
const { presentEvidence } = load("../src/components/workspace/evidencePresentation.ts", { "./workspaceState": state });

function fixture(before = "Read 🧭 this: ", quote = "Keep 🚀 the exact words.", after = "\nConditions remain.") {
  const start = Array.from(before).length;
  const end = start + Array.from(quote).length;
  const span = { id: "anchor", start, end, text: quote };
  const evidence = { source_revision_id: "revision-1", page_number: 7, span_id: span.id, quote, label: "Rule" };
  const page = { page_number: 7, text: before + quote + after, spans: [span] };
  return { evidence, page, source: { source_revision_id: "revision-1", source_extraction: { pages: [page] } } };
}

test("Unicode code-point offsets produce exact untouched quotation and adjacent text", () => {
  const before = "🧭 Read this: "; const quote = "Use 🚀 carefully."; const after = "\nAnd keep 🪴 growing.";
  const { evidence, source } = fixture(before, quote, after);
  const saved = JSON.stringify({ evidence, source });
  const result = presentEvidence(evidence, source);
  assert.equal(result.matched, true);
  assert.equal(result.scope, "Saved excerpt");
  assert.equal(result.context.before, before);
  assert.equal(result.context.quote, quote);
  assert.equal(result.context.after, after);
  assert.equal(result.context.before + result.context.quote + result.context.after, result.context.fullPage);
  assert.equal(result.context.clippedBefore, false);
  assert.equal(result.context.clippedAfter, false);
  assert.equal(JSON.stringify({ evidence, source }), saved);
});

test("context is bounded in Unicode characters and never changes the saved quotation", () => {
  const before = "🧭".repeat(400); const after = "🪴".repeat(401);
  const { evidence, source } = fixture(before, "exact\n\nquote", after);
  const result = presentEvidence(evidence, source);
  assert.equal(Array.from(result.context.before).length, 360);
  assert.equal(Array.from(result.context.after).length, 360);
  assert.equal(result.context.clippedBefore, true);
  assert.equal(result.context.clippedAfter, true);
  assert.equal(result.context.quote, "exact\n\nquote");
  assert.equal(result.context.fullPage, before + evidence.quote + after);
});

test("page boundaries never borrow neighboring pages or invent missing text", () => {
  const { evidence, source } = fixture("", "Single page rule.", "");
  source.source_extraction.pages.unshift({ page_number: 6, text: "Other-page secret", spans: [] });
  source.source_extraction.pages.push({ page_number: 8, text: "Never joined", spans: [] });
  const result = presentEvidence(evidence, source);
  assert.equal(result.context.before, "");
  assert.equal(result.context.after, "");
  assert.equal(result.context.fullPage, evidence.quote);
  assert.equal(result.context.pageNumber, 7);
});

test("same-page ranges preserve newlines and all exact Unicode text between their anchors", () => {
  const { evidence, source, page } = fixture("Before ", "One 🚀.\n\nTwo 🪴.", " After");
  const first = { id: "start", start: 7, end: 13, text: "One 🚀." };
  const last = { id: "end", start: 15, end: 21, text: "Two 🪴." };
  page.spans = [first, last];
  evidence.span_id = first.id; evidence.end_span_id = last.id;
  const result = presentEvidence(evidence, source);
  assert.equal(result.matched, true);
  assert.equal(result.scope, "Selected passage");
  assert.equal(result.context.before, "Before ");
  assert.equal(result.context.quote, evidence.quote);
  assert.equal(result.context.after, " After");
});

test("revision, page, quote and missing anchor mismatches never reveal context", () => {
  for (const change of [
    { source_revision_id: "other" }, { page_number: 8 }, { span_id: "missing" },
    { quote: "Slightly rewritten words" }, { end_span_id: "missing" }, { end_span_id: "" },
  ]) {
    const { evidence, source } = fixture();
    const result = presentEvidence({ ...evidence, ...change }, source);
    assert.equal(result.matched, false, JSON.stringify(change));
    assert.equal(result.context, null);
  }
  assert.equal(presentEvidence(fixture().evidence, null).context, null);
});

test("malformed single-span offsets cannot supply a matched quote or context", () => {
  for (const change of [
    { start: -1 }, { start: 0.5 }, { end: 9999 }, { end: 0 }, { end: Number.NaN }, { text: "changed" },
  ]) {
    const { evidence, source, page } = fixture();
    Object.assign(page.spans[0], change);
    assert.equal(presentEvidence(evidence, source).matched, false, JSON.stringify(change));
    assert.equal(presentEvidence(evidence, source).context, null);
  }
});

test("legacy duplicate and overlapping anchors fail closed without changing the old matching helper", () => {
  for (const mutate of [
    ({ page }) => page.spans.push({ ...page.spans[0] }),
    ({ page }) => page.spans.push({ ...page.spans[0], id: "overlap" }),
    ({ source, page }) => source.source_extraction.pages.push({ ...page, page_number: 8 }),
    ({ source, page }) => source.source_extraction.pages.push({ ...page, spans: [] }),
  ]) {
    const values = fixture(); mutate(values);
    assert.equal(state.evidenceMatches(values.evidence, values.source), true);
    const result = presentEvidence(values.evidence, values.source);
    assert.equal(result.matched, false);
    assert.equal(result.context, null);
  }
});

test("reversed, cross-page and inconsistent ranges are never reconstructed", () => {
  for (const mutation of ["reverse", "other-page", "gap", "overlap"]) {
    const { evidence, source, page } = fixture("", "First.\nLast.", "");
    page.spans = [{ id: "a", start: 0, end: 6, text: "First." }, { id: "b", start: 7, end: 12, text: "Last." }];
    evidence.span_id = "a"; evidence.end_span_id = "b";
    if (mutation === "reverse") { evidence.span_id = "b"; evidence.end_span_id = "a"; }
    if (mutation === "other-page") source.source_extraction.pages.push({ page_number: 8, text: "Last.", spans: [page.spans.pop()] });
    if (mutation === "gap") { page.text = "First.xLast."; evidence.quote = page.text; }
    if (mutation === "overlap") page.spans.push({ id: "c", start: 0, end: 6, text: "First." });
    const result = presentEvidence(evidence, source);
    assert.equal(result.matched, false, mutation);
    assert.equal(result.context, null);
  }
});

test("absent and null end anchors keep the legacy single-span scope", () => {
  const { evidence, source } = fixture();
  for (const end_span_id of [undefined, null]) {
    const result = presentEvidence({ ...evidence, end_span_id }, source);
    assert.equal(result.matched, true);
    assert.equal(result.scope, "Saved excerpt");
    assert.equal(result.context.quote, evidence.quote);
  }
});
