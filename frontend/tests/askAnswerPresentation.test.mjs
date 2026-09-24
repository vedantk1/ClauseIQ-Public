import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as icons from "lucide-react";
import ts from "typescript";

function load(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require(name) {
    assert.ok(name in imports, `Unexpected dependency: ${name}`);
    return imports[name];
  } });
  return exports;
}
const answerPresentation = load("../src/components/workspace/askAnswerPresentation.ts");
const { presentAskAnswer } = answerPresentation;
const state = load("../src/components/workspace/workspaceState.ts");
const presentation = load("../src/components/workspace/evidencePresentation.ts", { "./workspaceState": state });
const controls = load("../src/components/workspace/WorkspaceControls.tsx", { react: React, "./workspaceState": state });
const evidenceControls = load("../src/components/workspace/EvidenceSourcePane.tsx", {
  react: React, "lucide-react": icons, "./evidencePresentation": presentation, "./WorkspaceControls": controls,
});
const { AskTurn } = load("../src/components/workspace/FindingAsk.tsx", {
  react: React, "./askAnswerPresentation": answerPresentation, "./workspaceState": state,
  "./EvidenceSourcePane": evidenceControls, "./WorkspaceControls": controls,
  "@/components/ui/Modal": () => null, "@/context/WorkspaceContext": { useWorkspace() { assert.fail("Turn display must not access model settings"); } },
});

function nodes(node, predicate) {
  if (!React.isValidElement(node)) return [];
  return [...(predicate(node) ? [node] : []), ...React.Children.toArray(node.props.children).flatMap(item => nodes(item, predicate))];
}

function fixture() {
  const first = { source_revision_id: "source-1", span_id: "line-1", page_number: 1, quote: "First exact quotation.", label: "First rule" };
  const second = { ...first, span_id: "line-2", quote: "Second exact quotation.", label: "Exception" };
  const source = { source_revision_id: "source-1", source_extraction: { pages: [{ page_number: 1,
    text: `${first.quote}\n${second.quote}`, spans: [
      { id: first.span_id, start: 0, end: first.quote.length, text: first.quote },
      { id: second.span_id, start: first.quote.length + 1, end: first.quote.length + 1 + second.quote.length, text: second.quote },
    ] }] } };
  const turn = { id: "answer-1", question: "What qualifies this rule?", status: "ready",
    answer: [{ text: "A qualification applies [p1_b3_v1; p2_b3_v1].", evidence: [first, second] }],
    limitations: [], created_at: "2026-01-01", completed_at: "2026-01-01", history_turn_ids: [],
    include_history: false, history_truncated: false, coverage: { extracted_pages: [1], page_count: 1, omitted_pages: [], limitations: [] },
    generation: { model_id: "test", reasoning_effort: "medium", endpoint: "test", usage: null } };
  return { first, second, source, turn };
}

test("display-only segmentation retains every character and marks request-local IDs as unlinked", () => {
  const text = "Read 🧭 [p1_b3_v1; p2_b3_v1].\nThen [ p3_b14_v99, p4_b2_v1 ] carefully.";
  const parts = presentAskAnswer(text);
  assert.equal(parts.map(part => part.text).join(""), text);
  assert.deepEqual(JSON.parse(JSON.stringify(parts.filter(part => part.kind !== "text"))), [
    { kind: "unlinked-reference", text: "[p1_b3_v1; p2_b3_v1]", number: 1 },
    { kind: "unlinked-reference", text: "[ p3_b14_v99, p4_b2_v1 ]", number: 2 },
  ]);
  assert.ok(parts.every(part => !('pageNumber' in part) && !('evidence' in part)), "page syntax never creates a source association");
});

