"""Offline source anchors and safe extraction failures for reviewed PDF fixtures."""

import hashlib
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pdfplumber
import pytest
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pydantic import ValidationError

from clauseiq_types.source import SourceExtraction, SourcePage, SourceSpan
from services.ai import text_extractor
from services.ai.text_extractor import EXTRACTION_VERSION, TextExtractor


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text())
TEXT_FIXTURES = [fixture for fixture in MANIFEST["fixtures"] if fixture["kind"] == "text"]
TEXT_FIXTURES += [
    json.loads((FIXTURE_DIR / "sources" / filename).read_text())
    for filename in MANIFEST["fixture_sources"]
]


def mock_pdf(monkeypatch, page_results):
    """Supply extraction outputs, without creating or modifying PDF artifacts."""
    pages = [SimpleNamespace(extract_text=Mock(
        side_effect=result if isinstance(result, Exception) else None,
        return_value=None if isinstance(result, Exception) else result,
    )) for result in page_results]

    class FakePDF:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    pdf = FakePDF()
    pdf.pages = pages
    opened = Mock(return_value=pdf)
    monkeypatch.setattr(text_extractor.pdfplumber, "open", opened)
    return opened


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", TEXT_FIXTURES, ids=lambda fixture: fixture["filename"])
async def test_real_source_pages_anchors_and_determinism(fixture):
    content = (FIXTURE_DIR / fixture["filename"]).read_bytes()
    extractor = TextExtractor()
    result = await extractor.extract_source(content, fixture["filename"])
    repeated = await extractor.extract_source(content, fixture["filename"])

    assert result == repeated
    assert result.content_sha256 == hashlib.sha256(content).hexdigest()
    assert result.extraction_version == f"pdfplumber:{pdfplumber.__version__}:page-lines-v1"
    assert result.status == "complete"
    assert result.page_count == len(fixture["pages"])
    assert result.warnings == []
    assert [page.page_number for page in result.pages] == list(range(1, result.page_count + 1))
    assert SourceExtraction.model_validate_json(result.model_dump_json()) == result

    with pdfplumber.open(io.BytesIO(content)) as original:
        expected_texts = [page.extract_text() for page in original.pages]
    assert [page.text for page in result.pages] == expected_texts
    assert result.text == "\n".join(text for text in expected_texts if text).strip()
    assert await extractor.extract_text(content, fixture["filename"]) == result.text

    span_ids = []
    for page, expected in zip(result.pages, fixture["pages"]):
        assert page.status == "extracted"
        assert page.warnings == []
        assert page.spans
        normalized_text = " ".join(page.text.split())
        for anchor in expected["text_anchors"]:
            assert anchor in normalized_text
        previous_end = 0
        for span in page.spans:
            assert 0 <= span.start < span.end <= len(page.text)
            assert span.start >= previous_end
            assert page.text[span.start:span.end] == span.text
            previous_end = span.end
            span_ids.append(span.id)
    assert len(span_ids) == len(set(span_ids))


@pytest.mark.asyncio
async def test_image_only_source_is_unavailable_but_original_api_still_rejects_it():
    filename = "image-only-scan.pdf"
    content = (FIXTURE_DIR / filename).read_bytes()
    extractor = TextExtractor()
    result = await extractor.extract_source(content, filename)
    assert result.status == "unavailable"
    assert result.page_count == 1
    assert result.text == ""
    assert result.warnings == ["no_extractable_text"]
    assert result.pages[0].model_dump() == {
        "page_number": 1, "text": "", "status": "empty", "spans": [],
        "warnings": ["no_extractable_text"],
    }
    with pytest.raises(ValueError, match="^No text could be extracted from PDF$"):
        await extractor.extract_text(content, filename)


@pytest.mark.asyncio
async def test_page_failure_keeps_original_numbering_and_other_text(monkeypatch):
    mock_pdf(monkeypatch, [
        "First page", RuntimeError("PRIVATE SOURCE FRAGMENT"), None, "Last page",
    ])
    source = await TextExtractor().extract_source(b"synthetic bytes", "fixture.pdf")
    assert source.status == "partial"
    assert source.page_count == 4
    assert [page.page_number for page in source.pages] == [1, 2, 3, 4]
    assert [page.status for page in source.pages] == ["extracted", "failed", "empty", "extracted"]
    assert source.pages[1].text == ""
    assert source.pages[1].spans == []
    assert source.pages[1].warnings == ["page_extraction_failed"]
    assert source.warnings == ["page_extraction_failed", "no_extractable_text"]
    assert source.text == "First page\nLast page"
    assert "PRIVATE SOURCE FRAGMENT" not in source.model_dump_json()


