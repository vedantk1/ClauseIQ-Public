"""Unpaid source, ranking, provider-boundary and cost-accounting regressions.

Fake vectors verify mechanics, never provide a dense/hybrid quality result.
"""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evaluations.library_search_cases import DATASET_PATH
from evaluations.retrieval_comparison import (
    CachedCandidates, DIMENSIONS, MODEL, RRF_CONSTANT, compare, digest,
    fuse_rankings, normalize_vector, passage_key, query_key,
)
from evaluations.retrieval_embeddings import (
    ENDPOINT, MAX_INPUT_TOKENS, approve_plan, collect, load_cache, main,
    prepare, price, replay, validate_response,
)


@pytest.fixture(autouse=True)
def fixed_pricing_review_date():
    # Live commands expire old price approvals; deterministic tests do not.
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 26)
    with patch("evaluations.retrieval_embeddings.date", ReviewDate):
        yield


@pytest.fixture(scope="module")
def prepared():
    # CI's existing tokenizer preflight supplies the public vocabulary.
    # No settings/database/client import is needed to prepare either split.
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("openai.OpenAI", side_effect=AssertionError("Provider forbidden")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("Provider forbidden")):
        return asyncio.run(prepare())


def vector(index=0):
    return [1.0 if i == index else 0.0 for i in range(DIMENSIONS)]


def response(count=1):
    return SimpleNamespace(model=MODEL, usage=SimpleNamespace(prompt_tokens=count, total_tokens=count),
                           data=[SimpleNamespace(index=i, embedding=vector()) for i in reversed(range(count))])


def small_plan(prepared):
    keys = list(prepared.inputs)[:2]
    return replace(prepared, inputs={key: prepared.inputs[key] for key in keys}, batches=[[key] for key in keys])


def fake_factory(calls, failure=None, policy_change=None):
    class Embeddings:
        async def create(self, **payload):
            calls.append(payload)
            if failure:
                raise failure
            return response(len(payload["input"]))

    @asynccontextmanager
    async def factory():
        client = SimpleNamespace(base_url=ENDPOINT, max_retries=0, embeddings=Embeddings())
        if policy_change:
            setattr(client, *policy_change)
        yield client
    return factory


def test_frozen_new_question_families_and_authored_pdf_labels(prepared):
    development, holdout = prepared.corpora.values()
    assert len(development.dataset.cases) == 24 and len(holdout.dataset.cases) == 20
    assert Counter(case.category for case in holdout.dataset.cases) == {
        "exact_term": 4, "paraphrase": 4, "multi_document": 4,
        "exception_near_match": 4, "unanswerable": 4,
    }
    assert len(holdout.passages) == 203 and development.documents == holdout.documents
    assert not {a.identity() for a in development.dataset.anchors.values()} & {
        a.identity() for a in holdout.dataset.anchors.values()}
    fixture_root = DATASET_PATH.parents[3] / "tests/fixtures/pdfs"
    manifest = json.loads((fixture_root / "manifest.json").read_text())
    for anchor in holdout.dataset.anchors.values():
        authored = next((item for item in manifest["fixtures"]
                         if item["filename"] == anchor.document_id + ".pdf"), None)
        if authored is None:
            authored = json.loads((fixture_root / "sources" / (anchor.document_id + ".json")).read_text())
        sections = authored["pages"][anchor.page_number - 1]["sections"]
        assert sum(anchor.quote in section["text"] for section in sections) == 1


def test_plan_contains_text_only_inputs_not_labels_and_conservative_reservations(prepared):
    assert len(prepared.inputs) == 247 and len(prepared.batches) == 51
    assert Counter(item.kind for item in prepared.inputs.values()) == {"passage": 203, "query": 44}
    assert prepared.manifest["pricing"]["reserved_usd"] == price(247 * MAX_INPUT_TOKENS)
    assert all(0 < item.tokens <= MAX_INPUT_TOKENS for item in prepared.inputs.values())
    assert all(len(keys) * MAX_INPUT_TOKENS < 300_000 for keys in prepared.batches)
    assert len({key for keys in prepared.batches for key in keys}) == len(prepared.inputs)
    for corpus in prepared.corpora.values():
        for case in corpus.dataset.cases:
            assert prepared.inputs[query_key(case.query)].text == case.query
            assert len(case.query) <= 200
        for identity, passage in corpus.passages.items():
            assert prepared.inputs[passage_key(identity)].text == passage.text
    assert "quote" not in json.dumps(prepared.manifest)
    assert "rationale" not in json.dumps(prepared.manifest)


