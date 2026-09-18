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
| /api/v1/analysis | Upload/analysis, stored clauses, notes, flags and rewrites |
| /api/v1/chat | Document sessions, messages, history and status |
| /api/v1/analytics | Workspace dashboard |
| /api/v1/reports | Document PDF reports |
| /api/v1/health | Local health checks |
| /api/v1/app-config | Non-sensitive presentation settings |

Account, admin and AI-debug routes are removed. The server supplies workspace_id;
request data cannot change the workspace. Document IDs remain required for
document-specific operations.

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
There is no new paid retry endpoint in this increment. Reading sources, retrying
local extraction, downloading originals and reading old reviews never spend AI
tokens. The existing upload UI remains combined until the new brief flow lands.

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

The fresh review default is gpt-5.6-luna; query preparation defaults to
gpt-5-nano. Existing saved selections remain unchanged, including legacy gpt-5.
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
