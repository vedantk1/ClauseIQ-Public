"""Offline invariants for the public, source-backed synthetic PDF corpus."""
import importlib.util
import io
import json
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
LONG_FIXTURES = [fixture for fixture in FIXTURES if "expected_page_count" in fixture]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["filename"])
def test_pdf_is_reproducible_and_has_no_author(fixture):
    content = (FIXTURE_DIR / fixture["filename"]).read_bytes()
    assert content == GENERATOR.render_fixture(fixture, MANIFEST["notice"])
    assert content == GENERATOR.render_fixture(fixture, MANIFEST["notice"])
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        assert len(pdf.pages) == len(fixture["pages"])
        assert len(pdf.pages) == fixture.get("expected_page_count", len(fixture["pages"]))
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
                # Catch clipped titles or table cells without an application UI run.
                assert all(0 <= char["x0"] < char["x1"] <= page.width
                           and 0 <= char["top"] < char["bottom"] <= page.height
                           for char in page.chars)


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
    assert len(expected) == len(FIXTURES)
    assert expected == {path.name for path in FIXTURE_DIR.glob("*.pdf")}
    assert {fixture["kind"] for fixture in FIXTURES} == {"text", "image_only"}
    assert {len(fixture["pages"]) for fixture in FIXTURES} == {1, 2, 5, 12, 25}
    assert set(MANIFEST["fixture_sources"]) == {
        path.name for path in (FIXTURE_DIR / "sources").glob("*.json")
    }


@pytest.mark.parametrize("fixture", LONG_FIXTURES, ids=lambda fixture: fixture["filename"])
def test_long_fixtures_have_substance_and_distant_cross_references(fixture):
    """Length coverage must include distinct content, not repeated/mostly blank pages."""
    assert fixture["min_body_words_per_page"] >= 220
    paragraphs = []
    for page in fixture["pages"]:
        page_paragraphs = [section["text"] for section in
                           page["sections"] + page.get("after_table", [])]
        # Exclude title, footer, notice and table headers from the density floor.
        assert sum(len(text.split()) for text in page_paragraphs) >= fixture["min_body_words_per_page"]
        paragraphs.extend(" ".join(text.split()) for text in page_paragraphs)
    assert len(paragraphs) == len(set(paragraphs)), "Do not pad pages with repeated paragraphs"
    assert len(fixture["cross_references"]) >= 2
    with pdfplumber.open(FIXTURE_DIR / fixture["filename"]) as pdf:
        texts = [" ".join(page.extract_text().split()) for page in pdf.pages]
    for reference in fixture["cross_references"]:
        source, target = reference["from_page"], reference["to_page"]
        assert 1 <= source <= len(texts) and 1 <= target <= len(texts)
        assert abs(source - target) >= 2
        assert reference["source_anchor"] in texts[source - 1]
        assert reference["target_anchor"] in texts[target - 1]


@pytest.mark.parametrize("source", ["../outside.json", "nested/source.json", "source.txt"])
def test_source_index_rejects_paths_outside_flat_json_sources(tmp_path, monkeypatch, source):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"fixtures": [], "fixture_sources": [source]}), encoding="utf-8"
    )
    monkeypatch.setattr(GENERATOR, "FIXTURE_DIR", tmp_path)
    with pytest.raises(ValueError, match="Fixture source must be a JSON filename"):
        GENERATOR.load_manifest()


def test_source_index_rejects_duplicate_pdf_outputs(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"fixtures": [{"filename": "same.pdf"}, {"filename": "same.pdf"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(GENERATOR, "FIXTURE_DIR", tmp_path)
    with pytest.raises(ValueError, match="Fixture output filenames must be unique"):
        GENERATOR.load_manifest()
