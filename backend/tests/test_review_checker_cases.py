"""Offline corpus/binding checks, not an automated semantic checker assessment."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from clauseiq_types.source import SourceExtraction
from evaluations.review_checker import cases
from evaluations.review_checker.contract import CheckCandidate
from evaluations.review_checker.preparation import prepare_check
from services.ai.review_passages import build_review_passages


BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", cases.CASE_IDS)
async def test_authored_cases_preserve_exact_sources_and_evidence_without_reference_label_leak(case_id):
    loaded = await cases.load_checker_case(case_id)
    definition = cases._load_definition(case_id, BACKEND)
    assert loaded.case_id == case_id
    assert loaded.case_version == cases.CASE_VERSION
    assert loaded.fixture == definition["source_case_id"] + ".pdf"
    assert loaded.case_sha256 == hashlib.sha256(json.dumps(
        definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    assert loaded.document["source_sha256"] == definition["source_sha256"]
    assert set(loaded.candidate) == {"source_revision_id", "context", "overview_items", "findings", "coverage"}
    assert loaded.candidate["source_revision_id"] == cases.SOURCE_REVISION_ID
    CheckCandidate.model_validate(loaded.candidate)
    before = deepcopy(loaded.candidate)
    prepared = prepare_check(loaded.document, loaded.candidate)
    assert loaded.candidate == before
    payload = json.loads(prepared.messages[1]["content"])
    extraction = SourceExtraction.model_validate(loaded.document["source_extraction"])
    passages = build_review_passages(extraction, cases.SOURCE_REVISION_ID)
    assert [(p["passage_id"], p["page_number"], p["text"]) for p in payload["source"]["passages"]] == [
        (passage.id, passage.page_number, passage.text) for passage in passages
    ]
    assert {p["page_number"] for p in payload["source"]["passages"]} == set(range(1, extraction.page_count + 1))
    canonical_ranges = {(p.page_number, p.span_ids[0], p.span_ids[-1], p.text) for p in passages}
    for item in loaded.candidate["overview_items"] + loaded.candidate["findings"]:
        for evidence in item["evidence"]:
            assert (evidence["page_number"], evidence["span_id"], evidence["end_span_id"], evidence["quote"]) in canonical_ranges
    assert "expectations" not in payload
    assert "scope" not in payload
    assert case_id not in prepared.messages[1]["content"]
    for expectation in loaded.expectations["claim_issues"] + loaded.expectations["priority_gaps"]:
        assert expectation["reason"] not in prepared.messages[1]["content"]
    for criterion in loaded.expectations["must_not_flag"]:
        assert criterion not in prepared.messages[1]["content"]


@pytest.mark.parametrize("case_id", cases.CASE_IDS)
def test_frozen_reference_claims_and_brief_excerpts_match_authored_candidate(case_id):
    definition = cases._load_definition(case_id, BACKEND)
    cases._validate_expectations(definition)
    used_anchors = {evidence["anchor"] for item in definition["overview_items"] + definition["findings"]
                    for evidence in item["evidence"]}
    used_anchors.update(anchor for expectation in definition["expectations"]["claim_issues"]
                        + definition["expectations"]["priority_gaps"] for anchor in expectation["source_anchors"])
    assert used_anchors == set(definition["anchors"]), "Do not retain unrelated case anchors"


def test_corpus_keeps_negative_and_positive_controls_and_an_untuned_holdout():
    definitions = [cases._load_definition(case_id, BACKEND) for case_id in cases.CASE_IDS]
    negatives = [d for d in definitions if d["expectations"]["claim_issues"] or d["expectations"]["priority_gaps"]]
    assert len(negatives) == 6
    assert len(definitions) - len(negatives) == 4
    assert {d["source_case_id"] for d in definitions} == {"managed-services-25p", "service-terms-conflict"}
    assert "consulting-agreement-5p" not in cases.CASE_IDS
    files = {p.stem for p in (BACKEND / "fixtures" / "review_checks").glob("*.json")}
    assert files == set(cases.CASE_IDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["unknown", "../convenience-supported", "convenience-supported.json", "consulting-agreement-5p"])
async def test_checker_case_allowlist_refuses_paths_unknown_cases_and_reserved_holdout(case_id):
    with pytest.raises(ValueError, match="allowlisted"):
        await cases.load_checker_case(case_id)


@pytest.mark.asyncio
async def test_changed_definition_source_hash_is_rejected_before_extraction(monkeypatch):
    definition = cases._load_definition("convenience-supported", BACKEND)
    definition["source_sha256"] = "0" * 64
    monkeypatch.setattr(cases, "_load_definition", lambda *args: definition)
    with pytest.raises(ValueError, match="hash changed"):
        await cases.load_checker_case("convenience-supported")


@pytest.mark.asyncio
async def test_wrong_heading_is_not_repaired_with_another_source_match(monkeypatch):
    definition = cases._load_definition("acceptance-focused-concise", BACKEND)
    definition["anchors"]["acceptance"]["heading_prefix"] = "3. Missing acceptance heading"
    monkeypatch.setattr(cases, "_load_definition", lambda *args: definition)
    with pytest.raises(ValueError, match="missing or ambiguous"):
        await cases.load_checker_case("acceptance-focused-concise")


@pytest.mark.parametrize("mutation", ["claim", "field", "target", "anchor", "priority"])
def test_reference_expectations_reject_drift_in_exact_targets_or_support(mutation):
    definition = cases._load_definition("convenience-wrong-finding", BACKEND)
    issue = definition["expectations"]["claim_issues"][0]
    if mutation == "claim":
        issue["exact_claim"] = "A fabricated reference label absent from the candidate"
    elif mutation == "field":
        issue["field"] = "not_a_field"
    elif mutation == "target":
        issue["target"]["id"] = "unknown"
    elif mutation == "anchor":
        issue["source_anchors"] = ["unknown"]
    else:
        definition["expectations"]["priority_gaps"] = [{
            "brief_quote": "not part of this brief", "reason": "Reference drift", "source_anchors": ["convenience"],
        }]
    with pytest.raises(ValueError):
        cases._validate_expectations(definition)


@pytest.mark.asyncio
async def test_loaded_candidates_and_labels_are_detached_from_future_loads():
    loaded = await cases.load_checker_case("acceptance-focused-concise")
    original_candidate = deepcopy(loaded.candidate)
    original_expectations = deepcopy(loaded.expectations)
    loaded.candidate["findings"][0]["facts"] = "Mutated only inside this test"
    loaded.expectations["must_not_flag"].clear()
    reloaded = await cases.load_checker_case("acceptance-focused-concise")
    assert reloaded.candidate == original_candidate
    assert reloaded.expectations == original_expectations
    assert reloaded.case_sha256 == loaded.case_sha256
