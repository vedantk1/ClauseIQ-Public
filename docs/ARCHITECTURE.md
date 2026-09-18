# Architecture

ClauseIQ is a single-person local application. It has one server-selected
workspace namespace (`local`), not a default user, membership model or account.

| Component | Responsibility |
| --- | --- |
| Next.js | Upload, review, document library, chat, analytics and Settings |
| FastAPI | Local request boundary, document processing and AI orchestration |
| MongoDB / GridFS | Documents, PDFs, interactions, chats, settings and encrypted credentials |
| Qdrant | Per-document vector data for retrieval-augmented chat |

Shared Python and TypeScript domain types live in shared/clauseiq_types.

## Document flow

1. The local browser submits a PDF with the local-request marker.
2. The backend validates the file and supplies its own workspace identifier.
3. The backend creates a document/source revision and stores the original PDF
   before local page-aware extraction or AI analysis. Import itself needs no key.
4. Explicit legacy analysis uses a request-scoped personal OpenAI client. It
   updates that same document; indexing is separate from saving its analysis.
   Documents, PDFs and embeddings retain document and workspace identifiers.
5. The frontend renders the PDF alongside the structured review.
6. Chat checks the requested document, retrieves only its workspace/document
   vectors and persists messages with that document.

Reading saved analysis does not make a new AI request. Deleting a document
must remove its files, vector chunks, interactions and embedded chat; failures
must be reported rather than claiming complete deletion.

## Original sources and extraction

services/source_service.py owns local import and extraction; it never requests
credentials, generation or embeddings. The original file, content SHA-256 and
source-revision ID are retained before extraction. Source and extraction status
are distinct from analysis status; a stored PDF is not a completed review.

services/ai/text_extractor.py extracts in a worker thread from in-memory bytes.
Each PDF page retains its one-based position, exact extracted text, empty/failed
state and deterministic line-span IDs. Offsets count Unicode code points from
the start of the page text and are end-exclusive, not JavaScript UTF-16 indices
or PDF geometry. IDs incorporate the file hash, extractor/version and location.
These anchors match extracted text; they do not establish layout fidelity,
interpretation accuracy or comprehensive review. No OCR is performed.

The page-aware snapshot is immutable once published. Retrying a completed,
partial or unavailable extraction returns the saved snapshot. Failed/pending
extractions can be retried against the same original; an explicit restart can
supersede an interrupted processing attempt. Conditional workspace/document and
attempt-token updates reject late results. This restarts local extraction only,
never a paid AI request. A storage-status interruption can be reconciled only
from a readable original that matches the recorded hash.

Malformed/encrypted PDFs can remain stored with failed extraction; empty or
unreadable pages remain visible as limitations. The legacy analyze path currently
requires complete text extraction; it will not silently analyze a partial prefix.
Generation failure retains the original/source snapshot and records failed
analysis. New imports have explicit status, while legacy records without source
metadata stay readable without inventing provenance or migrating their findings.
The library and review screen distinguish non-ready imports from completed legacy
analysis. The key-free import UI opens a separate review workspace preview;
the existing analysis screen remains available without converting old clauses.

Source metadata and page snapshots live in the existing scoped document record;
no migration, new database or vector reindex is needed. GridFS pointer writes are
confirmed before reporting success. On an uncertain outcome, potentially attached
files are retained rather than deleted. Only a confirmed-unattached new file is
eligible for rollback; previous originals are preserved.

## Review workspace

The /import and /workspace frontend routes are independent of the legacy /review
screen. services/review_workspace_service.py stores a review_workspace object in
the existing document, using the same workspace/document boundary. Deleting that
document also deletes its review state; there is no new collection, migration or
legacy-note conversion. GET returns an empty default without writing anything.

The workspace keeps the current brief, immutable review runs and personal work
separate. Runs snapshot their source revision and context; editing the brief
does not reinterpret existing findings. Personal data is scoped by run/finding:
recoverable drafts, explicitly saved questions, explicit reversible markers and
navigation/opened history are distinct. Reading a finding never marks it reviewed.
Saving wording does not send it, accept a term or resolve a finding.

Updates carry an expected workspace revision and a typed operation. An atomic
conditional document update rejects stale writes; it never upserts or changes
identity. The frontend serializes its own writes and debounces draft recovery.
It keeps newer local wording while a response is pending and preserves the last
confirmed saved question after failure. Cross-tab conflicts stop the queue; the
person must reload saved state and explicitly choose whether to apply pending
edits. Unconfirmed browser-only edits are not promised to survive a hard close.

