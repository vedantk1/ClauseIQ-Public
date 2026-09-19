# API reference

Application routes use /api/v1. The generated schema at
http://localhost:8000/docs is authoritative while the API evolves.

## Local access

Workspace calls require:

~~~http
X-ClauseIQ-Local: 1
~~~

There are no bearer tokens or account sessions. This marker triggers browser
CORS preflight; it is not a secret. Requests also require a loopback Host and,
when present, an allowed local Origin. In Swagger, select Authorize and enter
1 for the local marker. CLI clients may omit Origin but must include the marker.

| Prefix | Purpose |
| --- | --- |
| /api/v1/workspace | Key status, key save/removal and ordinary Settings |
| /api/v1/documents | Local source import/extraction, list, fetch, PDF access and delete |
| /api/v1/analysis | Legacy clauses, notes, flags, rewrites and deprecated upload/analysis |
| /api/v1/chat | Document sessions, messages, history and status |
| /api/v1/reports | Document PDF reports |
| /api/v1/health | Local health checks |
| /api/v1/app-config | Non-sensitive presentation settings |

Account, admin and AI-debug routes are removed. The server supplies workspace_id;
request data cannot change the workspace. Document IDs remain required for
document-specific operations.

The standalone Analytics API is removed; /api/v1/analytics/dashboard returns 404
for authorized local requests. POST /api/v1/analysis/analyze/ remains available
but is marked deprecated in OpenAPI. Its frontend uploader is retired; new work
uses source import followed by an explicit review-workspace generation request.
Saved earlier analyses, interactions, chat, reports and originals are not removed.

## Library listing

GET /api/v1/documents/ returns the document metadata list without loading source
text, full review output, evidence, saved-question wording or credentials. One
workspace-scoped Mongo projection supplies each row; there are no per-document
workspace requests or automatic AI operations.

In addition to retained source and legacy analysis metadata, rows include:

- page_count: the saved extraction's physical page count, or null when unknown.
- review_summary: kind (fixture/ai/null), status
  (not_started/ready/incomplete/processing/failed/interrupted/unavailable),
  saved_question_count, last_activity_at (UTC ISO timestamp or null), and can_resume.

The summary selects the final saved run in array order, matching the workspace's
default selection. A failed or processing newer attempt never silently falls back
to an older ready run. Missing status is compatible only with historical fixture
snapshots. Saved-question counts belong to that selected run, not all past runs.
Only ready/incomplete runs with consistent projected metadata offer resume;
malformed or mismatched summary metadata returns unavailable. This is a display
summary, not evidence validation or a claim of review completeness. The workspace
still validates its full saved state when opened.

Activity derives from existing last_viewed, run creation/completion and saved
question timestamps; upload/update timestamps do not fabricate review activity.
Listing does not write timestamps or migrate records. Legacy records without a
source revision retain their original analysis metadata and earlier review route;
the new workspace summary does not reinterpret them.

## Source import and extraction

- POST /api/v1/documents/import accepts multipart file, persists the original and
  attempts local extraction. No key, model or vector request is made. Success
  means the original was imported, not that AI review succeeded; inspect statuses.
- GET /api/v1/documents/{document_id}/source returns source metadata and the saved
  source_extraction snapshot. Legacy records have null source metadata; this read
  never invents anchors or starts extraction.
- POST /api/v1/documents/{document_id}/extract accepts `{}` to retry pending/failed
  local extraction. Use `{"restart": true}` deliberately to supersede an interrupted
  processing attempt. Saved snapshots are returned unchanged. No AI is retried.

New document detail/list responses include optional source_revision_id,
source_sha256, source_status (storing/stored/storage_failed), extraction_status
(pending/processing/complete/partial/unavailable/failed), extraction_error (safe
code), and analysis_status (not_started/processing/ready/failed). Missing/null
metadata identifies historical records, not proof of a failed or new review.

The source snapshot contains content_sha256, extraction_version, status, page_count,
pages, warnings and compatibility text. Each page has a one-based page_number,
exact extracted text, extracted/empty/failed status, warnings and line spans.
Each span has id, text, start and end; offsets are page-relative Unicode code-point
positions, end-exclusive. In JavaScript use code-point indexing, not raw string
slice offsets. References do not represent PDF highlight rectangles.

Source errors use safe codes and, when known, error.details.document_id so the
stored record can be inspected. Storage failure is not successful import. Failed
text extraction can be a successful import with extraction_status=failed and an
available original PDF. Extraction conflicts return 409. Actual byte length is
limited by the smaller of the configured upload cap and the supported GridFS
service cap; declared upload size alone is not trusted.

POST /api/v1/analysis/analyze/ remains the current upload-and-analyze entry point.
It checks the personal key, imports the source before generation, requires complete
extraction, and saves analysis back to the same document. Provider errors preserve
their safe status/message and include X-Document-ID and error.details.document_id
when a source was imported.
Non-ready new records return REVIEW_NOT_READY from the stored-clauses endpoint;
they are not represented as successfully reviewed documents with zero concerns.
Reading sources, retrying
local extraction, downloading originals and reading old reviews never spend AI
tokens. The existing upload-and-analysis UI remains available; /import uses the
key-free source endpoint and opens the separate workspace preview.

