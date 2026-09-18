"""Allowlisted, source-bound manual evaluation cases; never model instructions."""

import json
from pathlib import Path
import re


CASE_IDS = ("managed-services-25p", "service-terms-conflict")
DEFAULT_CASE = CASE_IDS[0]


def load_case(backend: Path, case_id: str) -> dict:
    if case_id not in CASE_IDS:
        raise ValueError("Choose an allowlisted synthetic evaluation case")
    case = json.loads((backend / "fixtures" / "review_evaluations" / f"{case_id}.json").read_text())
    if case["case_id"] != case_id or case["fixture"] != f"{case_id}.pdf":
        raise ValueError("The evaluation case identity does not match its allowlist")
    if (not isinstance(case["case_version"], str) or not case["case_version"]
            or not re.fullmatch(r"[0-9a-f]{64}", case["source_sha256"])
            or type(case["page_count"]) is not int or case["page_count"] < 1):
        raise ValueError("The evaluation case has invalid source metadata")
    anchors = case["source_anchors"]
    if not anchors or not case["criteria"]:
        raise ValueError("The evaluation case needs source anchors and manual criteria")
    for anchor in anchors.values():
        if (type(anchor["page"]) is not int or not 1 <= anchor["page"] <= case["page_count"]
                or not isinstance(anchor["quote"], str) or not anchor["quote"].strip()):
            raise ValueError("The evaluation case has an invalid source anchor")
    ids = [criterion["id"] for criterion in case["criteria"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation criterion identifiers must be unique")
    for criterion in case["criteria"]:
        if (not criterion["expectation"] or not criterion["anchors"]
                or any(anchor not in anchors for anchor in criterion["anchors"])
                or criterion["importance"] not in {"priority", "supporting"}):
            raise ValueError("The evaluation case has an invalid manual criterion")
    return case


def validate_case_source(case: dict, extraction) -> None:
    """Check fixture provenance, not model truth or claim coverage.

    Authored sentence anchors preserve source wording. Whitespace is collapsed
    only here to accommodate PDF line wrapping in the offline reference corpus;
    this does not alter the production exact-span citation validator.
    """
    if extraction.content_sha256 != case["source_sha256"]:
        raise ValueError("The reviewed synthetic fixture changed")
    if extraction.page_count != case["page_count"] or extraction.status != "complete":
        raise ValueError("The reviewed synthetic fixture extraction changed")
    pages = {page.page_number: page for page in extraction.pages}
    for anchor in case["source_anchors"].values():
        page = pages.get(anchor["page"])
        quote = " ".join(anchor["quote"].split())
        if page is None or " ".join(page.text.split()).count(quote) != 1:
            raise ValueError("A reviewed synthetic source anchor is missing or ambiguous")
