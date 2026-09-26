# Frozen synthetic library-retrieval questions

`dataset.json` is an authored **development regression set**, not a held-out
benchmark, legal checklist or evidence of production answer quality. It contains
24 questions: five exact-term, five paraphrase, five multi-document, five
exception/near-match, and four reviewed unanswerable cases.

`holdout.json` adds 20 questions (four per category), frozen before implementing
the dense/hybrid candidates. Its topics include staffing/subcontractors,
change-control approval, capacity, incident response, backups/restoration,
audit/testing safeguards, feedback, confidentiality exclusions and urgent updates.
Its labelled passages do not overlap development-set labels. Related variants
stay within the holdout, rather than being split into development and test.
Both splits use the **same known contracts**; this is not an unseen-document test,
blind study or independently annotated legal benchmark. Once results inform a
change, that set becomes regression data; new claims need a new untouched set.

The corpus is the seven existing synthetic PDFs. Six have text; the image-only
scan remains explicitly unavailable, not OCRed or silently treated as searched.
Consulting questions here are retrieval-specific; they are not generated-review
criteria or a claim that the reserved review-generation holdout was evaluated.
The planted instruction text is untrusted source data, never a directive.

Each relevant label includes a document identity, source revision, physical page,
canonical passage ID and authored exact wording. PDF hashes, extraction version,
passage version and the dataset SHA-256 are frozen. The harness validates every
label against actual PDF extraction before scoring. Whitespace normalization is
used only to check authored sentences across PDF line wraps; returned excerpts
must be verbatim substrings of their exact canonical passages. A source match
does not establish that an interpretation is correct.

From `backend`:

```bash
venv/bin/python -m evaluations.library_search_evaluation --limit 5
venv/bin/python -m pytest tests/test_library_search_evaluation.py
```

The first command prints JSON without reading application data, settings or keys,
without writing reports, and without provider calls. It runs the current pure
lexical search function. Expected labels and rationales never enter the query.

## Metrics and limits

- Document recall counts labelled relevant agreements found in the first `k`
  passage hits; document precision uses distinct returned document IDs.
- Passage recall requires the exact document/revision/page/passage identity.
  Passage precision divides relevant unique hits by `k`, including empty slots.
  Duplicate hits consume result positions without increasing relevance credit.
- Unanswerable cases have no artificial perfect-recall score. Their separate
  nonempty-result rate records how often lexical overlap still returns a hit.
  An empty result does not prove a topic absent from a real library.
- Invalid source identities or fabricated excerpts receive no relevance credit
  and are counted separately. Latency includes the search callable's preparation
  but excludes loading/extracting the fixed PDF corpus; p50/p95 use nearest rank.

Report overall and category-level results, including failures. Do not choose a
quality-pass threshold after seeing a run or turn these 24 questions into a broad
retrieval-accuracy claim. Multi-document questions have specific finite labels;
top-k recall does not establish exhaustive answers to “all” or “every”.

The development labels are intentionally visible and may be used for debugging.
The new question-family holdout must not be used to tune the current comparison.
`evaluations.retrieval_embeddings` prepares a fixed lexical/exact-dense/RRF-hybrid
experiment; its default dry run is key-free. Live embeddings require separately
approved spending; mocked tests are not semantic measurements. See
[the comparison protocol](../../../docs/EVALUATION.md#densehybrid-comparison)
and [commands](../../../docs/DEVELOPMENT.md#retrieval-comparison-experiment).
The [first live result](../../../docs/evaluations/LIBRARY_RETRIEVAL_V1.md) records
both improvements and regressions. After inspecting these results, do not treat
the same holdout as untouched evidence for subsequent tuning.
The [header/diversity follow-up](../../../docs/evaluations/LIBRARY_RETRIEVAL_REFINEMENT.md)
uses both unchanged datasets as inspected regression sets, reuses real cached
embeddings and records losses as well as gains. Fresh adversarial unit tests
check mechanics; they are not fresh semantic holdout questions.
Deliberate fixture/label changes require source review, a dataset version update
and a reviewed checksum update. Never refresh hashes simply to silence drift.
