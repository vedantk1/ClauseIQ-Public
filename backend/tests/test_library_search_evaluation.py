"""No paid AI: frozen-source retrieval scoring, not generated-answer grading."""

import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from evaluations.library_search_cases import DATASET_PATH, RetrievalDataset, load_dataset, prepare_corpus, validate_anchors
from evaluations.library_search_evaluation import evaluate_search, score_case, summarize


@pytest.fixture(scope="module")
def corpus():
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in retrieval evaluation")), \
         patch("openai.OpenAI", side_effect=AssertionError("Provider forbidden")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("Provider forbidden")):
        return asyncio.run(prepare_corpus())


def hit_for(corpus, anchor_name):
    anchor = corpus.dataset.anchors[anchor_name]
    passage = corpus.passages[anchor.identity()]
    return {"document_id": anchor.document_id, "source_revision_id": anchor.source_revision_id,
            "page_number": anchor.page_number, "passage_id": anchor.passage_id,
            "excerpt": passage.text[:80]}


def test_frozen_cases_cover_requested_categories_and_preserve_unavailable_source(corpus):
    assert corpus.dataset_sha256 == hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert len(corpus.documents) == 7
    assert Counter(case.category for case in corpus.dataset.cases) == {
        "exact_term": 5, "paraphrase": 5, "multi_document": 5,
        "exception_near_match": 5, "unanswerable": 4,
    }
    scan = next(document for document in corpus.documents if document["id"] == "image-only-scan")
    assert scan["extraction_status"] == "unavailable"
    assert not any(identity[0] == "image-only-scan" for identity in corpus.passages)
    assert all(anchor.identity() in corpus.passages for anchor in corpus.dataset.anchors.values())


def test_label_quotes_match_authored_sources_as_well_as_the_physical_pdf(corpus):
    fixture_root = DATASET_PATH.parents[3] / "tests/fixtures/pdfs"
    manifest = json.loads((fixture_root / "manifest.json").read_text())
    for anchor in corpus.dataset.anchors.values():
        filename = anchor.document_id + ".pdf"
        authored = next((item for item in manifest["fixtures"] if item["filename"] == filename), None)
        if authored is None:
            authored = json.loads((fixture_root / "sources" / (anchor.document_id + ".json")).read_text())
        page = authored["pages"][anchor.page_number - 1]
        paragraphs = [item["text"] for field in ("sections", "after_table") for item in page.get(field, [])]
        assert sum(anchor.quote in paragraph for paragraph in paragraphs) == 1


