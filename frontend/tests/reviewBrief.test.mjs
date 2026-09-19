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
const { buildReviewBrief } = load("../src/components/workspace/reviewBrief.ts", { "./workspaceState": state });

function input() {
  const quote = "Keep 🚀 the exact words.";
  const evidence = { source_revision_id: "source-revision-private", span_id: "span-private", page_number: 7, quote, label: "Transition period" };
  return {
    filename: "managed-services.pdf",
    run: { id: "run-private", kind: "ai", source_revision_id: evidence.source_revision_id, created_at: "2026-01-02T03:04:05Z",
      status: "ready", context: { perspective: "customer", role: "Purchasing team", priorities: "Exit arrangements" },
      overview: "Full overview is not a selected finding", findings: [
        { id: "finding-private", title: "Check the exit period", facts: "Standard assistance is sixty days.",
          interpretation: "Extra time requires a request.", uncertainty: "No exit notice supplied.",
          next_step: "Unselected suggested action", suggested_question: "Unselected suggested question", evidence: [evidence] },
        { id: "other-finding-private", title: "Unselected finding", facts: "Not selected", interpretation: "", uncertainty: "", evidence: [] },
      ],
      coverage: { page_count: 8, extracted_pages: [1, 2, 3, 4, 5, 6, 7], omitted_pages: [8],
        input_scope: "all_extracted_text", limitations: ["Page 8 contains no extractable text."] },
      generation: { model_id: "review-model", reasoning_effort: "medium", usage: { total_tokens: 12345 } },
    },
    personal: { ...state.emptyPersonal(), saved_questions: { "finding-private": { id: "question-private", text: "Can we extend it?", saved_at: "2026-01-03" } },
      drafts: { "finding-private": "Unsaved question wording" }, ask_drafts: { "finding-private": "Ask-only wording" },
      markers: { "finding-private": "revisit" } },
    source: { id: "document-private", source_revision_id: evidence.source_revision_id, source_sha256: "hash-private",
      source_extraction: { page_count: 8, text: "Full document secret", pages: [{ page_number: 7, text: quote,
        spans: [{ id: evidence.span_id, start: 0, end: Array.from(quote).length, text: quote }] }] } },
  };
}

test("ready review exports selected saved work, original context and physical-page provenance", () => {
  const result = buildReviewBrief(input());
  assert.equal(result.filename, "review-brief-managed-services.md");
  assert.equal(result.itemCount, 1);
  for (const value of ["AI-generated review", "Saved run status: Ready", "Customer", "Purchasing team", "Exit arrangements",
    "review-model", "medium", "Can we extend it?", "Personal marker: Revisit", "Standard assistance is sixty days.",
    "Extra time requires a request.", "No exit notice supplied.", "Physical PDF page 7 — quote matched to source", "Transition period",
    "Pages omitted: 8", "Page 8 contains no extractable text.", "not legal advice", "not correctness or legal effect"]) {
    assert.ok(result.markdown.includes(value), value);
  }
  for (const value of ["-private", "12345", "Full document secret", "Keep 🚀", "Unselected", "Unsaved", "Ask-only"]) {
    assert.ok(!result.markdown.includes(value), value);
  }
});

test("no run, no confirmed saved work, and explicit not-marked-only state do not export", () => {
  const values = input();
  assert.equal(buildReviewBrief({ ...values, run: null }), null);
  values.personal.saved_questions = {};
  values.personal.markers = {};
  assert.equal(buildReviewBrief(values), null);
  values.personal.markers["finding-private"] = "not_marked";
  assert.equal(buildReviewBrief(values), null);
});

