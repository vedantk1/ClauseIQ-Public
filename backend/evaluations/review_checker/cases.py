"""Authored synthetic checker controls, separate from the model's input contract.

Expectations are engineering reference labels, not a semantic grader or legal
ground truth. Loading resolves only explicitly authored page/heading anchors; it
never searches for evidence to repair the candidate's claims.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from clauseiq_types.review import ReviewBrief, ReviewCoverage, ReviewEvidence, ReviewFinding, ReviewOverviewItem
from services.ai.review_passages import build_review_passages
from services.ai.text_extractor import TextExtractor
from tests.review_evaluation_cases import load_case, validate_case_source


CASE_IDS = (
    "convenience-wrong-finding", "convenience-wrong-overview",
    "acceptance-own-support", "archive-qualification", "format-absence-overstated",
    "change-approval-priority-gap", "convenience-supported", "archive-paraphrase",
    "format-narrow-question", "acceptance-focused-concise",
)
SOURCE_REVISION_ID = "synthetic-check-source"
BACKEND = Path(__file__).resolve().parents[2]
CASE_VERSION = "authored-check-v1"
_ISSUE_CATEGORIES = {"own_evidence_missing", "source_conflict", "qualification_missing", "absence_overstated"}


@dataclass(frozen=True)
class CheckerCase:
    case_id: str
    case_version: str
    fixture: str
    case_sha256: str
    document: dict
    candidate: dict
    expectations: dict


def _load_definition(case_id: str, backend: Path) -> dict:
    if case_id not in CASE_IDS:
        raise ValueError("Choose an allowlisted authored checker case")
    definition = json.loads((backend / "fixtures" / "review_checks" / f"{case_id}.json").read_text())
    required = {"case_id", "case_version", "source_case_id", "source_sha256", "scope", "context",
                "anchors", "overview_items", "findings", "expectations"}
    if (set(definition) != required or definition["case_id"] != case_id
            or definition["case_version"] != CASE_VERSION or not definition["scope"]):
        raise ValueError("The authored checker case metadata is invalid")
    return definition


def _validate_expectations(definition: dict) -> None:
    expectations = definition["expectations"]
    if set(expectations) != {"claim_issues", "priority_gaps", "must_not_flag"}:
        raise ValueError("The authored checker expectations are invalid")
    for key in expectations:
        if not isinstance(expectations[key], list):
            raise ValueError("The authored checker expectations must be lists")
    for issue in expectations["claim_issues"]:
        if set(issue) != {"target", "field", "exact_claim", "category", "reason", "source_anchors"}:
            raise ValueError("The authored claim expectation is invalid")
        target = issue["target"]
        if target.get("kind") == "finding" and set(target) == {"kind", "id"}:
            matches = [item for item in definition["findings"] if item["id"] == target["id"]]
        elif (target.get("kind") == "overview" and set(target) == {"kind", "index"}
              and type(target["index"]) is int and 0 <= target["index"] < len(definition["overview_items"])):
            matches = [definition["overview_items"][target["index"]]]
        else:
            matches = []
        if (len(matches) != 1 or not isinstance(matches[0].get(issue["field"]), str)
                or not issue["exact_claim"] or issue["exact_claim"] not in matches[0][issue["field"]]
                or issue["category"] not in _ISSUE_CATEGORIES or not issue["reason"]):
            raise ValueError("The authored expectation does not identify an exact candidate claim")
    for gap in expectations["priority_gaps"]:
        if (set(gap) != {"brief_quote", "reason", "source_anchors"} or not gap["brief_quote"]
                or gap["brief_quote"] not in definition["context"]["priorities"] or not gap["reason"]):
            raise ValueError("The authored priority expectation does not identify an exact brief excerpt")
    for expectation in expectations["claim_issues"] + expectations["priority_gaps"]:
        anchors = expectation["source_anchors"]
        if not isinstance(anchors, list) or not anchors or any(anchor not in definition["anchors"] for anchor in anchors):
            raise ValueError("The authored expectation has an unknown source anchor")
    if (not expectations["must_not_flag"]
            or any(not isinstance(item, str) or not item.strip() for item in expectations["must_not_flag"])):
        raise ValueError("Each authored case needs false-alarm reference criteria")


async def load_checker_case(case_id: str, *, backend: Path = BACKEND) -> CheckerCase:
    """Load one allowlisted full source and a small, explicitly scoped candidate.

The optional backend path is for offline isolated fixture tests, not a CLI path
override. The returned candidate contains neither answer keys nor case labels.
Each load returns detached data; changes cannot alter a later load's baseline.
"""
    definition = _load_definition(case_id, backend)
    reviewed_source = load_case(backend, definition["source_case_id"])
    if definition["source_sha256"] != reviewed_source["source_sha256"]:
        raise ValueError("The authored checker case source hash changed")
    pdf_path = backend.parent / "tests" / "fixtures" / "pdfs" / reviewed_source["fixture"]
    extraction = await TextExtractor().extract_source(pdf_path.read_bytes(), pdf_path.name)
    validate_case_source(reviewed_source, extraction)
    passages = build_review_passages(extraction, SOURCE_REVISION_ID)
    resolved = {}
    for anchor_id, anchor in definition["anchors"].items():
        if (set(anchor) != {"page", "heading_prefix"} or type(anchor["page"]) is not int
                or not isinstance(anchor["heading_prefix"], str) or not anchor["heading_prefix"].strip()):
            raise ValueError("The authored checker source anchor is invalid")
        matches = [passage for passage in passages if passage.page_number == anchor["page"]
                   and passage.text.startswith(anchor["heading_prefix"] + "\n")]
        if len(matches) != 1:
            raise ValueError("An authored checker passage anchor is missing or ambiguous")
        resolved[anchor_id] = matches[0]

    def evidence(items: list) -> list[dict]:
        result = []
        for item in items:
            if set(item) != {"anchor", "label"} or item["anchor"] not in resolved:
                raise ValueError("The authored candidate has an unknown evidence anchor")
            passage = resolved[item["anchor"]]
            result.append(ReviewEvidence(
                source_revision_id=SOURCE_REVISION_ID, span_id=passage.span_ids[0],
                end_span_id=passage.span_ids[-1], page_number=passage.page_number,
                quote=passage.text, label=item["label"],
            ).model_dump())
        return result

    _validate_expectations(definition)
    overview = [ReviewOverviewItem.model_validate(item | {"evidence": evidence(item["evidence"])}).model_dump()
                for item in definition["overview_items"]]
    findings = [ReviewFinding.model_validate(item | {"evidence": evidence(item["evidence"])}).model_dump()
                for item in definition["findings"]]
    if not overview or not findings or len({item["id"] for item in findings}) != len(findings):
        raise ValueError("Authored checker cases need an overview and uniquely identified findings")
    candidate = {
        "source_revision_id": SOURCE_REVISION_ID,
        "context": ReviewBrief.model_validate(definition["context"]).model_dump(),
        "overview_items": overview, "findings": findings,
        "coverage": ReviewCoverage(page_count=extraction.page_count,
                                   extracted_pages=list(range(1, extraction.page_count + 1)),
                                   omitted_pages=[]).model_dump(),
    }
    document = {
        "source_revision_id": SOURCE_REVISION_ID, "source_sha256": extraction.content_sha256,
        "source_extraction": extraction.model_dump(), "source_status": "stored",
        "has_pdf_file": True, "extraction_status": extraction.status,
    }
    digest = hashlib.sha256(json.dumps(definition, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return CheckerCase(case_id, definition["case_version"], reviewed_source["fixture"], digest,
                       document, candidate, deepcopy(definition["expectations"]))