def test_default_dry_run_does_not_construct_provider_or_read_credentials(prepared, capsys):
    args = SimpleNamespace(replay=False, run_paid=False)
    with patch("evaluations.retrieval_embeddings.prepare", return_value=prepared), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("No client")), \
         patch("services.workspace_service.WorkspaceService.get_api_key", side_effect=AssertionError("No key")):
        assert asyncio.run(main(args))
    result = json.loads(capsys.readouterr().out)
    assert result["credential_access"] is False
    assert result["plan_sha256"] == prepared.plan_sha256


def test_tokenizer_failure_precedes_keys_or_provider():
    with patch("tiktoken.get_encoding", side_effect=RuntimeError("vocabulary unavailable")), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("No client")):
        with pytest.raises(RuntimeError, match="vocabulary"):
            asyncio.run(prepare())


@pytest.mark.parametrize("value", [None, "0", "-1", "0.000001", "NaN", "Infinity", "2"])
def test_invalid_or_insufficient_cap_fails_before_client_or_files(prepared, tmp_path, value):
    calls = []
    with pytest.raises(ValueError):
        asyncio.run(collect(prepared, cap_usd=value, approved_plan=prepared.plan_sha256,
                            client_factory=fake_factory(calls), directory=tmp_path / "attempt"))
    assert not calls and not (tmp_path / "attempt").exists()


def test_changed_approval_digest_and_stale_pricing_block_dispatch(prepared):
    with pytest.raises(ValueError, match="digest"):
        approve_plan(prepared, "0.05", "old-plan")
    with patch("evaluations.retrieval_embeddings.PRICE_VERIFIED_ON", "2020-01-01"):
        with pytest.raises(ValueError, match="pricing"):
            approve_plan(prepared, "0.05", prepared.plan_sha256)


@pytest.mark.parametrize("bad", [[0.0] * DIMENSIONS, [1.0], [True] * DIMENSIONS,
                                 [float("nan")] * DIMENSIONS, [float("inf")] * DIMENSIONS])
def test_invalid_vectors_fail_closed(bad):
    with pytest.raises(ValueError):
        normalize_vector(bad)


def test_vectors_use_cosine_and_rank_fusion_ignores_scale_and_duplicate_hits():
    assert normalize_vector([3, 4], 2) == [0.6, 0.8]
    a, b, c = [(name, "revision", 1, "p1_b1_v1") for name in ("a", "b", "c")]
    assert fuse_rankings([a, b], [b, c])[0] == b
    assert fuse_rankings([a, a, b], [c]) == fuse_rankings([a, b], [c])
    assert RRF_CONSTANT == 60


@pytest.mark.parametrize("change", [
    lambda r: setattr(r, "model", "different-model"),
    lambda r: setattr(r, "data", []),
    lambda r: setattr(r.data[0], "index", True),
    lambda r: setattr(r.data[0], "index", 10),
    lambda r: setattr(r.data[0], "index", r.data[1].index),
    lambda r: setattr(r.data[0], "embedding", [0.0] * DIMENSIONS),
    lambda r: setattr(r.usage, "prompt_tokens", 0),
    lambda r: setattr(r.usage, "total_tokens", -1),
    lambda r: setattr(r.usage, "prompt_tokens", 2 * MAX_INPUT_TOKENS + 1),
])
def test_unknown_response_or_usage_is_not_a_success(change):
    result = response(2)
    change(result)
    with pytest.raises(ValueError):
        validate_response(result, 2)


def test_complete_attempt_writes_before_dispatch_and_replays_without_spend(prepared, tmp_path):
    plan = small_plan(prepared)
    directory = tmp_path / "attempt"
    calls = []
    base_factory = fake_factory(calls)

    @asynccontextmanager
    async def factory():
        assert (directory / "plan.json").is_file()
        assert json.loads((directory / "ledger.jsonl").read_text().splitlines()[0])["event"] == "reserved"
        async with base_factory() as client:
            yield client

    assert asyncio.run(collect(plan, cap_usd="0.05", approved_plan=plan.plan_sha256,
                              client_factory=factory, directory=directory))
    assert len(calls) == 2
    assert all(call["model"] == MODEL and call["dimensions"] == DIMENSIONS for call in calls)
    assert [call["input"] for call in calls] == [[plan.inputs[key].text] for key in plan.inputs]
    cache = load_cache(plan, directory)
    assert set(cache["vectors"]) == set(plan.inputs)
    assert len(cache["requests"]) == 2
    # A second invocation cannot silently retry or reuse the same reservation.
    with pytest.raises(FileExistsError):
        asyncio.run(collect(plan, cap_usd="0.05", approved_plan=plan.plan_sha256,
                            client_factory=factory, directory=directory))
    assert len(calls) == 2