test("legal brackets, unfamiliar identifiers and malformed tokens are never stripped", () => {
  for (const text of ["Payment [30 days] applies under [2.1].", "[p1_b3_v1; unknown]", "[p1_b3_v1 amended]",
    "[p1_b0_v1]", "[p0_b1_v1]", "[p1_b2_v0]", "[source-1]", "[p1_b3]", "", "[p1_b3_v1–p2_b3_v1]"]) {
    const parts = presentAskAnswer(text);
    assert.equal(parts.length, 1, text);
    assert.equal(parts[0].kind, "text", text);
    assert.equal(parts[0].text, text);
  }
});

test("compact answer references preserve each exact associated entry rather than grouping by page", () => {
  const { first, second, source } = fixture();
  const previews = [];
  const tree = evidenceControls.EvidenceList({ preview: true, evidence: [first, second, first], source,
    onOpen: evidence => previews.push(evidence) });
  const buttons = nodes(tree, node => node.type === "button");
  assert.equal(buttons.length, 3);
  buttons[1].props.onClick(); buttons[2].props.onClick();
  assert.equal(previews[0], second); assert.equal(previews[1], first);
  assert.match(buttons[1].props["aria-label"], /Preview excerpt · page 1 · Exception/);
  const html = renderToStaticMarkup(tree);
  assert.doesNotMatch(html, /<blockquote|First exact quotation|Second exact quotation|View page/);
});

test("source mismatch or ambiguous anchors never imply a matched preview or invent PDF navigation", () => {
  for (const variation of ["missing", "revision", "ambiguous", "quote"]) {
    const { first, source } = fixture();
    if (variation === "revision") source.source_revision_id = "other";
    if (variation === "ambiguous") source.source_extraction.pages[0].spans.push({ ...source.source_extraction.pages[0].spans[0] });
    if (variation === "quote") first.quote = "Altered quotation";
    let selected;
    const tree = evidenceControls.EvidenceList({ preview: true, evidence: [first], source: variation === "missing" ? null : source,
      onOpen: evidence => { selected = evidence; } });
    const html = renderToStaticMarkup(tree);
    assert.match(html, /Source not matched/);
    assert.doesNotMatch(html, /View page|Quote matched|Passage matched/);
    nodes(tree, node => node.type === "button")[0].props.onClick();
    assert.equal(selected, first, "only the exact saved quotation is available for inspection");
  }
});

test("Ask prose carries an explicit unlinked indicator with raw IDs accessible without changing saved content", () => {
  const { turn, source, second } = fixture();
  const saved = JSON.stringify(turn);
  let selected;
  const tree = AskTurn({ turn, source, onEvidence: (text, evidence) => { selected = { text, evidence }; },
    onRefresh() { assert.fail("display must not reload"); }, onInterrupt() { assert.fail("display must not interrupt"); }, controlsDisabled: false });
  const html = renderToStaticMarkup(tree);
  assert.match(html, /\[unlinked reference 1\]/);
  assert.match(html, /<details class="cw-unlinked-citations"><summary>Unlinked source references \(1\)<\/summary>/);
  assert.match(html, /<code>\[p1_b3_v1; p2_b3_v1\]<\/code>/);
  assert.doesNotMatch(html, /<blockquote|First exact quotation|Second exact quotation/);
  const evidenceList = nodes(tree, node => node.type === evidenceControls.EvidenceList)[0];
  evidenceList.props.onOpen(second);
  assert.equal(selected.text, turn.answer[0].text);
  assert.equal(selected.evidence, second);
  assert.equal(JSON.stringify(turn), saved);
});

test("incomplete answers keep their specific warning outside the generic answer-details disclosure", () => {
  const { turn, source } = fixture(); turn.status = "incomplete"; turn.limitations = ["The schedule was not extracted."];
  const tree = AskTurn({ turn, source, onEvidence() {}, onRefresh() {}, onInterrupt() {}, controlsDisabled: false });
  const html = renderToStaticMarkup(tree);
  const details = html.indexOf('<details class="cw-ask-answer-details">');
  assert.ok(html.indexOf("This answer is incomplete") < details);
  assert.ok(html.indexOf("The schedule was not extracted.") < details);
  assert.ok(html.indexOf("AI interpretation can be wrong") > details);
});
