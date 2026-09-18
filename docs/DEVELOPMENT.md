# Development

## Setup

Use Node.js 24+, Python 3.13+ and Docker with Docker Compose.

~~~bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
npm ci
npm run setup
~~~

No JWT, SMTP or admin-email setup is needed. Do not put an OpenAI key in an
environment file; enter it in the application's Settings when needed.

Check ports 3000, 8000, 27017, 6333 and 6334 before starting another service:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Open http://localhost:3000. Servers use development mode and loopback bindings.
MongoDB and Qdrant must both be available for workspace migration preflight.
Use matching compatible Qdrant server/client versions; an existing older Docker
image may need a separately reviewed upgrade before updating stored vectors.

## Commands

| Command | Purpose |
| --- | --- |
| npm run setup | Install dependencies and build shared types |
| npm run dev | Hot-reloading frontend and backend |
| npm test | Deterministic backend and frontend tests, no paid AI calls |
| npm run test:backend | Backend tests only |
| npm run test:frontend | Local API, persistence state, viewer adapter and render-contract tests |
| npm run typecheck | Frontend types |
| npm run lint | Frontend lint |
| npm run build | Shared types and frontend production build |
| npm run check | Complete deterministic validation sequence |

Focused commands:

~~~bash
docker compose -f docker-compose.dev.yml ps
cd backend && venv/bin/python -m pytest tests -v
npm --prefix shared run build
~~~

Optional isolated live storage checks (no OpenAI calls) are documented in
../backend/tests/README.md. They create and clean up only their own fixture stores.

For source import/extraction changes, focused checks include:

~~~bash
cd backend
venv/bin/python -m pytest tests/test_source_extraction.py tests/test_source_import.py tests/test_source_storage.py tests/test_source_analysis.py tests/test_source_error_responses.py -q
venv/bin/python tests/manual_source_smoke.py --run-isolated-live
~~~

The manual source smoke requires the existing development MongoDB only, not
Qdrant or a provider key. It uses a verified-absent disposable database, checks
real GridFS bytes/page anchors, retry/fencing and unrelated-data preservation,
then reports cleanup. Never point it at the application database.
This source increment is additive; no source backfill/migration or vector rebuild
is required. Existing analyses are not silently re-extracted or overwritten.

For review workspace persistence changes:

~~~bash
cd backend
venv/bin/python -m pytest tests/test_review_workspace.py tests/test_review_generation_lifecycle.py tests/test_review_generation.py tests/test_review_run_contract.py -q
venv/bin/python tests/manual_review_workspace_smoke.py --run-isolated-live
~~~

The review smoke uses an isolated synthetic database on the existing local MongoDB
service. It verifies fresh-connection restoration, competing revision writes,
scoping, immutable runs and deletion of nested personal work without
touching the application database. Its final report must show no leftovers.
It also checks real generation claims/finalization with a mocked provider,
same-ID replay, restart-visible interruption and fencing of late results after
deletion. It makes no provider or vector requests or saved credential reads.

For review evidence and quality-contract changes, run the focused offline checks:

~~~bash
cd backend
venv/bin/python -m pytest tests/test_review_passages.py tests/test_review_generation.py tests/test_review_run_contract.py tests/test_review_evaluation_cases.py tests/test_review_evaluation_guard.py -q
~~~

These check exact passage preservation, provider-reference resolution, historical
single-span compatibility and evaluation-case safety. They do not grade real model
interpretation. Passage grouping is derived from immutable extraction; it requires
no source migration, re-extraction or vector rebuild. Include frontend workspace
tests and type checking when changing the range-evidence display contract.

The /import and /workspace routes support source-backed AI reviews and a key-free
fixture preview. Import tests/fixtures/pdfs/managed-services-25p.pdf, then load its
labelled synthetic example to exercise findings and saved work. Other PDFs may be
imported and reviewed explicitly with AI, but never receive those example findings. Fixture
definitions ship under backend/fixtures/reviews; missing definitions disable the
example rather than inventing output. Existing /review analysis remains separate.
Focused frontend tests include delayed replies, conflicts, explicit saves,
debounced draft recovery, page navigation and exact source excerpt checks. Paid
generation is outside the normal save retry queue: unknown outcomes are reconciled
by GET, and any deliberate resend retains its original request ID/model/revision.
No automatic review occurs on import, navigation, brief changes or reload.

## Verification cadence

- Routine changes: add or update focused deterministic tests and run the affected
  tests, type checks and lint. Use the existing hot-reloading development servers.
  Documentation-only edits normally need link/content review and git diff --check.