## Review workspace

All routes below retain the local boundary and server-selected workspace.
GET, PUT and fixture operations do not read an AI key or call a provider;
generation and Ask are separate explicit actions. A stored source revision is required;
legacy analyses are left unchanged and require a separate PDF import.

- GET /api/v1/documents/{document_id}/review-workspace returns document_id,
  source_revision_id, revision, brief, runs, personal, ask_turns and fixture_available. It is
  read-only; an untouched workspace has revision 0 and no runs/personal work.
- PUT the same path accepts expected_revision and one operation. Supported types
  are set_brief (brief), set_draft/set_ask_draft/save_question (run_id, finding_id, text),
  set_marker (run_id, finding_id, marker), and set_position (run_id, position).
- POST /api/v1/documents/{document_id}/review-workspace/fixture accepts
  expected_revision and explicitly installs the synthetic customer-perspective
  example only for its exact source hash and complete extraction. Repeating the
  request returns the existing immutable fixture run without resetting work.

Brief fields are perspective (neutral/customer/provider/other), role (up to 200
characters) and priorities (up to 2000). Drafts/questions are limited to 5000
characters. Markers are not_marked/revisit/reviewed_by_me. Position contains view
(overview/findings/document/my_review), finding_id and evidence_span_id; IDs are
validated against that run/finding. Opening history is navigation, not review
completion. Resume stores the view, finding and evidence selection, not arbitrary
PDF scroll pixels. A saved question has one stable ID per finding and changes only on
an explicit save_question operation; draft updates do not add it to My review.

Successful mutations return the updated workspace and confirmed revision.
REVISION_CONFLICT returns 409 plus current_revision. A write with an uncertain
database outcome returns a safe 503; reload before deciding how to retry.
Conflicts never silently merge or overwrite newer data. Unknown request fields,
invalid operations and unsupported IDs are rejected. No run or personal work is
copied automatically across sources, runs or documents.

Fixture findings and evidence are labelled kind=fixture, not AI-generated output.
The server resolves exact stored spans; ambiguous/missing references refuse the
fixture rather than silently dropping findings. Editing a brief preserves the
run's original context. Ask drafts and attempts are independent of saved questions.

### AI review attempts

- POST /api/v1/documents/{document_id}/review-workspace/generate accepts
  expected_revision, request_id and model_id. The model must match the selected
  Settings model shown before starting. The saved brief is used; save edits first.
  It returns the updated workspace after one bounded provider request, including
  a terminal failed/incomplete run when generation does not yield valid output.
- The request_id becomes the run ID. A repeated ID returns the recorded attempt
  without calling OpenAI again, including after a lost response. A new ID requests
  a new paid review. Only one processing attempt per document is allowed.
- POST /api/v1/documents/{document_id}/review-workspace/runs/{run_id}/interrupt
  accepts expected_revision. It marks a processing attempt interrupted without a
  provider call. Late output cannot replace it. This is not provider cancellation;
  the request may already have incurred a charge.

Runs distinguish kind=fixture/ai and status=processing/ready/incomplete/failed/
interrupted. AI runs carry a source/context snapshot, overview_items with evidence,
findings, coverage, generation provenance, completed_at and safe failure information.
The legacy overview string is retained for authored fixtures; new AI overview
statements each require source references. Findings may be empty, not an assertion
that the agreement has no issues. A not_found finding must state coverage_basis.

Coverage identifies extracted and omitted physical pages and the all_extracted_text
input scope. Supplied text is not proof that the model considered every provision.
Reference validation failure withholds output and cannot become ready. Partial source
input stays incomplete. Reading saved runs and editing personal work need no key.

Evidence in saved responses contains source_revision_id, span_id, optional
end_span_id, page_number, quote and label. A non-null end_span_id identifies the
inclusive final anchor on the same physical page. The quote is the exact original
page slice from the first span's start through the final span's end, including
intervening whitespace and line breaks. The anchors must be ordered and consistent;
missing, reversed or cross-page endpoints are invalid. An omitted/null end_span_id
retains the original exact single-span contract, so existing runs and fixtures
remain readable without a migration. Position.evidence_span_id continues to select
the evidence's first span_id.

New generation uses a separate provider-only shape: evidence contains a supplied
passage_id and relevance label. The server resolves that ID to the canonical
range above; provider-authored quotations, pages and line IDs are not accepted.
Passage IDs are scoped to the prepared source, not new persisted extraction anchors.
No fuzzy matching or whitespace/case correction is performed. Page-local grouping
is a bounded navigation heuristic, not a promise of complete clauses or support for
every generated assertion. Exact evidence establishes wording/location, not semantic
correctness, legal applicability or review completeness.

After canonical passage expansion, the combined serialized overview_items/findings
envelope is limited to 1,000,000 UTF-8 bytes. Exceeding this per-result limit returns
an incomplete run with REVIEW_RESOLVED_OUTPUT_LIMIT, empty overview_items/findings
and retained available usage; it does not retry. This does not guarantee the total
size of a stored document containing multiple runs.