test("marker-only findings join saved questions once in the selected run's stable finding order", () => {
  const values = input();
  values.personal.markers["other-finding-private"] = "reviewed_by_me";
  const result = buildReviewBrief(values);
  assert.equal(result.itemCount, 2);
  assert.equal(result.markdown.match(/## Finding [12]/g).length, 2);
  assert.ok(result.markdown.indexOf("Check the exit period") < result.markdown.indexOf("Unselected finding"));
  assert.ok(result.markdown.includes("Personal marker: Reviewed by me."));
  assert.ok(result.markdown.includes("No question saved for this finding."));
  assert.ok(result.markdown.includes("No source reference accompanies this finding."));
  values.personal.saved_questions = {};
  assert.equal(buildReviewBrief(values).itemCount, 2);
});

test("orphaned or other-run personal data, opened findings and suggested questions never enter the brief", () => {
  const values = input();
  values.personal.saved_questions = { "stale-id": { text: "Another run's question" } };
  values.personal.markers = { "stale-id": "reviewed_by_me" };
  values.personal.opened_finding_ids = ["finding-private"];
  assert.equal(buildReviewBrief(values), null);
  values.personal.markers["finding-private"] = "revisit";
  const result = buildReviewBrief(values);
  assert.equal(result.itemCount, 1);
  assert.ok(!result.markdown.includes("Another run's question"));
  assert.ok(!result.markdown.includes("Unselected suggested question"));
});

test("all non-ready statuses and recorded failure wording remain explicit", () => {
  for (const status of ["incomplete", "processing", "failed", "interrupted"]) {
    const values = input(); values.run.status = status;
    values.run.failure = { code: "INTERNAL_CODE", message: "The review did not finish." };
    const result = buildReviewBrief(values);
    assert.ok(result.markdown.includes(`Saved run status: ${status[0].toUpperCase() + status.slice(1)}.`));
    assert.ok(result.markdown.includes("did not reach a ready state"));
    assert.ok(result.markdown.includes("The review did not finish."));
    assert.ok(!result.markdown.includes("INTERNAL_CODE"));
  }
});

test("authored fixture and absent coverage cannot masquerade as a complete AI review", () => {
  const values = input(); values.run.kind = "fixture";
  delete values.run.status; delete values.run.generation; delete values.run.coverage;
  const result = buildReviewBrief(values);
  assert.ok(result.markdown.includes("Authored synthetic example (not an AI-generated review)"));
  assert.ok(result.markdown.includes("not exhaustive"));
  assert.ok(result.markdown.includes("No page-coverage record"));
  assert.ok(!result.markdown.includes("Recorded model"));
  assert.ok(result.markdown.includes("Saved run status: Ready."));
});

test("missing extraction, wrong revisions and unmatched anchors never report a source match", () => {
  for (const mutate of [
    values => { values.source = null; },
    values => { values.source.source_extraction = null; },
    values => { values.source.source_revision_id = "other-source"; },
    values => { values.run.source_revision_id = "other-run-source"; },
    values => { values.run.findings[0].evidence[0].source_revision_id = "other-evidence-source"; },
    values => { values.run.findings[0].evidence[0].span_id = "missing"; },
    values => { values.run.findings[0].evidence[0].quote = "Wrong words"; },
    values => { values.run.findings[0].evidence[0].page_number = 2; },
  ]) {
    const values = input(); mutate(values);
    const result = buildReviewBrief(values);
    assert.ok(!result.markdown.includes("— quote matched to source"), mutate.toString());
    assert.ok(result.markdown.includes("quote not matched"), mutate.toString());
  }
  assert.ok(buildReviewBrief({ ...input(), source: null }).markdown.includes("Source text is unavailable"));
});

test("not-found claims retain their limited basis without inventing references or findings", () => {
  const values = input(); Object.assign(values.run.findings[0], { basis: "not_found", coverage_basis: "Only extracted pages supplied.", evidence: [] });
  const result = buildReviewBrief(values);
  assert.ok(result.markdown.includes("not proof of absence"));
  assert.ok(result.markdown.includes("Only extracted pages supplied."));
  assert.ok(result.markdown.includes("No source reference"));
});

test("multiline Unicode and malicious Markdown, HTML, links and fence closers remain literal", () => {
  const malicious = "  café 🧭 合同\n# forged heading\n![image](https://invalid.example/pixel)\n<script>alert(1)</script>\n```\n````\n~~~\n[link](javascript:bad)\nhttps://invalid.example/\n> quote\n1. item\n\ntrailing  ";
  const values = input();
  values.personal.saved_questions["finding-private"].text = malicious;
  values.run.findings[0].title = malicious;
  values.run.context.role = malicious;
  values.run.findings[0].evidence[0].label = malicious;
  values.run.coverage.limitations = [malicious];
  const result = buildReviewBrief(values);
  assert.equal(result.markdown.split(`\`\`\`\`\`text\n${malicious}\n\`\`\`\`\``).length - 1, 5);
  // Any attacker-controlled heading, HTML or link text occurs inside a fence.
  let fence = null;
  for (const line of result.markdown.split("\n")) {
    if (!fence && /^`{3,}text$/.test(line)) { fence = line.slice(0, -4); continue; }
    if (fence && line === fence) { fence = null; continue; }
    if (line.includes("invalid.example") || line.includes("<script>") || line.includes("forged heading")) assert.ok(fence);
  }
  assert.equal(fence, null);
});

test("download filenames are portable basenames with bounded Unicode and no traversal", () => {
  for (const [filename, expected] of [
    ["../../contract.pdf", "review-brief-contract.md"],
    ["C:\\private\\agreement.PDF", "review-brief-agreement.md"],
    ["...", "review-brief-agreement.md"],
    ["CON.pdf", "review-brief-CON.md"],
    ["合同 🧭 résumé.pdf", "review-brief-合同-résumé.md"],
    ["bad\u0000\nname.pdf", "review-brief-bad-name.md"],
  ]) {
    const result = buildReviewBrief({ ...input(), filename });
    assert.equal(result.filename, expected);
    assert.ok(!/[\\/:\u0000-\u001f]/.test(result.filename));
    assert.ok(!result.filename.includes(".."));
  }
  const result = buildReviewBrief({ ...input(), filename: `${"a".repeat(1000)}.pdf` });
  assert.equal(Array.from(result.filename).length, "review-brief-".length + 80 + ".md".length);
  assert.ok(!buildReviewBrief({ ...input(), filename: "/private/location/contract.pdf" }).markdown.includes("/private/location"));
});

test("export is deterministic and leaves deeply frozen source, run and personal state unchanged", () => {
  const values = input(); const before = JSON.stringify(values);
  function freeze(value) { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } }
  freeze(values);
  const first = buildReviewBrief(values);
  assert.equal(buildReviewBrief(values).markdown, first.markdown);
  assert.equal(JSON.stringify(values), before);
});