def test_uncertain_failure_stops_without_retry_leak_or_complete_cache(prepared, tmp_path):
    plan, calls = small_plan(prepared), []
    directory = tmp_path / "attempt"
    assert not asyncio.run(collect(plan, cap_usd="0.05", approved_plan=plan.plan_sha256,
        client_factory=fake_factory(calls, TimeoutError("sensitive-request-sentinel")), directory=directory))
    ledger = (directory / "ledger.jsonl").read_text()
    assert len(calls) == 1 and not (directory / "cache.json").exists()
    assert "sensitive-request-sentinel" not in ledger
    assert "dispatch_outcome_unknown" in ledger and "halted" in ledger
    assert json.loads(ledger.splitlines()[-1])["reservations_reclaimed_usd"] == "0"


def test_replay_separates_indexing_and_query_usage_without_new_calls(prepared, tmp_path):
    calls = []
    directory = tmp_path / "attempt"
    assert asyncio.run(collect(prepared, cap_usd="0.05", approved_plan=prepared.plan_sha256,
        client_factory=fake_factory(calls), directory=directory))
    with patch("evaluations.retrieval_embeddings.compare", return_value={"mocked": True}), \
         patch("openai.AsyncOpenAI", side_effect=AssertionError("Replay is unpaid")):
        result = replay(prepared, directory)
    assert len(calls) == 51
    assert result["embedding_usage"]["passage"]["requests"] == 7
    assert result["embedding_usage"]["query"]["requests"] == 44
    assert result["total_usage_based_usd"] == price(247)
    assert set(result["results"]) == {"development", "holdout"}
    assert all(value == {"mocked": True} for value in result["results"].values())
    # A complete cache file alone is insufficient after a failed finalization.
    with (directory / "ledger.jsonl").open("a") as ledger:
        ledger.write(json.dumps({"event": "halted"}) + "\n")
    with pytest.raises(ValueError):
        load_cache(prepared, directory)


@pytest.mark.parametrize("change", [("base_url", "https://example.invalid/v1/"), ("max_retries", 2)])
def test_endpoint_and_retry_guards_stop_before_any_dispatch(prepared, tmp_path, change):
    calls = []
    plan = small_plan(prepared)
    assert not asyncio.run(collect(plan, cap_usd="0.05", approved_plan=plan.plan_sha256,
        client_factory=fake_factory(calls, policy_change=change), directory=tmp_path / "attempt"))
    assert calls == []


def test_cache_rejects_corruption_missing_vectors_revisions_and_accounting(prepared, tmp_path):
    plan, calls = small_plan(prepared), []
    directory = tmp_path / "attempt"
    assert asyncio.run(collect(plan, cap_usd="0.05", approved_plan=plan.plan_sha256,
        client_factory=fake_factory(calls), directory=directory))
    path = directory / "cache.json"
    original = json.loads(path.read_text())
    changes = [
        lambda data: data.update(plan_sha256="obsolete-revision"),
        lambda data: data["vectors"].pop(next(iter(data["vectors"]))),
        lambda data: data["requests"].pop(),
        lambda data: data["requests"][0].update(input_keys=["wrong-query"]),
        lambda data: data["requests"][0].update(usage_based_usd="0"),
    ]
    for change in changes:
        changed = deepcopy(original["payload"])
        change(changed)
        path.write_text(json.dumps({"sha256": digest(changed), "payload": changed}))
        with pytest.raises(ValueError):
            load_cache(plan, directory)
    path.write_text(json.dumps({**original, "sha256": "corrupt"}))
    with pytest.raises(ValueError):
        load_cache(plan, directory)


def test_dense_source_identity_hybrid_and_scorer_with_fake_vectors(prepared):
    corpus = prepared.corpora["development"]
    case = corpus.dataset.cases[0]
    wanted = corpus.dataset.anchors[case.anchors[0]].identity()
    vectors = {key: vector(0) for key in prepared.inputs}
    vectors[passage_key(wanted)] = vector(1)
    vectors[query_key(case.query)] = vector(1)
    candidates = CachedCandidates(corpus, vectors)
    assert candidates.dense(case.query)[0] == wanted
    hit = candidates.search(corpus.documents, case.query, limit=5)["results"][0]
    assert hit["excerpt"] == corpus.passages[wanted].text
    assert hit["source_revision_id"] == wanted[1]
    with pytest.raises(ValueError):
        candidates.search([], case.query, limit=5)
    with patch("openai.AsyncOpenAI", side_effect=AssertionError("No provider")):
        reports = compare(corpus, vectors)["candidates"]
    assert set(reports) == {"lexical", "dense", "hybrid"}
    assert all(report["overall"]["invalid_hits"] == 0 for report in reports.values())
    assert all(report["dataset"]["questions"] == 24 for report in reports.values())
    # Without an abstention threshold dense always returns top-k near-matches.
    assert reports["dense"]["overall"]["unanswerable_nonempty_rate"] == 1.0