def test_dataset_hash_drift_is_rejected_without_silently_relabelling(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_bytes(DATASET_PATH.read_bytes() + b"\n")
    path.with_suffix(".sha256").write_text(DATASET_PATH.with_suffix(".sha256").read_text())
    with pytest.raises(ValueError, match="hash changed"):
        load_dataset(path)


@pytest.mark.parametrize("mutation", [
    lambda data: data["documents"][0].update(filename="../../private.pdf"),
    lambda data: data["anchors"]["nda_return"].update(source_revision_id="other-revision"),
    lambda data: data["anchors"]["nda_return"].update(page_number=2),
    lambda data: data["cases"][0].update(anchors=["missing"]),
    lambda data: data["cases"][0].update(anchors=[]),
    lambda data: data["cases"][-1].update(anchors=["nda_return"]),
    lambda data: data["cases"][10].update(anchors=["nda_return"]),
])
def test_malformed_dataset_identity_and_relevance_contract_fails(corpus, mutation):
    data = corpus.dataset.model_dump()
    mutation(data)
    with pytest.raises(ValidationError):
        RetrievalDataset.model_validate(data)


@pytest.mark.parametrize("mutation", [
    {"passage_id": "p1_b2_v1"}, {"quote": "A fabricated retention duty."},
])
def test_anchor_text_and_passage_drift_fail_against_exact_source(corpus, mutation):
    dataset = corpus.dataset.model_copy(deep=True)
    dataset.anchors["nda_return"] = dataset.anchors["nda_return"].model_copy(update=mutation)
    with pytest.raises(ValueError, match="anchor"):
        validate_anchors(dataset, corpus.passages)


def test_document_and_passage_metrics_are_separate_and_duplicates_do_not_inflate_recall(corpus):
    case = next(case for case in corpus.dataset.cases if case.id == "exception-01")
    hit = hit_for(corpus, "service_payment")
    result = score_case(corpus, case, [hit, deepcopy(hit)], 5)
    assert result["document_recall_at_k"] == 1
    assert result["document_precision_at_k"] == 1
    assert result["passage_recall_at_k"] == 0.5
    assert result["passage_precision_at_k"] == 0.2
    assert result["duplicate_hits"] == 1
    assert len(result["missing_relevant_passages"]) == 1


def test_scoring_cannot_match_bare_passage_ids_across_documents_or_revisions(corpus):
    case = next(case for case in corpus.dataset.cases if case.id == "exact-05")
    other_document = hit_for(corpus, "service_liability")
    assert other_document["passage_id"] == corpus.dataset.anchors["nda_return"].passage_id
    wrong_revision = {**hit_for(corpus, "nda_return"), "source_revision_id": "old-revision"}
    result = score_case(corpus, case, [other_document, wrong_revision], 5)
    assert result["document_recall_at_k"] == 0
    assert result["passage_recall_at_k"] == 0
    assert result["invalid_hits"] == 1


def test_fabricated_excerpt_or_page_receives_no_source_credit(corpus):
    case = corpus.dataset.cases[0]
    hit = hit_for(corpus, case.anchors[0])
    result = score_case(corpus, case, [{**hit, "excerpt": "Invented exact quote"}, {**hit, "page_number": 1}], 5)
    assert result["invalid_hits"] == 2
    assert result["document_recall_at_k"] == result["passage_recall_at_k"] == 0


def test_unanswerable_cases_are_reported_separately_not_counted_as_perfect_recall(corpus):
    case = corpus.dataset.cases[-1]
    empty = score_case(corpus, case, [], 5)
    noisy = score_case(corpus, case, [hit_for(corpus, "nda_return")], 5)
    assert empty["passage_recall_at_k"] is None and noisy["document_precision_at_k"] is None
    assert empty["unanswerable_nonempty"] is False and noisy["unanswerable_nonempty"] is True
    aggregate = summarize([{**empty, "latency_ms": 1.0}, {**noisy, "latency_ms": 3.0}])
    assert aggregate["unanswerable_nonempty_rate"] == 0.5
    assert aggregate["macro_passage_recall_at_k"] is None
    assert aggregate["latency_ms"]["p50"] == 1.0 and aggregate["latency_ms"]["p95"] == 3.0


def test_harness_sends_only_queries_and_corpus_to_search_and_retains_failures(corpus):
    calls = []
    def empty_search(documents, query, *, limit):
        calls.append((documents, query, limit))
        assert all("anchors" not in document and "rationale" not in document for document in documents)
        return {"results": [], "coverage": {"synthetic_test": True}}
    report = evaluate_search(corpus, empty_search, 5)
    assert len(calls) == 24 and report["dataset"]["questions"] == 24
    assert report["overall"]["macro_passage_recall_at_k"] == 0
    assert report["overall"]["unanswerable_nonempty_rate"] == 0
    assert report["cases"][0]["missing_relevant_passages"]
    assert report["cases"][0]["coverage"] == {"synthetic_test": True}
    assert all(row["latency_ms"] >= 0 for row in report["cases"])


def test_actual_lexical_baseline_remains_unpaid_and_source_bound(corpus):
    from services.library_search import search_passages

    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("openai.OpenAI", side_effect=AssertionError("Provider forbidden")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("Provider forbidden")):
        report = evaluate_search(corpus, search_passages, 5)
    assert report["overall"]["invalid_hits"] == 0
    assert report["overall"]["cases"] == 24
    assert report["overall"]["unanswerable_cases"] == 4
    assert report["cases"][0]["coverage"] is not None
    # A functioning harness must report weaknesses, not assert a post-hoc
    # semantic pass threshold or silently drop difficult/unanswerable cases.
    assert len(report["by_category"]) == 5
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("limit", [0, 21, True, 2.5])
def test_invalid_k_never_calls_search(corpus, limit):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid limit must fail before search")
    with pytest.raises(ValueError, match="limit"):
        evaluate_search(corpus, forbidden, limit)
