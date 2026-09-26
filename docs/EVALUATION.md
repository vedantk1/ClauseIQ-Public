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
| Library retrieval | 24 labelled synthetic development questions and a local lexical-ranking harness | Passage/document retrieval regression, including missed passages and irrelevant near-matches |

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

| Product path | Current method | Evaluation status |
| --- | --- | --- |
| Individual review and finding-scoped Ask | Complete supported extracted source with bounded input | Source-reviewed criteria and a small recorded live baseline; known omissions remain |
| Library agreement-text search | Local BM25 ranking over canonical page passages | Implemented; offline development-set results below and real-stack search/page-navigation coverage |
| Retained earlier document chat | Embeddings and Qdrant retrieval followed by generation | Existing legacy RAG; not exercised by the Library retrieval benchmark |
| Library-wide answers | Planned retrieval followed by generation over selected evidence | Not implemented or evaluated |

The current review workspace and finding-scoped Ask use the complete supported
extracted source, subject to their input guards. They do not use top-k retrieval.
Retained earlier document chat uses Qdrant retrieval. Library agreement-text
search is a separate, key-free lexical baseline over current page-aware passages;
it does not generate cross-contract answers or claim hybrid/vector performance.

The frozen [24-question synthetic development set](../backend/fixtures/library_search_evaluations/README.md)
contains six searchable PDFs plus one image-only exclusion, with 203 canonical
passages. The initial local lexical run at five returned passages per question
reported:

| Retrieval measure | Initial result |
| --- | ---: |
| Macro document recall@5 / precision@5 | 93.3% / 54.8% |
| Macro exact-passage recall@5 / precision@5 | 80.8% / 25.0% |
| Exact-term / paraphrase passage recall@5 | 100% / 60% |
| Multi-document / exception passage recall@5 | 73.3% / 90% |
| Reviewed unanswerable queries returning a lexical match | 4 of 4 |
| Invalid source hits | 0 |

The dataset is visible and small, so these are local regression measurements,
not independent benchmark accuracy. In particular, a returned lexical match is
not an answer: all four no-answer cases still produced near-matches. Latency
depends on the computer and library size; the harness reports its own query
timings and excludes PDF extraction/preparation.

The synthetic retrieval set freezes source-relevant document/page/passage labels
for exact-term, paraphrase, multi-document, near-match and unanswerable questions.
Run the unpaid harness on the same corpus and query set when changing passage
construction or ranking. Record document and passage recall/precision at a fixed
result limit separately, along with latency, skipped sources and the dataset,
passage and extraction versions. Small authored fixtures are a regression set,
not a population-wide accuracy estimate. Do not tune on a held-out question
family and then report it as unseen performance.

Locating relevant passages and answering from them are separate evaluation
problems. Recall at a chosen result limit measures how many labelled relevant
passages were returned; it does not prove that every agreement in a collection
was inspected. Exact source identity and quote matching also do not establish
retrieval completeness. Any future retrieval-grounded answer evaluation must
hold the retrieved evidence fixed while assessing support, missed qualifications,
cross-document confusion and abstention; all/every claims additionally require
explicit collection coverage. No such generated-answer score is claimed here.

### Next comparison

The lexical baseline is a publishable result for this search implementation.
The broader retrieval/answer evaluation remains open. Before developing a new
ranker, freeze a separate holdout containing new question families and label its
relevant passages against the source. Use the visible 24-question set for
development, then compare lexical, dense and hybrid candidates under the same
corpus, passage construction, result limit and scoring rules. Report exact-term,
paraphrase, exception and multi-document results separately, plus near-matches on
unanswerable questions, query latency and indexing/query cost. Keep failures and
source exclusions in the report. No dense/hybrid result is available yet.

Source revision changes, partial indexing and deletion must have defined behavior
before a persistent vector index becomes a product dependency. Generated library
answers then need separate source-grounded assessments with fixed evidence inputs
and an end-to-end assessment that includes retrieval failures. Publish the dataset
and implementation versions, commands, sample counts and limitations alongside
results; keep a concise result/link in the README rather than an overall AI
accuracy badge.

## Operational evidence

The backend has correlated HTTP request/error logs and in-memory endpoint timings,
error counts and system metrics. Review and Ask preserve attempt outcomes and
generation metadata. These aid debugging but do not measure answer quality.
The current search endpoint has no persistent index and the retrieval harness
measures local query latency; neither provides durable retrieval-stage traces.

As retrieval stages are added, useful diagnostics include stage duration,
outcome, source/index version, collection coverage and provider usage where
applicable, linked to the request or paid attempt. Routine telemetry must omit
queries, source/answer text and credentials. This instrumentation is proposed;
there is no new external telemetry service, monitoring dashboard or operational
reliability claim attached to the offline scores.

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
