"""Offline grouping checks; passage boundaries do not certify model quality."""

from pathlib import Path

import pytest

from clauseiq_types.source import SourceExtraction, SourcePage, SourceSpan
from services.ai.review_passages import (
    MAX_PASSAGE_CHARACTERS, MAX_PASSAGE_SPANS, MAX_SINGLE_SPAN_CHARACTERS,
    PASSAGE_VERSION, PassageConstructionError, build_review_passages,
)
from services.ai.text_extractor import TextExtractor, _line_spans


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs"


def source(*texts):
    pages = [SourcePage(page_number=index, text=text, status="extracted" if text.strip() else "empty",
                        spans=_line_spans(text, "a" * 64, index)) for index, text in enumerate(texts, 1)]
    return SourceExtraction(content_sha256="a" * 64, extraction_version="test-lines-v1",
                            status="complete" if all(text.strip() for text in texts) else "partial",
                            page_count=len(pages), pages=pages, text="\n".join(texts).strip())


def assert_preserved(extraction, passages):
    assert [span_id for passage in passages for span_id in passage.span_ids] == [
        span.id for page in extraction.pages for span in page.spans
    ]
    for passage in passages:
        page = extraction.pages[passage.page_number - 1]
        assert passage.text == page.text[passage.start:passage.end]
        assert passage.source_revision_id == "revision"
        assert len(passage.span_ids) <= MAX_PASSAGE_SPANS
        assert len(passage.text) <= MAX_PASSAGE_CHARACTERS or len(passage.span_ids) == 1
        assert len(passage.text) <= MAX_SINGLE_SPAN_CHARACTERS


@pytest.mark.parametrize("filename", ["managed-services-25p.pdf", "service-terms-conflict.pdf"])
def test_actual_fixtures_preserve_all_anchors_and_determinism_without_mutation(filename):
    extraction = TextExtractor._extract_pdf_source((FIXTURE_DIR / filename).read_bytes())
    before = extraction.model_dump_json()
    passages = build_review_passages(extraction, "revision")
    assert passages == build_review_passages(extraction, "revision")
    assert extraction.model_dump_json() == before
    assert len({passage.id for passage in passages}) == len(passages)
    assert PASSAGE_VERSION == "source-passages-v1"
    assert_preserved(extraction, passages)


def test_managed_services_transition_and_verification_are_complete_page_local_units():
    extraction = TextExtractor._extract_pdf_source((FIXTURE_DIR / "managed-services-25p.pdf").read_bytes())
    passages = build_review_passages(extraction, "revision")
    transition = next(passage for passage in passages if passage.text.startswith("73. "))
    verification = next(passage for passage in passages if passage.text.startswith("74. "))
    assert transition.page_number == verification.page_number == 25
    assert len(transition.span_ids) == 7
    assert "ten business days afterward" in transition.text
    assert "minimum additional arrangement needed for an effective transfer." in transition.text
    assert len(verification.span_ids) == 8
    assert "fifteen business days" in verification.text
    assert "relationship index" in verification.text
    assert "assistance charges remain payable" in verification.text
    assert "not separately chargeable" in verification.text
    assert verification.text.endswith("written instruction process.")
    assert not transition.continuation_before and not transition.continuation_after
    assert not verification.continuation_before and not verification.continuation_after


def test_two_page_conflict_keeps_each_deadline_with_its_qualification_and_table():
    extraction = TextExtractor._extract_pdf_source((FIXTURE_DIR / "service-terms-conflict.pdf").read_bytes())
    passages = build_review_passages(extraction, "revision")
    fees = next(passage for passage in passages if passage.text.startswith("2. Fees"))
    schedule = next(passage for passage in passages if passage.text.startswith("A2. "))
    delivery = next(passage for passage in passages if passage.text.startswith("A1. "))
    assert "within 30 days" in fees.text and "no priority rule" in fees.text
    assert "within 7 days" in schedule.text and "difference is intentional" in schedule.text
    assert fees.page_number == 1 and schedule.page_number == 2
    assert "Reviewed inventory" in delivery.text and "GBP 600" in delivery.text


def test_unnumbered_paragraphs_split_at_blank_lines_not_wrapped_lines():
    extraction = source("First paragraph begins\nand ends here.\n\nSecond paragraph includes\na qualification.")
    passages = build_review_passages(extraction, "revision")
    assert [passage.text for passage in passages] == [
        "First paragraph begins\nand ends here.", "Second paragraph includes\na qualification.",
    ]
    assert_preserved(extraction, passages)