- Broader checkpoints: batch manual UI testing and the full npm run check sequence
  after several related implementations or a substantial milestone. A production
  build and end-to-end manual walkthrough are not required after every small edit.
- Build earlier if the change affects bundling, dependency compatibility, Next.js
  configuration, generated shared output, or a defect only reproducible in a build.
  Rebuild only the affected package where sufficient; do not restart working
  services or rebuild Docker images without a relevant reason.
- Run targeted migration, data-integrity, local-access and credential checks when
  those boundaries change. Batch testing is not a reason to defer safety checks.
- Record what was checked, what is deferred to the next checkpoint, and any known
  failures. Mocked AI tests do not establish real model quality or actual cost.

### Synthetic PDF fixtures

tests/fixtures/pdfs contains explicitly synthetic PDFs spanning 1, 2, 5, 12 and
25 pages, their readable sources/manifest, and a deterministic generator. Keep
the small cases for fast diagnosis; use the longer agreements for late-page
extraction, distant cross-references, schedules and document-wide checks. Length
alone does not establish realistic difficulty or AI coverage. The corpus also
includes conflicting terms, untrusted embedded instructions and image-only input.
These are not real agreements or legally validated examples, and their presence
does not select a target contract family for the product.

From the repository root:

~~~bash
backend/venv/bin/python tests/fixtures/pdfs/generate.py --check
cd backend && venv/bin/python -m pytest tests/test_pdf_fixtures.py -q
~~~

See tests/fixtures/pdfs/README.md for regeneration and expectations. The default
tests perform local extraction checks only; no fixture is uploaded to the app or
sent to an AI provider automatically. Live model evaluation remains separately
approved and cost-capped.

## Existing local installations

### Model defaults and bounded requests

Workspace Settings selects the review model and an optional separate chat query
preparation model. Without a saved review choice, OPENAI_DEFAULT_MODEL can
override the catalog default (gpt-5.6-terra). Query preparation also defaults to
gpt-5.6-terra. Mini and Nano are no longer selectable or accepted for new requests;
old selections/default overrides for those two IDs resolve to Terra without
rewriting saved run attribution. Other saved choices take precedence over the
environment default. Unknown IDs produce an explicit error, not a fallback.

