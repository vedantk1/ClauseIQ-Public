"""Offline invariants for the public, source-backed synthetic PDF corpus."""
import importlib.util
import io
from pathlib import Path

import pdfplumber
import pytest

from services.ai.text_extractor import TextExtractor


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs"
SPEC = importlib.util.spec_from_file_location("synthetic_pdf_generator", FIXTURE_DIR / "generate.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
MANIFEST = GENERATOR.load_manifest()
FIXTURES = MANIFEST["fixtures"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["filename"])
def test_pdf_is_reproducible_and_has_no_author(fixture):
    content = (FIXTURE_DIR / fixture["filename"]).read_bytes()
    assert content == GENERATOR.render_fixture(fixture, MANIFEST["notice"])
    assert content == GENERATOR.render_fixture(fixture, MANIFEST["notice"])
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        assert len(pdf.pages) == len(fixture["pages"])
        assert pdf.metadata.get("Author", "") == ""
        assert pdf.metadata["Title"] == fixture["title"]
        assert pdf.metadata["Creator"] == "ClauseIQ synthetic fixture generator"
        assert str(FIXTURE_DIR) not in str(pdf.metadata)
        for page, expected in zip(pdf.pages, fixture["pages"]):
            text = " ".join((page.extract_text() or "").split())
            if fixture["kind"] == "image_only":
                assert text == ""
                assert page.images
            else:
                assert "SYNTHETIC TEST FIXTURE" in text
                for anchor in expected["text_anchors"]:
                    assert anchor in text


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["filename"])
async def test_fixture_through_application_text_extractor(fixture):
    content = (FIXTURE_DIR / fixture["filename"]).read_bytes()
    extractor = TextExtractor()
    if fixture["kind"] == "image_only":
        with pytest.raises(ValueError, match="^No text could be extracted from PDF$"):
            await extractor.extract_text(content, fixture["filename"])
        return
    text = " ".join((await extractor.extract_text(content, fixture["filename"])).split())
    for page in fixture["pages"]:
        for anchor in page["text_anchors"]:
            assert anchor in text


def test_manifest_lists_the_entire_pdf_corpus():
    expected = {fixture["filename"] for fixture in FIXTURES}
    assert len(expected) == len(FIXTURES) == 4
    assert expected == {path.name for path in FIXTURE_DIR.glob("*.pdf")}
    assert {fixture["kind"] for fixture in FIXTURES} == {"text", "image_only"}