@pytest.mark.parametrize("heading", ["1. Conditions", "3.2 Conditions", "A4. Conditions", "CONDITIONS", "Payment terms"])
def test_heading_stays_with_body_across_blank_separator(heading):
    extraction = source(heading + "\n\nThe following terms apply.\n\nA separate paragraph.")
    passages = build_review_passages(extraction, "revision")
    assert passages[0].text == heading + "\n\nThe following terms apply."
    assert passages[1].text == "A separate paragraph."


def test_bullets_tables_whitespace_and_unicode_are_not_normalized_or_removed():
    text = ("CONDITIONS\r\n  Café e\u0301 🙂 must retain these:\r\n"
            " • an original\r\n • all metadata\r\n\r\n"
            "Item\tCharge\r\nArchive\t€ 25\r\nPortal\t£ 40  ")
    extraction = source(text)
    passages = build_review_passages(extraction, "revision")
    assert len(passages) == 2
    assert "\r\n" in passages[0].text and "e\u0301 🙂" in passages[0].text
    assert passages[1].text.endswith("£ 40  ")
    assert_preserved(extraction, passages)


def test_bounded_fallback_prefers_sentence_boundary_and_marks_both_sides():
    first = "Opening " + "a" * 1_950 + "."
    second = "Next " + "b" * 1_000
    third = "continued " + "c" * 1_100 + "."
    extraction = source("\n".join((first, second, third)))
    passages = build_review_passages(extraction, "revision")
    assert [passage.text for passage in passages] == [first, second + "\n" + third]
    assert passages[0].continuation_after and passages[1].continuation_before
    assert not passages[0].continuation_before and not passages[1].continuation_after
    assert_preserved(extraction, passages)


def test_forced_mid_sentence_and_span_count_boundaries_are_explicit():
    extraction = source("\n".join("unfinished line" for _ in range(70)))
    passages = build_review_passages(extraction, "revision")
    assert [len(passage.span_ids) for passage in passages] == [32, 32, 6]
    assert [(passage.continuation_before, passage.continuation_after) for passage in passages] == [
        (False, True), (True, True), (True, False),
    ]
    assert_preserved(extraction, passages)


def test_pages_never_join_and_boundaries_remain_visible_across_empty_pages():
    extraction = source("Sentence that continues", "", "on another page.")
    passages = build_review_passages(extraction, "revision")
    assert [passage.page_number for passage in passages] == [1, 3]
    assert passages[0].continuation_after and passages[1].continuation_before
    assert not passages[0].continuation_before and not passages[1].continuation_after
    assert_preserved(extraction, passages)


def test_one_long_line_is_preserved_whole_and_not_joined_to_neighbours():
    extraction = source("Intro\n" + "x" * 5_000 + "\nEnding.")
    passages = build_review_passages(extraction, "revision")
    assert [len(passage.span_ids) for passage in passages] == [1, 1, 1]
    assert passages[1].text == "x" * 5_000
    assert passages[1].continuation_before and passages[1].continuation_after
    assert_preserved(extraction, passages)


def test_oversized_line_is_rejected_without_exposing_source_or_mutating_it():
    extraction = source("PRIVATE SOURCE " + "x" * MAX_SINGLE_SPAN_CHARACTERS)
    before = extraction.model_dump_json()
    with pytest.raises(PassageConstructionError, match="^A source line exceeds the supported passage size.$"):
        build_review_passages(extraction, "revision")
    assert extraction.model_dump_json() == before


@pytest.mark.parametrize("malformation", ["duplicate", "overlap", "missing", "trailing", "blank"])
def test_invalid_anchor_sequence_fails_closed(malformation):
    extraction = source("First\nSecond")
    page = extraction.pages[0]
    if malformation == "duplicate":
        page.spans[1].id = page.spans[0].id
    elif malformation == "overlap":
        page.spans.append(page.spans[-1])
    elif malformation == "missing":
        page.spans = page.spans[1:]
    elif malformation == "trailing":
        page.spans = page.spans[:1]
    else:
        page.text += "\n "
        page.spans.append(SourceSpan(id="blank", start=len(page.text) - 1, end=len(page.text), text=" "))
    with pytest.raises(PassageConstructionError):
        build_review_passages(extraction, "revision")


def test_ids_are_local_to_the_source_revision_not_new_storage_anchors():
    extraction = source("1. A term\nText.")
    first = build_review_passages(extraction, "revision")[0]
    second = build_review_passages(extraction, "another-revision")[0]
    assert first.id == second.id == "p1_b1_v1"
    assert first.span_ids == second.span_ids
    assert first.source_revision_id != second.source_revision_id
    with pytest.raises(PassageConstructionError):
        build_review_passages(extraction, " ")
