"""Fresh unpaid adversarial mechanics tests, not additional semantic evidence."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evaluations.library_search_cases import EvaluationCorpus
from evaluations.retrieval_comparison import DIMENSIONS, digest, passage_key, query_key
from evaluations.retrieval_embeddings import prepare, price, write_exclusive
from evaluations.retrieval_refinement import RefinedCandidates, replay_refinement
from services.ai.review_passages import ReviewPassage
from services.library_search import search_passages
from services.retrieval_policy import document_diverse, repeated_headers


def add(passages, text, *, doc="agreement", revision="revision-a", page=1, block=1, **kwargs):
    passage = ReviewPassage(
        id=f"p{page}_b{block}_v1", source_revision_id=revision, page_number=page,
        text=text, span_ids=(f"p{page}_line{block}",),
        start=(block - 1) * 500, end=(block - 1) * 500 + len(text), **kwargs,
    )
    identity = (doc, revision, page, passage.id)
    passages[identity] = passage
    return identity


def pages(header="Commercial services agreement\nFor discussion only\nOperating schedule", count=5):
    passages = {}
    for page in range(1, count + 1):
        add(passages, header, page=page)
        add(passages, "No additional fees are payable.", page=page, block=2)
    return passages


def test_repeated_headers_are_derived_metadata_not_source_edits():
    passages = pages()
    before = deepcopy(passages)
    excluded = repeated_headers(passages)
    assert len(excluded) == 5
    assert all(identity[3].endswith("b1_v1") for identity in excluded)
    assert passages == before
    assert len(passages) == 10  # Short clauses remain intact and eligible.


@pytest.mark.parametrize("clause", [
    "No refunds", "Customer must notify supplier", "Payment within five days",
    "Liability is capped", "The supplier may suspend services", "Written consent required",
    "No automatic renewal.", "Termination requires approval", "Fees £50",
    "The supplier shall not use records for training", "2. Service restrictions",
    "Only approved personnel", "The customer retains all rights",
])
def test_repeated_operative_or_ambiguous_blocks_stay_searchable(clause):
    assert not repeated_headers(pages("Commercial agreement\nFor discussion only\n" + clause))


def test_mixed_body_blocks_and_embedded_footers_are_not_removed():
    passages = pages("Commercial agreement\nFor discussion only\nSupplier must return the complete export.")
    for identity, passage in list(passages.items()):
        if identity[3].endswith("b2_v1"):
            passages[identity] = replace(passage, text=passage.text + "\nConfidential copy")
    assert not repeated_headers(passages)


@pytest.mark.parametrize("header", ["Running title", "Commercial agreement\nLegal notice.\nSchedule"])
def test_one_line_and_unrecognized_sentence_are_not_sufficient(header):
    assert not repeated_headers(pages(header))


def test_requires_three_pages_and_sixty_percent_of_observed_pages():
    assert not repeated_headers(pages(count=2))
    passages = pages(count=6)
    for page in (4, 5, 6):
        identity = next(key for key in passages if key[2] == page and key[3].endswith("b1_v1"))
        passages[identity] = replace(passages[identity], text=f"Different title {page}\nConfidential")
    assert not repeated_headers(passages)  # 3/6 is below 60%.


def test_revision_and_document_boundaries_do_not_share_repeat_counts():
    combined = {}
    for doc, revision in (("one", "r1"), ("one", "r2"), ("two", "r1")):
        for identity, passage in pages(count=2).items():
            passage = replace(passage, source_revision_id=revision)
            combined[(doc, revision, identity[2], identity[3])] = passage
    assert not repeated_headers(combined)


def test_one_block_pages_and_continued_headers_remain_eligible():
    passages = pages()
    assert not repeated_headers({key: value for key, value in passages.items() if key[3].endswith("b1_v1")})
    continued = {key: replace(value, continuation_after=True) for key, value in passages.items()}
    assert not repeated_headers(continued)


def test_physical_page_boundary_flag_does_not_hide_repeated_headers():
    passages = {key: replace(value, continuation_before=(key[2] > 1))
                for key, value in pages().items()}
    assert len(repeated_headers(passages)) == 5


def test_header_in_middle_of_page_is_not_furniture():
    passages = pages()
    for page in range(1, 6):
        add(passages, "Ordinary page introduction.", page=page, block=0)
    assert not repeated_headers(passages)


def test_source_identity_mismatch_fails_closed():
    passages = pages()
    first = next(iter(passages))
    passages[first] = replace(passages[first], source_revision_id="other")
    with pytest.raises(ValueError, match="identity"):
        repeated_headers(passages)


def test_diversity_is_deterministic_preserves_identity_and_refills():
    a, b, c, d = ("a", "r", 1, "1"), ("a", "r", 1, "2"), ("b", "r", 2, "1"), ("c", "r", 3, "1")
    assert document_diverse([a, b, a, c, d], 3) == [a, c, d]
    assert document_diverse([a, b, a, c, d], 5) == [a, c, d, b]
    assert document_diverse([a, b], 2) == [a, b]
    assert document_diverse([], 5) == []
    with pytest.raises(ValueError):
        document_diverse([a], 0)


def unit_vector(index=0):
    return [float(i == index) for i in range(DIMENSIONS)]


def test_dense_filter_refills_window_before_fusion_and_keeps_exact_text():
    passages = pages(count=25)
    query = "additional fees"
    corpus = EvaluationCorpus(
        dataset=SimpleNamespace(cases=[SimpleNamespace(query=query)]), dataset_sha256="test",
        documents=[{"id": "agreement", "filename": "agreement.pdf"}], passages=passages,
    )
    vectors = {passage_key(key): unit_vector(0 if key[3].endswith("b1_v1") else 1) for key in passages}
    vectors[query_key(query)] = unit_vector(0)
    candidates = RefinedCandidates(corpus, vectors)
    assert len(candidates.dense(query)) == 20
    assert all(key[3].endswith("b2_v1") for key in candidates.dense(query))
    result = candidates.search_variant(corpus.documents, query, limit=5, variant="filtered_hybrid")
    assert len(result["results"]) == 5
    assert all(row["excerpt"] == "No additional fees are payable." for row in result["results"])
    assert result["coverage"]["excluded_header_passages"] == 25


@pytest.fixture(scope="module")
def prepared():
    with patch("socket.socket.connect", side_effect=AssertionError("No network")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("No provider")):
        return asyncio.run(prepare())


@pytest.fixture(scope="module")
def vectors(prepared):
    return {key: unit_vector() for key in prepared.inputs}


def test_label_free_policy_preserves_all_reviewed_source_anchors(prepared):
    for corpus in prepared.corpora.values():
        excluded = repeated_headers(corpus.passages)
        assert len(excluded) == 42  # Only the three longer documents qualify.
        assert not set(excluded) & {anchor.identity() for anchor in corpus.dataset.anchors.values()}


def test_unfiltered_lexical_ranking_matches_frozen_baseline(prepared, vectors):
    corpus = prepared.corpora["development"]
    with patch("evaluations.retrieval_refinement.repeated_headers", return_value={}):
        candidates = RefinedCandidates(corpus, vectors)
    for case in corpus.dataset.cases:
        expected = search_passages(corpus.documents, case.query, limit=20).results
        assert candidates.lexical(case.query) == [
            (hit.document_id, hit.source_revision_id, hit.page_number, hit.passage_id) for hit in expected
        ]


def test_retrieval_does_not_read_anchor_labels_or_case_categories(prepared, vectors):
    corpus = prepared.corpora["development"]
    poisoned = replace(corpus, dataset=SimpleNamespace(cases=[SimpleNamespace(query=case.query)
                                                            for case in corpus.dataset.cases]))
    normal, independent = RefinedCandidates(corpus, vectors), RefinedCandidates(poisoned, vectors)
    for case in corpus.dataset.cases:
        assert normal.ranking(case.query, "filtered_hybrid") == independent.ranking(case.query, "filtered_hybrid")


def save_fake_cache(prepared, vectors, directory):
    requests = [{"batch": i, "input_keys": keys, "kind": prepared.inputs[keys[0]].kind,
                 "provider_input_tokens": len(keys), "usage_based_usd": price(len(keys)), "latency_ms": 1}
                for i, keys in enumerate(prepared.batches)]
    cache = {"plan_sha256": prepared.plan_sha256, "vectors": vectors, "requests": requests}
    write_exclusive(directory / "plan.json", {"manifest": prepared.manifest})
    write_exclusive(directory / "cache.json", {"sha256": digest(cache), "payload": cache})
    (directory / "ledger.jsonl").write_text(json.dumps({"event": "completed"}) + "\n")


def test_offline_replay_keeps_original_cache_and_separate_consumer_provenance(prepared, vectors, tmp_path):
    save_fake_cache(prepared, vectors, tmp_path)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    with patch("socket.socket.connect", side_effect=AssertionError("No network")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("No provider")), \
         patch("services.workspace_service.WorkspaceService.get_api_key", side_effect=AssertionError("No key")):
        report = replay_refinement(prepared, tmp_path)
    assert report["consumer"]["producer_plan_sha256"] == prepared.plan_sha256
    assert report["consumer_sha256"] == digest(report["consumer"])
    assert report["new_provider_calls"] == 0 and report["new_usage_based_usd"] == "0"
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before
    for result in report["results"].values():
        assert len(result["candidates"]) == 4
        for candidate in result["candidates"].values():
            assert candidate["overall"]["invalid_hits"] == 0


def test_replay_rejects_changed_producer_before_ranking(prepared, vectors, tmp_path):
    save_fake_cache(prepared, vectors, tmp_path)
    manifest = deepcopy(prepared.manifest)
    manifest["code_sha256"]["services/library_search.py"] = "changed"
    with patch("evaluations.retrieval_refinement.compare_refinement", side_effect=AssertionError("Do not rank")):
        with pytest.raises(ValueError, match="obsolete"):
            replay_refinement(replace(prepared, manifest=manifest), tmp_path)


def test_replay_output_restriction_and_exclusive_write(tmp_path):
    from evaluations.retrieval_refinement import main

    report = {"consumer_sha256": "test", "new_provider_calls": 0}
    with patch("evaluations.retrieval_refinement.prepare", return_value=SimpleNamespace(plan_sha256="test")), \
         patch("evaluations.retrieval_refinement.replay_refinement", return_value=report):
        with pytest.raises(ValueError, match="private"):
            asyncio.run(main(Path("public-report.json")))
        with patch("evaluations.retrieval_refinement.OUTPUT_ROOT", tmp_path):
            asyncio.run(main(tmp_path / "report.json"))
            with pytest.raises(FileExistsError):
                asyncio.run(main(tmp_path / "report.json"))
