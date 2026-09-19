# Authored checker calibration cases

These ten deliberately authored candidates use the unchanged synthetic
managed-services-25p.pdf and service-terms-conflict.pdf sources. They are not
copied provider outputs, private contracts, expert legal judgments or a claim
that the checker works. Case version authored-check-v1 freezes these labels
before any checker API run. A change to a candidate or label needs a new case
version and fresh report attribution, not replacement of historical results.

Each JSON contains a focused review brief, candidate overview/findings, exact
page-and-heading evidence anchors, and separate manual expectations. The loader
checks the existing reviewed source hash and anchors, then resolves the authored
evidence into exact complete passages. It supplies the entire extracted source,
not only selected evidence. It never searches for better evidence to repair an
incorrect candidate. The case digest covers both candidate and reference labels.

Only document and candidate go to checker preparation. Scope descriptions, case
names, expected errors, source anchor aliases and must-not-flag criteria are
evaluation metadata; they never enter the request. Expectations are not a keyword
grader. Assess actual output against the source, recording misses and false
alarms separately, with reasons. A correct output shape or a reference pointing
to real text does not prove correct semantic assessment.

| Case | Intended calibration question |
| --- | --- |
| convenience-wrong-finding | Detect clause 62 evidence attached to a clause 63 convenience-exit finding; distinguish missing own support from a source contradiction. |
| convenience-wrong-overview | Apply the same own-support rule to the overview even when a finding has correct evidence. |
| acceptance-own-support | Notice the acceptance half of an invoice/acceptance comparison is true elsewhere but unsupported by the item's invoice-only evidence. |
| archive-qualification | Detect an unconditional request/duration claim and a no-cost inference despite full conditions appearing in the evidence and overview. |
| format-absence-overstated | Do not turn unspecified format particulars into proof that no agreement exists or must occur in future. |
| change-approval-priority-gap | Surface the A3 bilateral written-approval protection for an explicit charge-change priority; quotation alone is not explanatory coverage. |
| convenience-supported | Positive counterpart with clause 63 attached to both overview and finding. |
| archive-paraphrase | Accept a meaning-preserving paraphrase retaining duration, request timing, service scope and cost qualifications. |
| format-narrow-question | Accept absence limited to the supplied PDF, acknowledged outside-document uncertainty and a practical question. |
| acceptance-focused-concise | Accept a focused acceptance review without requiring low-relevance or explicitly excluded payment, liability and confidentiality topics. |

These candidates intentionally cover small declared review scopes. They test
specific failure boundaries; they do not represent complete contract reviews.
The negative cases may have related issues beyond the minimum listed expected
issue (for example, more than one assertion in a wrongly supported item). Do not
count a source-grounded additional issue as a false alarm merely because its
wording differs from a reference. Conversely, generic warnings do not count as
detecting the exact intended defect. Positive cases should not acquire material
claim issues or priority gaps solely to make reviews longer.

consulting-agreement-5p.pdf is reserved as a contrasting holdout for this checker.
Do not use its source or candidate answers to tune this initial prompt. It is not
allowlisted in this corpus and has no checker labels yet. Before any adoption
decision, create and source-review a holdout candidate after the calibration
prompt is frozen, then test it without rerolling or repair. Reserving a file here
does not claim that every historical project participant has never seen it.

Offline checks:

~~~bash
cd backend
venv/bin/python -m pytest tests/test_review_checker_cases.py -q
~~~

These tests make no API calls. Paid checker runs require explicit approval and
the separate opt-in harness. Keep captured provider outputs, assessments and
spending records in ignored local reports. Do not add the checker to the product
request path based only on this small calibration corpus.
