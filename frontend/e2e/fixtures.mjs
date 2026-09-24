import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { test as base, expect } from "@playwright/test";

export const DOCUMENT_ID = "synthetic-managed-services";
export const IMPORT_ID = "synthetic-imported-agreement";
export const RUN_ID = "authored-example-review";
export const PDF_PATH = fileURLToPath(new URL("../../tests/fixtures/pdfs/managed-services-25p.pdf", import.meta.url));
const recordedAt = "2026-01-01T12:00:00Z";
const origin = "http://127.0.0.1:3100";

const personalState = () => ({
  drafts: {}, ask_drafts: {}, saved_questions: {}, markers: {}, opened_finding_ids: [],
  position: { view: "overview", finding_id: null, evidence_span_id: null },
});

/** Build browser-only responses from the public PDF and reviewed authored fixture.
 * PDF.js supplies exact PDF text, not generated or hand-retyped source quotes.
 * This is not a backend extraction or AI-quality test.
 */
async function sourceFixture(documentId) {
  const pdfPath = fileURLToPath(new URL("../../tests/fixtures/pdfs/managed-services-25p.pdf", import.meta.url));
  const bytes = await readFile(pdfPath);
  const authored = JSON.parse(await readFile(new URL("../../backend/fixtures/reviews/managed-services-25p.json", import.meta.url), "utf8"));
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  assert.equal(sha256, authored.source_sha256, "The authored findings must match the canonical PDF bytes");
  const { getDocument } = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const task = getDocument({ data: new Uint8Array(bytes), useSystemFonts: true, disableFontFace: true, isEvalSupported: false });
  const pdf = await task.promise;
  const pages = [];
  try {
    for (let number = 1; number <= pdf.numPages; number++) {
      const content = await (await pdf.getPage(number)).getTextContent();
      const lines = [];
      let line = "";
      for (const item of content.items) {
        if (!("str" in item)) continue;
        const text = item.str.trim();
        if (text) line += `${line ? " " : ""}${text}`;
        if (item.hasEOL && line) { lines.push(line); line = ""; }
      }
      if (line) lines.push(line);
      let offset = 0;
      const spans = lines.map((text, index) => {
        const span = { id: `fixture-p${number}-line${index + 1}`, start: offset, end: offset + Array.from(text).length, text };
        offset = span.end + 1;
        return span;
      });
      pages.push({ page_number: number, status: "extracted", text: lines.join("\n"), spans, warnings: [] });
    }
  } finally { await task.destroy(); }
  assert.equal(pages.length, 25);
  const revision = `${documentId}-source-v1`;
  const findings = authored.findings.map(finding => ({ ...finding, evidence: finding.evidence.map(reference => {
    const matches = pages[reference.page_number - 1].spans.filter(span => span.text.includes(reference.match));
    assert.equal(matches.length, 1, `Ambiguous or missing public fixture anchor: ${reference.label}`);
    return { source_revision_id: revision, span_id: matches[0].id, page_number: reference.page_number, quote: matches[0].text, label: reference.label };
  }) }));
  const source = {
    id: documentId, source_revision_id: revision, source_sha256: sha256,
    source_status: "stored", extraction_status: "complete", analysis_status: "not_started",
    source_extraction: { content_sha256: sha256, extraction_version: "browser-fixture-pdfjs-v1", status: "complete", page_count: pages.length, pages, warnings: [], text: pages.map(page => page.text).join("\n\n") },
  };
  const run = { id: RUN_ID, kind: "fixture", source_revision_id: revision, created_at: recordedAt,
    context: authored.context, fixture_version: authored.version, overview: authored.overview, findings };
  const workspace = { document_id: documentId, source_revision_id: revision, revision: 0, brief: authored.context,
    runs: [run], personal: { [RUN_ID]: personalState() }, ask_turns: [], fixture_available: true };
  return { bytes, source, workspace };
}

function applyOperation(workspace, operation) {
  if (operation.type === "set_brief") workspace.brief = operation.brief;
  else {
    assert.equal(operation.run_id, RUN_ID);
    const personal = workspace.personal[RUN_ID];
    if (operation.type === "set_position") {
      personal.position = operation.position;
      if (operation.position.finding_id && !personal.opened_finding_ids.includes(operation.position.finding_id)) personal.opened_finding_ids.push(operation.position.finding_id);
    } else {
      assert.ok(workspace.runs[0].findings.some(finding => finding.id === operation.finding_id));
      switch (operation.type) {
        case "set_draft": personal.drafts[operation.finding_id] = operation.text; break;
        case "set_ask_draft": personal.ask_drafts[operation.finding_id] = operation.text; break;
        case "save_question": personal.saved_questions[operation.finding_id] = { id: `question-${operation.finding_id}`, text: operation.text, saved_at: recordedAt }; break;
        case "set_marker": personal.markers[operation.finding_id] = operation.marker; break;
        default: throw new Error(`Unexpected browser fixture operation: ${operation.type}`);
      }
    }
  }
  workspace.revision += 1;
}

