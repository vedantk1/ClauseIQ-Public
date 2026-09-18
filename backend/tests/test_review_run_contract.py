"""Persisted AI attempts cannot masquerade as completed source-backed reviews."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from clauseiq_types.review import ReviewCoverage, ReviewEvidence, ReviewRun, StartReviewRequest


def attempt():
    return {
        "id": "attempt-1", "kind": "ai", "status": "processing",
        "source_revision_id": "source-1", "created_at": "synthetic-time", "context": {},
        "coverage": {"page_count": 2, "extracted_pages": [1, 2], "omitted_pages": []},
        "generation": {
            "model_id": "gpt-5.6-terra", "reasoning_effort": "medium",
            "max_completion_tokens": 16000, "catalog_verified_on": "synthetic-date",
            "prompt_version": "test-v1", "schema_version": "test-v1",
            "extraction_version": "test-v1", "estimated_input_tokens": 100,
        },
    }


def overview():
    return [{"text": "Synthetic source fact", "evidence": [{
        "source_revision_id": "source-1", "span_id": "span-1", "page_number": 1,
        "quote": "Synthetic source fact", "label": "Source",
    }]}]


@pytest.mark.parametrize("pages,omitted", [([1, 1], []), ([1], []), ([0, 1], []), ([1], [1]), ([1, 2], [3])])
def test_coverage_accounts_for_each_physical_page_once(pages, omitted):
    with pytest.raises(ValidationError):
        ReviewCoverage(page_count=2, extracted_pages=pages, omitted_pages=omitted)


def test_complete_and_partial_coverage_contract():
    assert ReviewCoverage(page_count=2, extracted_pages=[1], omitted_pages=[2]).omitted_pages == [2]
    assert ReviewRun.model_validate(attempt()).status == "processing"


@pytest.mark.parametrize("change", [
    {"generation": None}, {"coverage": None}, {"overview": "Unfinished review"},
    {"overview_items": overview()}, {"status": "failed"},
    {"status": "ready", "completed_at": "synthetic-time"},
    {"status": "ready", "completed_at": "synthetic-time", "overview_items": overview(),
     "failure": {"code": "INVALID", "message": "Invalid output"}},
    {"status": "ready", "completed_at": "synthetic-time", "overview_items": overview(),
     "coverage": {"page_count": 2, "extracted_pages": [1], "omitted_pages": [2]}},
])
def test_unfinished_or_inconsistent_runs_cannot_claim_ready(change):
    with pytest.raises(ValidationError):
        ReviewRun.model_validate({**attempt(), **deepcopy(change)})


def test_zero_findings_can_have_a_sourced_overview_without_inventing_findings():
    ready = ReviewRun.model_validate({**attempt(), "status": "ready",
                                     "completed_at": "synthetic-time", "overview_items": overview()})
    assert ready.findings == []


def test_old_fixture_remains_readable_without_invented_ai_metadata():
    fixture = ReviewRun(id="fixture-1", kind="fixture", source_revision_id="source-1",
                        created_at="synthetic-time", context={}, fixture_version="v1", overview="Authored example")
    assert fixture.generation is None and fixture.status == "ready"


@pytest.mark.parametrize("end_anchor", [None, "span-1", "span-3"])
def test_evidence_range_contract_round_trips_without_altering_unicode_or_whitespace(end_anchor):
    evidence = overview()[0]["evidence"][0]
    evidence.update(end_span_id=end_anchor, quote="🙂 Rule applies.\n  Only if requested.\nCharges continue.")
    parsed = ReviewEvidence.model_validate(evidence)
    restored = ReviewEvidence.model_validate_json(parsed.model_dump_json())
    assert restored.end_span_id == end_anchor
    assert restored.quote == evidence["quote"]
    assert restored.span_id == "span-1"
    run = ReviewRun.model_validate({**attempt(), "status": "ready", "completed_at": "synthetic-time",
                                   "overview_items": [{"text": "Qualified rule", "evidence": [evidence]}]})
    assert ReviewRun.model_validate_json(run.model_dump_json()).overview_items[0].evidence[0] == restored


def test_legacy_evidence_omits_range_anchor_without_inventing_one():
    evidence = ReviewEvidence.model_validate(overview()[0]["evidence"][0])
    assert evidence.end_span_id is None
    assert "end_span_id" not in evidence.model_dump(exclude_none=True)


@pytest.mark.parametrize("end_anchor", ["", "not an id", "span.1", "x" * 129, 1, True])
def test_evidence_range_anchor_has_the_same_strict_identity_contract_as_start(end_anchor):
    with pytest.raises(ValidationError):
        ReviewEvidence.model_validate({**overview()[0]["evidence"][0], "end_span_id": end_anchor})


@pytest.mark.parametrize("model_id", ["gpt-5-mini", "gpt-5-nano"])
def test_retired_model_attribution_remains_readable_in_saved_runs(model_id):
    historical = attempt()
    historical["generation"]["model_id"] = model_id
    historical.update(status="ready", completed_at="synthetic-time", overview_items=overview())
    restored = ReviewRun.model_validate(historical)
    assert restored.generation.model_id == model_id
    assert restored.status == "ready"


@pytest.mark.parametrize("mutation", [
    {"expected_revision": True}, {"request_id": "dot.id"}, {"request_id": ""},
    {"model_id": ""}, {"workspace_id": "other"}, {"api_key": "not-a-credential"},
])
def test_start_request_is_bounded_and_cannot_supply_scope_or_credentials(mutation):
    with pytest.raises(ValidationError):
        StartReviewRequest.model_validate({"expected_revision": 0, "request_id": "r1",
                                          "model_id": "gpt-5.6-terra", **mutation})