Provider limits/prices are maintained in backend/ai_models/models.py and checked
against the [official model catalog](https://developers.openai.com/api/docs/models).
GPT-5.6 reasoning supports none/low/medium/high/xhigh/max; retained GPT-5 models
support minimal/low/medium/high. Review calls explicitly use medium; query
preparation uses low. No new reasoning controls are required during onboarding.

Task completion budgets include reasoning and visible answer tokens. Override
these in the backend environment or backend/.env as needed:

| Setting | Default |
| --- | --- |
| AI_MAX_INPUT_TOKENS | 100000 |
| AI_CLASSIFICATION_MAX_COMPLETION_TOKENS | 1024 |
| AI_EXTRACTION_MAX_COMPLETION_TOKENS | 16000 |
| AI_REVIEW_MAX_COMPLETION_TOKENS | 16000 |
| AI_REVIEW_TIMEOUT_SECONDS | 120 (maximum 180) |
| AI_SUMMARY_MAX_COMPLETION_TOKENS | 4000 |
| AI_REWRITE_MAX_COMPLETION_TOKENS | 6000 |
| AI_QUERY_GATE_MAX_COMPLETION_TOKENS | 1024 |
| AI_QUERY_REWRITE_MAX_COMPLETION_TOKENS | 2048 |
| AI_CHAT_MAX_COMPLETION_TOKENS | 4000 |

The input cap applies to the complete estimated message input, not just document
text; a 2,048-token capacity margin is also reserved. Completion settings clamp
to the model's output maximum. Invalid budgets fail visibly. These are per-call
limits, not an account-level monetary cap. The legacy analysis makes multiple calls;
the new source-backed review makes one strict-schema call, with schema overhead
included in its input guard. Its SDK retries are disabled and its total provider
wait is bounded by AI_REVIEW_TIMEOUT_SECONDS, including connection time.
Oversized prompts are rejected, not silently truncated. Partial-output failures
do not trigger an automatic larger or more expensive retry.

The existing OpenAI Python SDK remains pinned: deterministic tests exercise its
actual Chat Completions serialization through a local mock transport for every
supported ID. This is request compatibility coverage, not a live provider-access
or output-quality guarantee. tiktoken may download its public tokenizer vocabulary
on first use; it is cached locally and contains no document or credential data.

Paid evaluation is separate: agree on models, synthetic/public fixtures, a finite
spending ceiling and stop conditions before making calls. Record correctness,
grounding, latency and actual usage—not just a successful HTTP response. Do not
paste keys into test files or use confidential agreements as evaluation fixtures.

A separately authorized, single-call check is available in
backend/tests/manual_review_generation_check.py (run from backend). It is fixed
to GPT-5.6 Terra and accepts only the source-reviewed cases in
backend/fixtures/review_evaluations. Use --case managed-services-25p (the default)
for cross-page commercial/exit provisions or --case service-terms-conflict for
the contrasting two-page payment-deadline conflict and delivery table. The harness
verifies each PDF hash, page count and authored source anchors. It sends only the
case's brief and normal extracted source to the model, never expected answers or
assessment criteria. It reads the key through the normal credential service and
leaves the application library/Settings unchanged.

No paid call is part of ordinary tests. Obtain approval and recheck official
pricing and remaining approved spend before supplying --run-paid, --cap-usd,
--previous-reserved-usd and a unique --report-name. Caps and prior reservations must
be finite; each invocation permits at most one provider dispatch. There is no
automatic retry, model fallback or second grading call. The local
report reserves a conservative text-request byte/framing bound plus the completion
budget, including applicable long-context and cache-write uplifts, before dispatch.
Only the fixed text-only request shape can use this guard; changed payloads fail
closed. An existing report name refuses another call. Prior spend/reservations must
be supplied explicitly; this is not an automatically reconciled account budget.
Retain the full reservation for uncertain outcomes. Reports remain ignored under
.local-only. Only this allowlisted synthetic diagnostic retains raw response message
content; application generation does not. Reports record case/version/criteria
provenance and leave semantic assessment explicitly unassessed.

Use backend/fixtures/review_evaluations/README.md for the manual assessment method.
Record met/partial/missing/incorrect against source-reviewed criteria, assess each
finding's own supporting passages, and record incorrect claims outside the checklist
too. Check material triggers, scope, deadlines, exceptions and costs together;
evidence elsewhere in the output does not repair unsupported claims in a finding.
Do not require fixed titles, wording or finding counts, and do not substitute
keyword matches for semantic assessment. Source-anchor tests and a ready result
establish provenance/structural acceptance, not a passed quality evaluation.

### Workspace migration

Back up MongoDB, GridFS and Qdrant before the first workspace-mode startup.
Do not clear volumes or replace an existing .env file to fix a startup issue.

Startup checks ownership across all stores, then adds workspace metadata
without deleting accounts, legacy ownership fields, original ciphertext or
document relationships. A migration marker makes interrupted runs restartable.
Inherited automatic deletion is disabled; re-enable it only deliberately in
Settings. Legacy document-count settings are no longer enforced.

Multiple old accounts, missing ownership or conflicting data stop startup
rather than silently merging libraries. Select/import the intended data into
a separate local installation with an explicit migration plan; there is no
automatic account-selection or destructive reset command.

A single legacy key can be re-encrypted if the old API_KEY_ENCRYPTION_SECRET
(or its old JWT_SECRET_KEY fallback) remains available in the backend environment
or its existing .env. These values are used only for legacy decryption, not
new account functionality. If unavailable, Settings shows that key re-entry is
needed; document access is unaffected and the original ciphertext is preserved.

## Credential state and backups

The first key save creates backend/.local-only/workspace/credential.key with
owner-only permissions. WORKSPACE_STATE_DIR overrides the directory, relative
to backend unless absolute. This is ignored runtime data, not source.

Back up the database and credential directory together. Full Compose uses the
backend_credentials volume instead. Host development and full Compose use
different data/credential volumes; switching workflows is not a data migration.
A missing key file requires restoration or explicit key re-entry, never a reset
of the document library.

## Troubleshooting

- Database/vector startup failure: check Docker and both development services.
- Migration refusal: preserve data, read the ownership error and plan an explicit
  import. Repeated restarts cannot resolve ambiguous ownership.
- Key not usable: re-enter it in Settings, or restore the matching credential
  state. Saving does not validate OpenAI balance/model access.
- Local-access denial: use localhost, the configured frontend port and the
  X-ClauseIQ-Local: 1 request header; do not broaden CORS to external origins.
- Frontend API failure: NEXT_PUBLIC_API_URL defaults to http://localhost:8000.
  Restart frontend development after changing public environment values.
- Type-check errors referring to removed routes after switching revisions:
  regenerate Next.js types with a fresh frontend build.

See ../DOCKER.md for container smoke testing. Hosted deployment is unsupported.