@pytest.mark.asyncio
async def test_legacy_text_only_call_does_not_hide_failed_pages(monkeypatch):
    mock_pdf(monkeypatch, ["First page", RuntimeError("PRIVATE SOURCE FRAGMENT")])
    with pytest.raises(ValueError, match="^Could not extract text from all PDF pages$"):
        await TextExtractor().extract_text(b"synthetic bytes", "fixture.pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("page_results", [[], [None], [RuntimeError("PRIVATE SOURCE FRAGMENT")]])
async def test_no_successful_pages_report_unavailable(monkeypatch, page_results):
    mock_pdf(monkeypatch, page_results)
    source = await TextExtractor().extract_source(b"synthetic bytes", "fixture.pdf")
    assert source.status == "unavailable"
    assert source.page_count == len(page_results)
    assert source.text == ""
    assert "no_extractable_text" in source.warnings
    assert "PRIVATE SOURCE FRAGMENT" not in source.model_dump_json()


@pytest.mark.asyncio
async def test_exact_whitespace_and_unicode_offsets_remain_page_relative(monkeypatch):
    original_text = "  Payment café 🙂\r\n\n  Next line  \n"
    opened = mock_pdf(monkeypatch, [original_text, " \n", "Final"])
    source = await TextExtractor().extract_source(b"synthetic bytes", "fixture.PDF")
    assert isinstance(opened.call_args.args[0], io.BytesIO)
    assert source.status == "partial"
    assert source.pages[0].text == original_text
    assert source.pages[1].text == " \n"
    assert source.pages[1].status == "empty"
    assert source.pages[1].spans == []
    spans = source.pages[0].spans
    assert len(spans) == 2
    assert (spans[0].start, spans[0].end, spans[0].text) == (0, 16, "  Payment café 🙂")
    assert spans[1].start == original_text.index("  Next line")
    assert spans[1].text == "  Next line  "
    assert source.text == (original_text + "\n \n\nFinal").strip()


@pytest.mark.asyncio
async def test_span_identity_changes_with_file_version_page_and_offsets(monkeypatch):
    mock_pdf(monkeypatch, ["Same line\nSame line", "Same line"])
    extractor = TextExtractor()
    first = await extractor.extract_source(b"first synthetic file", "fixture.pdf")
    same_bytes_other_name = await extractor.extract_source(b"first synthetic file", "renamed.pdf")
    other_file = await extractor.extract_source(b"second synthetic file", "fixture.pdf")
    assert first == same_bytes_other_name
    ids = [span.id for page in first.pages for span in page.spans]
    assert len(ids) == len(set(ids)) == 3
    assert first.pages[0].spans[0].id != other_file.pages[0].spans[0].id
    monkeypatch.setattr(text_extractor, "EXTRACTION_VERSION", EXTRACTION_VERSION + ":test-version")
    other_version = await extractor.extract_source(b"first synthetic file", "fixture.pdf")
    assert first.pages[0].spans[0].id != other_version.pages[0].spans[0].id


@pytest.mark.asyncio
async def test_pdf_work_runs_off_the_event_loop(monkeypatch):
    opened = mock_pdf(monkeypatch, ["Source text"])
    event_thread = threading.get_ident()
    extraction_threads = []
    pdf = opened.return_value

    def check_thread(stream):
        assert isinstance(stream, io.BytesIO)
        extraction_threads.append(threading.get_ident())
        return pdf

    opened.side_effect = check_thread
    await TextExtractor().extract_source(b"synthetic bytes", "fixture.pdf")
    assert extraction_threads and extraction_threads[0] != event_thread


@pytest.mark.asyncio
async def test_malformed_pdf_failure_is_safe():
    with pytest.raises(ValueError, match="^Could not read PDF$"):
        await TextExtractor().extract_source(b"not a PDF: PRIVATE SOURCE FRAGMENT", "fixture.pdf")


@pytest.mark.asyncio
async def test_encrypted_pdf_failure_is_safe(monkeypatch):
    monkeypatch.setattr(text_extractor.pdfplumber, "open", Mock(
        side_effect=PDFPasswordIncorrect("PRIVATE SOURCE FRAGMENT"),
    ))
    with pytest.raises(ValueError, match="^Could not read PDF$"):
        await TextExtractor().extract_source(b"synthetic bytes", "fixture.pdf")


@pytest.mark.asyncio
async def test_unsupported_type_keeps_existing_error():
    with pytest.raises(ValueError, match="^Unsupported file format$"):
        await TextExtractor().extract_text(b"source text", "fixture.txt")


def test_source_models_reject_invalid_anchor_offsets_and_page_inventory():
    with pytest.raises(ValidationError, match="offsets must match"):
        SourceSpan(id="test", start=1, end=2, text="longer")
    with pytest.raises(ValidationError, match="must match its page"):
        SourcePage(page_number=1, text="test", status="extracted", spans=[
            SourceSpan(id="test", start=0, end=4, text="nope"),
        ])
    with pytest.raises(ValidationError, match="page count must match"):
        SourceExtraction(content_sha256="a" * 64, extraction_version="v1", status="complete",
                         page_count=2, pages=[], text="")
    with pytest.raises(ValidationError, match="retain original page order"):
        SourceExtraction(content_sha256="a" * 64, extraction_version="v1", status="unavailable",
                         page_count=1, pages=[SourcePage(page_number=2, text="", status="empty")],
                         text="")


def test_real_fixture_cases_cover_short_and_long_documents():
    assert {len(fixture["pages"]) for fixture in TEXT_FIXTURES} == {1, 2, 5, 12, 25}
