# Source-reviewed synthetic evaluation cases

These cases are finite manual evaluation references for the explicit paid-review
harness, separate from the authored workspace demonstration in `../reviews`.
They contain fictional scenario briefs, immutable PDF hashes, physical-page
source anchors and expected relationships. They are not model answers, legal
advice, an exhaustive legal checklist, or production prompt material.

The harness sends only the case's brief and PDF extraction through the normal
review generator. It records the case/version and this directory's criteria
reference in its ignored report; it never supplies expectations to the model.
The current harness fixes GPT-6 Sol; earlier Terra reports retain their original
model attribution and remain separate baselines. Each invocation makes at most one
provider call; no automatic retry, model fallback or second grading call occurs.

## Manual assessment

For each criterion record **met**, **partial**, **missing**, or **incorrect**, with
the actual overview/finding identifier and a source-grounded explanation. Evaluate
the review as a whole for priority coverage. Evaluate every material assertion
within each finding against that finding's own evidence: a related quotation in
another finding or overview does not repair its missing support. Record incorrect
claims even if they are outside a listed criterion.

Assess these dimensions separately:

- Priority coverage: relevant issues may be combined or split; no fixed finding
  count, title, wording, ordering, or risk label is required.
- Conditions and costs: preserve the trigger, deadline anchor, scope, exceptions,
  payment consequences and existing protections together where material.
- Claim support: displayed passages must substantiate the whole assertion, not
  just contain a matching number or appear on a relevant page.
- Uncertainty: distinguish missing scenario facts, genuine textual ambiguity and
  practical follow-up questions. Do not invent dates, hierarchy or legal effect.

`priority` criteria are deliberately bounded to the supplied brief. `supporting`
criteria are useful contextual checks, not an unlimited completeness requirement.
All must-not claims remain errors if asserted. A `ready` application result proves
structural/source-reference acceptance only, not this manual assessment's outcome.
Do not turn these criteria into keyword scores or an automatic semantic pass.

The offline case test validates hashes, complete extraction, exact authored
wording and the stated physical page. It collapses whitespace only for PDF line
wrapping of reference sentences, never to loosen production citation matching.
It does not grade generated reviews. Missing-band or missing-event expectations
are source-review judgments, not assertions proved by a substring test.

## Cases

| Case | Scenario | Distinction exercised |
| --- | --- | --- |
| `managed-services-25p` | Customer: charges, document access and orderly exit | Cross-page amendments, calculation dependencies, conditional extensions and interlocking protections |
| `service-terms-conflict` | Customer: payment timing/amount, acceptance and ending work | Short agreement with an unresolved 30-day/7-day conflict, delivery table and conditional notice/payment duties |

Keep versioned expectations synchronized with the reviewed PDFs and authored
sources; never silently rewrite a fixture hash to make a failing check pass.
Run `venv/bin/python -m pytest tests/test_review_evaluation_cases.py
tests/test_review_evaluation_guard.py` from `backend` for offline safety checks.