Model changes, source/input limits and missing credentials fail before paid work;
no model fallback or automatic paid retry is performed. If an HTTP/save outcome is
uncertain, reload first. The persisted processing record does not prove that a
provider is still running; explicit interruption permits a later deliberate review.

### Finding-scoped Ask attempts

- POST /api/v1/documents/{document_id}/review-workspace/runs/{run_id}/findings/{finding_id}/ask
  accepts expected_revision, request_id, model_id, question (1–5000 characters,
  nonblank) and include_history (default true). The displayed model must match
  Settings. The finding and original context come from the selected saved run;
  callers cannot supply another brief, source or arbitrary history. Ready or
  incomplete runs need a usable finding. This action can incur an API charge,
  including for findings in an authored synthetic example.
- The response is the full workspace with an ask_turns entry. A persisted
  request_id is idempotent; reusing it with another scope/question/model/history
  choice conflicts. At most one processing Ask per document is permitted. Reads,
  draft saves and navigation never dispatch another call.
- POST /api/v1/documents/{document_id}/review-workspace/ask/{turn_id}/interrupt
  accepts expected_revision. It marks processing work interrupted locally and
  fences later output. It does not cancel a provider request or establish that
  nothing was charged. Refresh saved state before deciding on another paid send.

Each Ask turn records run_id, finding_id, source_revision_id, question, created_at,
completed_at, status, answer, limitations, coverage, generation, failure and
history provenance. Answer items contain text and evidence using the same exact
source-range contract as review findings. Uncited clarification/uncertainty is not
source-verified. Status is processing/ready/incomplete/failed/interrupted; ready
means available, not legally verified. Invalid output is withheld. Known provider
usage remains available even when references fail.

include_history=true supplies up to six recent usable answers within the same
run/finding, respecting the latest successful fresh-question boundary. The
history_turn_ids list records the exact supplied turns; history_truncated discloses
older usable turns outside that bounded history. include_history=false sends a
fresh question with no conversation history while retaining the full extracted
source and original review context. Earlier saved answers are never deleted.
Over-budget source/context/history is rejected, not silently shortened; choose a
fresh question explicitly when conversation history causes the limit.

Personal ask_drafts use set_ask_draft and the existing revision-aware PUT path.
They do not change saved_questions, markers or ordinary question drafts. Existing
workspaces default to empty ask_turns and ask_drafts, so no backfill is necessary.
Ask attempts have bounded record/output/storage capacity; reaching a limit refuses
new work without removing earlier answers or requesting an automatic upgrade.

## Workspace settings

GET /api/v1/workspace returns:

- has_api_key and api_key_needs_reentry (booleans, never credential material)
- model_id and query_gate_model_id
- available_models: id, name, description, context_window, max_output_tokens,
  reasoning_efforts, default_reasoning_effort, input_price_per_million,
  output_price_per_million, pricing_verified_on, pricing_note and legacy
- retention_days (0 means keep until manually deleted)
- toast_notifications_enabled

PUT /api/v1/workspace/settings accepts any subset of model_id,
query_gate_model_id, retention_days and toast_notifications_enabled. Models
must be in the advertised catalog. Retention is 0..36500 days; enabling it can
delete already-old documents on the next cleanup run.

Both review and query preparation default to gpt-5.6-terra. Mini and Nano are
removed from the catalog and rejected on new saves/requests. Existing selections
of those retired IDs resolve to Terra; historical run metadata is unchanged.
Other saved selections remain unchanged, including legacy gpt-5.
Settings may return an unsupported historical ID so it can be replaced explicitly;
new saves must use the catalog. Catalog membership does not guarantee access for
a particular OpenAI account. Prices are dated standard USD base rates, not quotes
for complete reviews. The pricing note explains additional considerations.

PUT /api/v1/workspace/api-key accepts a JSON api_key field.
DELETE /api/v1/workspace/api-key removes the active credential.
Both return has_api_key only. Saving checks format and local persistence, not
OpenAI account access or balance; it makes no paid provider call.

## AI and saved data

Analysis, new chat answers and new rewrites need the configured key.
Reading saved documents, PDFs, clauses, chats and cached rewrites, managing
notes/flags, generating reports and deletion do not require an AI call.
File type/size and request-rate limits still apply; there is no library count cap.

New document responses can include analysis_generation, with per-stage model ID,
endpoint, reasoning_effort, max_completion_tokens and catalog_verified_on.
Clauses can include rewrite_generation; chat messages can include generation.
These fields are optional for historical results and do not imply a new AI call.

Unsupported/inaccessible selections and invalid model requests return safe 400
errors; provider quota/rate limits return 429, connectivity errors 503 and
incomplete/invalid provider output 502. There is no automatic model substitution.
Provider error bodies, credentials and submitted document content are not exposed.

## Responses

Application endpoints generally use:

~~~json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {}
}
~~~

PDF responses and framework documentation are exceptions. Errors must not
include key material, request bodies, document content or raw provider errors.