An explicitly requested synthetic fixture run is also available.
The fixture definition ships in backend/fixtures/reviews, is bound to the unchanged
25-page synthetic PDF SHA-256 and resolves each evidence match uniquely against
persisted page spans. Arbitrary files never receive these example findings.
The fixed Example Customer scenario is labelled and does not overwrite the
person's brief. No generation, embeddings, credential reads or paid retries are
part of the fixture path. Contextual Ask remains a later increment.

### Explicit review generation

services/ai/review_generation.py owns the versioned prompt, strict structured
output and source-reference validation. It supplies all successfully extracted
nonblank text as ordered page-local passages plus the saved brief. Initial review
does not use top-k vector retrieval, make embedding requests, truncate the source, or migrate
the retained Chat Completions endpoint. Input budgeting includes messages and the
output schema; the completion allowance is a separate configurable spending guard.

services/ai/review_passages.py derives these passages without changing stored
extraction. Generic numbering and blank separators guide grouping; bounded fallback
groups prefer sentence boundaries. Each original line anchor remains in exactly one
passage, including headings, tables and page noise. Ordinary groups are limited to
4,000 characters and 32 spans; a longer single line remains intact up to 20,000
characters or fails before dispatch. Physical page boundaries and forced splits
carry conservative continuation flags. These are navigation heuristics, not proof
that a passage is a complete clause or that adjacent pages are semantically joined.

The new output separates source facts, interpretation, uncertainty and possible
actions. Overview statements have evidence too. The provider returns supplied
passage IDs and relevance labels, not authoritative quotations, page numbers or
line IDs. The server resolves each ID within the prepared snapshot and publishes
its exact original text with the source revision, physical page, first span_id and
inclusive end_span_id. Unknown or repeated IDs in one evidence list are rejected;
there is no excerpt repair, fuzzy matching or search for a different passage.
A reference-validation failure withholds the generated output and records an
incomplete result rather than dropping a
finding silently. Missing-term findings require a stated reviewed scope. This
validation establishes wording and location, not truth, applicability or legal
completeness. Partly extracted input remains incomplete even if every returned
reference resolves. Unsupported input and zero findings are not a clean bill of health.

Canonical passage expansion also has a per-result safety bound:
MAX_RESOLVED_REVIEW_BYTES limits the combined serialized overview_items/findings
envelope to 1,000,000 UTF-8 bytes, checked incrementally as items are resolved.
Exceeding it records incomplete/REVIEW_RESOLVED_OUTPUT_LIMIT, withholds all generated
overview/findings, retains available usage and makes no retry. This is not a total
stored-document-size guarantee or a migration policy.

The prompt requires each finding and overview item to carry its own support for
material assertions, including relevant conditions, exceptions and costs. Evidence
elsewhere in the review does not make a finding self-contained. These instructions
are quality targets, not a semantic validator. The source-reviewed synthetic cases
in backend/fixtures/review_evaluations provide separate manual assessment criteria;
they never enter the production prompt or prescribe a fixed finding count.

services/review_generation_service.py owns the persisted attempt lifecycle. The
explicit generation request checks the saved workspace revision and displayed
model against Settings, snapshots the source/brief/model, and conditionally saves
a processing run before contacting OpenAI with the person's request-scoped key.
The request ID is the run ID. Replaying that ID returns its existing state, never
another paid call. Provider retries and automatic model fallback are disabled on
this path. A new request ID is a deliberate new review, not recovery of the old one.

Finalization rereads and conditionally updates the workspace, preserving concurrent
personal edits. Completed runs retain prompt/schema/extraction versions, model,
estimated input, actual usage when returned, duration and safe failure information.
Source changes, deletion and explicit interruption fence late results. Terminal
runs and older personal work are not overwritten by a new run. A process loss can
leave a processing attempt; read-only refresh and explicit interruption expose
that uncertainty without replaying paid work. Interruption does not cancel or
refund a provider request, and exactly-once billing is not promised. There is no
background worker or automatic restart recovery in this increment.

### Evidence display and PDF adapter

