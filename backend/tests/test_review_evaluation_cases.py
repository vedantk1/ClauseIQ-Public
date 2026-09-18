"""Offline reference-corpus checks, not a semantic grader for provider output."""

import hashlib
import json
from pathlib import Path

import pytest

from clauseiq_types.review import ReviewBrief
from services.ai.text_extractor import TextExtractor
from tests.review_evaluation_cases import CASE_IDS, load_case, validate_case_source


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", CASE_IDS)
async def test_case_hash_and_each_anchor_match_authored_source_and_physical_pdf_page(case_id):
    case = load_case(BACKEND, case_id)
    pdf_path = ROOT / "tests" / "fixtures" / "pdfs" / case["fixture"]
    pdf = pdf_path.read_bytes()
    assert hashlib.sha256(pdf).hexdigest() == case["source_sha256"]
    extraction = await TextExtractor().extract_source(pdf, pdf_path.name)
    validate_case_source(case, extraction)
    ReviewBrief.model_validate(case["context"])

    authored = json.loads((ROOT / case["authored_source"]).read_text())
    if "fixtures" in authored:
        authored = next(fixture for fixture in authored["fixtures"] if fixture["filename"] == case["fixture"])
    assert len(authored["pages"]) == case["page_count"]
    for anchor in case["source_anchors"].values():
        page = authored["pages"][anchor["page"] - 1]
        paragraphs = [section["text"] for key in ("sections", "after_table") for section in page.get(key, [])]
        paragraphs.extend(" ".join(row) for row in page.get("table", []))
        assert sum(anchor["quote"] in paragraph for paragraph in paragraphs) == 1, anchor
    used = {anchor for criterion in case["criteria"] for anchor in criterion["anchors"]}
    assert used == set(case["source_anchors"]), "Do not retain unrelated reference anchors"
    for criterion in case["criteria"]:
        assert criterion["must_not_claim"]


@pytest.mark.parametrize("case_id", ["unknown", "../managed-services-25p", "service-terms-conflict.pdf"])
def test_case_allowlist_does_not_accept_paths_or_unreviewed_sources(case_id):
    with pytest.raises(ValueError, match="allowlisted"):
        load_case(BACKEND, case_id)


@pytest.mark.asyncio
async def test_source_anchor_drift_fails_even_with_matching_hash():
    case = load_case(BACKEND, CASE_IDS[1])
    pdf = ROOT / "tests" / "fixtures" / "pdfs" / case["fixture"]
    extraction = await TextExtractor().extract_source(pdf.read_bytes(), pdf.name)
    case["source_anchors"]["payment_master"]["page"] = 2
    with pytest.raises(ValueError, match="anchor"):
        validate_case_source(case, extraction)
