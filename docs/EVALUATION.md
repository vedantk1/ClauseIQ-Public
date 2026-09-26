# Evaluation

ClauseIQ separates application correctness from the quality of generated reviews.
A successful request, a matched quotation and a passing test suite measure
different things. None establishes a complete or legally reliable review.

## What exists

| Layer | Evidence | What it establishes |
| --- | --- | --- |
| Application contracts | Deterministic backend/frontend tests and unpaid browser checks | Source identity, scoped persistence, explicit dispatch, failure handling and navigation under the tested conditions |
| Generation references | Two source-reviewed synthetic cases with frozen criteria | A repeatable basis for assessing short and long reviews, not an automated semantic score |
| Diagnostic checker calibration | Ten authored candidates: six negative mutations and four positive controls | Known errors and valid counterexamples for evaluating the development-only checker |
| Import corpus | Seven synthetic PDFs, including scanned and adversarial inputs | Extraction and workflow edge cases; these are not seven labelled AI-quality benchmarks |

The generator cases are in
[backend/fixtures/review_evaluations](../backend/fixtures/review_evaluations/README.md).
Checker candidates and holdout rules are in
[backend/fixtures/review_checks](../backend/fixtures/review_checks/README.md).
The authored example shown in the workspace is a separate demonstration fixture,
not generated output or a passing evaluation result.

## Assessing review and Ask output

Use the normal application engines and immutable source PDFs. Reference criteria
and expected answers must stay outside model inputs. For each attempt, retain the
source/case version, prompt/schema version, model, reasoning effort, token usage,
latency and operational outcome. Failed, refused or uncertain attempts count;
do not drop them from the denominator or rerun until a good answer appears.

Assess these dimensions separately against the source:

- **Priority coverage:** record met, partial, missing or incorrect for each
  source-reviewed criterion. Do not require specific titles or finding counts.
- **Material qualifications:** check triggers, exceptions, time anchors, scope,
  costs and cross-page amendments together.
- **Own-citation support:** each paragraph or finding's displayed evidence must
  support its assertions. A correct citation elsewhere does not repair it.
- **Unsupported claims and uncertainty:** identify invented rights, calculations
  or deadlines; distinguish absent scenario facts from ambiguity in the text.

Exact-reference validation is a structural gate. An accepted reference can match
real source text while supporting only part of the associated claim. Report invalid
or rejected output separately from the semantic support of accepted output.
Likewise, an inline citation mapping establishes which saved passage an identifier
refers to, not whether the model interpreted that passage correctly.

Keep per-case results and source-grounded explanations. A small synthetic corpus
supports bounded regression comparisons, not a general accuracy percentage or a
claim about legal documents in the wild. The diagnostic checker is not an
independent ground truth: its misses and false alarms also need assessment.

## Retrieval boundary

The current review workspace and finding-scoped Ask use the complete supported
extracted source, subject to their input guards. They do not use top-k retrieval.
Retained earlier document chat uses Qdrant retrieval; library-wide retrieval is not
implemented and no measured library-search recall is claimed.

For a retrieval-based system, locating relevant passages and answering from them
are separate evaluation problems. Recall at a chosen result limit measures how
many labelled relevant passages were returned; it does not prove that every
agreement in a collection was inspected. Exact source identity and quote matching
also do not establish retrieval completeness.

## Running checks

Ordinary tests and CI make no paid AI calls. Commands, tokenizer preflight,
isolated storage/browser checks and explicit evaluation opt-ins are documented in
[Development](DEVELOPMENT.md#model-defaults-and-bounded-requests).

Live evaluations require an approved finite spending ceiling, current pricing,
fixed cases and stop conditions. The existing manual harnesses disable automatic
retry and model switching. Preserve reservations for uncertain outcomes. A stronger
model or a higher reasoning setting is a hypothesis to test, not a recorded fix.
Private outputs, assessments and budget ledgers remain ignored; they are not
published by running CI.