The preview checks source revision, page-local anchor order and the exact Unicode
code-point slice before presenting evidence as matched. For end_span_id ranges,
it verifies the inclusive anchor sequence and all original text between the first
and last anchor. Missing, reversed, cross-page or inconsistent ranges are not
repaired. An omitted/null end_span_id retains the legacy exact single-span contract;
older saved runs and authored fixtures need no migration. It shows surrounding
extracted text and requests the corresponding physical PDF page through a small renderer adapter.
It never passes evidence to the legacy fuzzy highlighter or invents rectangles.
Quote matching does not verify interpretation, layout fidelity or completeness.

The current React PDF Viewer renderer remains isolated behind PDFViewer for this
increment, with isEvalSupported:false preserved. Its upstream is archived and its
declared PDF.js peer range does not support a blind modern PDF.js override.
Replacement is a separate bounded dependency milestone, not completed by this
adapter; see SECURITY.md. New geometry-based highlighting must be validated
against the original before it can be described as exact.

## Settings and credentials

The workspace service separates key handling from document operations.
Settings expose key presence only, the review/query-preparation model catalog,
optional retention and presentation preferences. No account, SMTP, role,
database-browser or raw-log administration routes remain.

A random encryption key is generated automatically in the backend's private
runtime directory on the first key save. Only encrypted API-key material is
stored in MongoDB. The decrypting key is owner-readable, excluded from Git and
Docker build contexts, and persisted in a separate volume in full Compose.
Missing state does not silently generate a replacement during decryption.

## Local request boundary

The application ports bind to loopback by default. The API validates loopback
Host names, exact configured browser Origins and the X-ClauseIQ-Local header.
The header is a browser preflight marker, not a password. See SECURITY.md for
the trusted-OS-user boundary and limitations.

## Model selection and request contracts

backend/ai_models/models.py is the canonical model catalog. The workspace API
serves its names, limits, reasoning options and dated base prices to the frontend;
the UI does not maintain a second catalog. New installations use GPT-5.6 Terra
for review and optional chat query preparation. Luna and Sol remain selectable;
an existing GPT-5 selection remains usable as legacy. Mini and Nano are removed
from the active catalog. Their old saved choices or environment defaults resolve
to Terra, without rewriting historical run attribution or other preferences.
Other stored choices take precedence over the initial default. Unknown saved IDs
remain visible and fail explicitly instead of silently selecting another model.

Classification, clause extraction, structured summaries, clause rewrites and
chat answers honor the review model. Chat context detection and query rewriting
honor the separate advanced model. Both choices use request-scoped personal
credentials. Database errors must not be mistaken for an unset model preference.

services/ai/generation.py validates every generation call against that catalog,
uses Chat Completions with explicit reasoning effort and completion limits, and
disables provider-side response storage with store=false. This is not a promise
of Zero Data Retention; OpenAI's account/data policies still apply. It reports
safe errors for unavailable models, provider failures, refusals, empty output and
incomplete completions. Structured analysis validates its output before saving.
Oversized requests fail before generation rather than silently reviewing a prefix.

services/ai/token_utils.py separates model capacities from task spending budgets.
Larger model capacity never automatically increases output allowances. Token
counts are local estimates using o200k_base, not provider billing measurements.
See DEVELOPMENT.md for budget overrides and evaluation limits.

New analysis results record model ID, endpoint, reasoning effort, completion
budget and catalog verification date per stage in analysis_generation. New
rewrites and chat answers record rewrite_generation and generation respectively.
Old saved results remain valid without this metadata. Cached rewrites keep their
original attribution and are not regenerated merely by changing Settings.

## Migration

Startup preflights MongoDB, GridFS and Qdrant before applying an additive,
restartable migration. Zero or one legacy owner is supported automatically.
Multiple owners, ambiguous ownership or conflicting workspace data stop startup
for an explicit data-selection decision. Existing account rows, ciphertext,
legacy owner fields, document IDs and relationships are not deleted.

Inherited retention is disabled during the first migration; newly opted-in
retention is preserved on later restarts. A decryptable legacy API key is copied
into the new credential store. If its old encryption secret is unavailable, the
library remains usable and Settings requests key re-entry.

## Scope

Next.js, FastAPI, MongoDB and Qdrant are retained. Embeddings remain
text-embedding-3-large with 3,072-dimensional vectors; no reindex is required.
This version does not introduce a job queue, a Responses API migration, offline
inference, team support or agent orchestration.