export const test = base.extend({
  mockWorkspace: [async ({ context }, use) => {
    const fixture = await sourceFixture(DOCUMENT_ID);
    const imported = structuredClone(fixture);
    imported.source.id = IMPORT_ID;
    imported.source.source_revision_id = `${IMPORT_ID}-source-v1`;
    imported.workspace.document_id = IMPORT_ID;
    imported.workspace.source_revision_id = imported.source.source_revision_id;
    imported.workspace.runs = [];
    imported.workspace.personal = {};
    let importCompleted = false;
    const unexpected = [];
    const providerDispatches = [];
    const operations = [];
    const errors = [];
    context.on("page", page => page.on("pageerror", error => errors.push(error.message)));
    const respond = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ success: status < 400, data }) });
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin) {
        unexpected.push(`${request.method()} external ${url.hostname}`);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const path = url.pathname.replace(/^\/api\/v1/, "");
      const method = request.method();
      if (/\/generate$|\/ask$|\/analysis|\/chat/.test(path)) {
        providerDispatches.push(`${method} ${path}`);
        return route.abort();
      }
      assert.equal(request.headers()["x-clauseiq-local"], "1", "The local-request marker must survive browser flows");
      if (method === "GET" && path === "/workspace") return respond(route, {
        has_api_key: false, api_key_needs_reentry: false, model_id: "gpt-6-sol", reasoning_effort: "medium",
        query_gate_model_id: "gpt-6-luna", available_models: [], retention_days: 0, toast_notifications_enabled: false,
      });
      if (method === "GET" && path === "/app-config") return respond(route, { toast_notifications_enabled: false });
      const item = (id, state) => ({ id, filename: "managed-services-25p.pdf", upload_date: recordedAt, page_count: 25,
        source_revision_id: state.source_revision_id, source_status: "stored", extraction_status: "complete", analysis_status: "not_started",
        review_summary: { kind: state.runs.length ? "fixture" : null, status: state.runs.length ? "ready" : "not_started",
          saved_question_count: Object.keys(state.personal[RUN_ID]?.saved_questions || {}).length, last_activity_at: recordedAt, can_resume: !!state.runs.length } });
      if (method === "GET" && path === "/documents/") return respond(route, { documents: [item(DOCUMENT_ID, fixture.workspace), ...(importCompleted ? [item(IMPORT_ID, imported.workspace)] : [])] });
      if (method === "POST" && path === "/documents/import") {
        assert.match(request.headers()["content-type"], /^multipart\/form-data; boundary=/);
        // Chromium's request introspection is not a binary multipart verifier.
        // setInputFiles supplies the SHA-checked public PDF; this verifies routing.
        assert.ok(request.postDataBuffer()?.includes(Buffer.from('filename="managed-services-25p.pdf"')), "The selected synthetic filename must reach the local import route");
        importCompleted = true;
        return respond(route, imported.source);
      }
      const match = path.match(/^\/documents\/(synthetic-managed-services|synthetic-imported-agreement)(.*)$/);
      if (match) {
        const current = match[1] === DOCUMENT_ID ? fixture : imported;
        const suffix = match[2];
        if (method === "GET" && suffix === "") return respond(route, item(match[1], current.workspace));
        if (method === "GET" && suffix === "/source") return respond(route, current.source);
        if (method === "GET" && suffix === "/pdf") return route.fulfill({ status: 200, contentType: "application/pdf", body: fixture.bytes });
        if (method === "POST" && suffix === "/view") return respond(route, { last_viewed: recordedAt });
        if (method === "GET" && suffix === "/review-workspace") return respond(route, current.workspace);
        if (method === "PUT" && suffix === "/review-workspace") {
          const { expected_revision: revision, operation } = request.postDataJSON();
          assert.equal(revision, current.workspace.revision, "Writes must retain the revision fence");
          applyOperation(current.workspace, operation); operations.push(operation);
          return respond(route, current.workspace);
        }
      }
      unexpected.push(`${method} ${path}`);
      return route.abort();
    });
    await use({ fixture, imported, operations });
    expect(providerDispatches, "Unpaid journeys must never dispatch a review or Ask request").toEqual([]);
    expect(unexpected, "Unexpected requests must be intercepted, never sent to the real backend or internet").toEqual([]);
    expect(errors, "Browser journeys must not hide runtime exceptions").toEqual([]);
  }, { auto: true }],
});

export { expect };
