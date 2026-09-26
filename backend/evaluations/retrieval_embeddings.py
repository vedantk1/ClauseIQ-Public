"""Synthetic-only embedding experiment. Default: key-free dry run; no API calls.

Run from backend: python -m evaluations.retrieval_embeddings
Paid dispatch requires an approved plan digest and an explicit total USD ceiling.
Replay reads an already complete private cache, never calls a provider.
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time

from evaluations.library_search_cases import DATASET_PATH, ROOT, prepare_corpus
from evaluations.retrieval_comparison import (
    CANDIDATE_DEPTH, COMPARISON_VERSION, DIMENSIONS, MODEL, RESULT_LIMIT,
    RRF_CONSTANT, compare, digest, normalize_vector, passage_key, query_key,
)


PRICE_PER_MILLION = Decimal("0.02")
PRICE_VERIFIED_ON = "2026-09-26"
MAX_INPUT_TOKENS = 8192
PASSAGES_PER_REQUEST = 32  # Even maximum-sized inputs stay below 300,000 tokens.
ENDPOINT = "https://api.openai.com/v1/"
OUTPUT_ROOT = ROOT / ".local-only/retrieval-comparison"


@dataclass(frozen=True)
class EmbeddingInput:
    key: str
    kind: str
    text: str
    tokens: int


@dataclass(frozen=True)
class PreparedComparison:
    corpora: dict
    inputs: dict[str, EmbeddingInput]
    batches: list[list[str]]
    manifest: dict

    @property
    def plan_sha256(self) -> str:
        return digest(self.manifest)


def price(tokens: int) -> str:
    return str(Decimal(tokens) * PRICE_PER_MILLION / 1_000_000)


async def prepare() -> PreparedComparison:
    """All source/label/tokenizer checks finish before any credential access."""
    import tiktoken

    corpora = {"development": await prepare_corpus(),
               "holdout": await prepare_corpus(DATASET_PATH.with_name("holdout.json"))}
    development, holdout = corpora.values()
    if (development.documents != holdout.documents
            or development.passages != holdout.passages
            or {a.identity() for a in development.dataset.anchors.values()}
            & {a.identity() for a in holdout.dataset.anchors.values()}
            or {case.query for case in development.dataset.cases}
            & {case.query for case in holdout.dataset.cases}):
        raise ValueError("Split corpus mismatch or development/holdout label overlap")
    encoder = tiktoken.get_encoding("cl100k_base")
    inputs = {}

    def add(key, kind, text):
        tokens = len(encoder.encode(text, disallowed_special=()))
        if not text.strip() or not 1 <= tokens <= MAX_INPUT_TOKENS or key in inputs:
            raise ValueError("Empty, oversized or duplicate embedding input; never truncate")
        inputs[key] = EmbeddingInput(key, kind, text, tokens)

    for identity, passage in sorted(development.passages.items()):
        add(passage_key(identity), "passage", passage.text)
    for corpus in corpora.values():
        for case in corpus.dataset.cases:
            add(query_key(case.query), "query", case.query)
    passage_keys = [key for key, item in inputs.items() if item.kind == "passage"]
    query_keys = [key for key, item in inputs.items() if item.kind == "query"]
    batches = [passage_keys[start:start + PASSAGES_PER_REQUEST]
               for start in range(0, len(passage_keys), PASSAGES_PER_REQUEST)]
    # Serial single-query requests measure actual embedding latency, not batched
    # throughput disguised as an interactive query's latency.
    batches.extend([key] for key in query_keys)
    code_paths = ["evaluations/retrieval_embeddings.py", "evaluations/retrieval_comparison.py",
                  "evaluations/library_search_cases.py", "evaluations/library_search_evaluation.py",
                  "services/library_search.py", "services/ai/review_passages.py",
                  "services/ai/text_extractor.py"]
    manifest = {
        "version": COMPARISON_VERSION, "model": MODEL, "dimensions": DIMENSIONS,
        "ranking": {"dense": "exact cosine", "hybrid": "equal-weight RRF", "rrf_constant": RRF_CONSTANT,
                    "candidate_depth": CANDIDATE_DEPTH, "result_limit": RESULT_LIMIT,
                    "abstention_threshold": None},
        "datasets": {split: {"id": corpus.dataset.id, "sha256": corpus.dataset_sha256,
                             "cases": len(corpus.dataset.cases)} for split, corpus in corpora.items()},
        "source_manifest_sha256": digest([document.model_dump() for document in development.dataset.documents]),
        "code_sha256": {path: hashlib.sha256((ROOT / "backend" / path).read_bytes()).hexdigest()
                        for path in code_paths},
        "extraction_version": development.dataset.extraction_version,
        "passage_version": development.dataset.passage_version,
        "inputs": [{"key": item.key, "kind": item.kind, "sha256": digest(item.text),
                    "estimated_tokens": item.tokens} for item in inputs.values()],
        "batches": batches,
        "pricing": {"verified_on": PRICE_VERIFIED_ON, "usd_per_million_input_tokens": str(PRICE_PER_MILLION),
                    "source": "https://developers.openai.com/api/docs/models/text-embedding-3-small",
                    "estimated_tokens": sum(item.tokens for item in inputs.values()),
                    "estimated_usd": price(sum(item.tokens for item in inputs.values())),
                    "reserved_usd": price(MAX_INPUT_TOKENS * len(inputs)),
                    "reservation_rule": "Full 8192-token per-input ceilings; reserve all inputs before key access; never reclaim within this run."},
    }
    return PreparedComparison(corpora, inputs, batches, manifest)


def approve_plan(prepared: PreparedComparison, cap_usd: str | None, approved_plan: str | None) -> Decimal:
    if approved_plan != prepared.plan_sha256:
        raise ValueError("Explicit approval must name the exact prepared plan digest")
    cap = Decimal(cap_usd or "0")
    reserved = Decimal(prepared.manifest["pricing"]["reserved_usd"])
    if not cap.is_finite() or not 0 < cap <= 1 or reserved > cap:
        raise ValueError("All conservative input ceilings must fit the explicit USD cap (maximum 1)")
    age = (date.today() - date.fromisoformat(PRICE_VERIFIED_ON)).days
    if not 0 <= age <= 7:
        raise ValueError("Recheck official pricing and refresh the plan before live dispatch")
    return cap


def write_exclusive(path: Path, value: dict) -> None:
    # Exclusive files plus fsync keep uncertain attempts from being silently
    # overwritten or replayed as though no request had been sent.
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, allow_nan=False, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def validate_response(response, count: int) -> tuple[list[list[float]], int]:
    if response.model != MODEL or len(response.data) != count:
        raise ValueError("Unexpected model or embedding count")
    indexed = {}
    for item in response.data:
        if type(item.index) is not int or not 0 <= item.index < count or item.index in indexed:
            raise ValueError("Missing, duplicate or invalid embedding index")
        normalize_vector(item.embedding)  # Validate but retain original vector bytes in the cache.
        indexed[item.index] = item.embedding
    tokens = response.usage.prompt_tokens
    if (type(tokens) is not int or not 0 < tokens <= count * MAX_INPUT_TOKENS
            or type(response.usage.total_tokens) is not int or response.usage.total_tokens != tokens):
        raise ValueError("Unknown or out-of-reservation provider usage")
    return [indexed[index] for index in range(count)], tokens


async def collect(prepared: PreparedComparison, *, cap_usd: str, approved_plan: str,
                  client_factory, directory: Path) -> bool:
    """Explicit opt-in only. Injected client factory is never touched by dry runs."""
    cap = approve_plan(prepared, cap_usd, approved_plan)
    directory.mkdir(parents=True, exist_ok=False)
    write_exclusive(directory / "plan.json", {"plan_sha256": prepared.plan_sha256,
                    "approved_cap_usd": str(cap), "manifest": prepared.manifest})
    records, vectors = [], {}
    with (directory / "ledger.jsonl").open("x", encoding="utf-8") as ledger:
        def record(event):
            ledger.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **event},
                                    allow_nan=False, sort_keys=True) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())

        record({"event": "reserved", "reserved_usd": prepared.manifest["pricing"]["reserved_usd"]})
        try:
            async with client_factory() as client:
                if str(client.base_url) != ENDPOINT or client.max_retries != 0:
                    raise ValueError("Provider endpoint or retry policy changed")
                for number, keys in enumerate(prepared.batches):
                    record({"event": "dispatch_outcome_unknown", "batch": number,
                            "input_keys": keys, "reserved_usd": price(len(keys) * MAX_INPUT_TOKENS)})
                    started = time.perf_counter()
                    response = await client.embeddings.create(
                        model=MODEL, dimensions=DIMENSIONS, encoding_format="float",
                        input=[prepared.inputs[key].text for key in keys],
                    )
                    duration = round((time.perf_counter() - started) * 1000, 3)
                    embedded, tokens = validate_response(response, len(keys))
                    vectors.update(zip(keys, embedded))
                    outcome = {"batch": number, "kind": prepared.inputs[keys[0]].kind,
                               "input_keys": keys, "latency_ms": duration,
                               "provider_input_tokens": tokens, "usage_based_usd": price(tokens)}
                    records.append(outcome)
                    record({"event": "response_accepted", **outcome})
            cache = {"plan_sha256": prepared.plan_sha256, "vectors": vectors, "requests": records}
            write_exclusive(directory / "cache.json", {"sha256": digest(cache), "payload": cache})
            record({"event": "completed", "reservations_reclaimed_usd": "0"})
            return True
        except Exception as error:
            # Never retain str(error), SDK request bodies, keys or provider errors.
            record({"event": "halted", "error_type": type(error).__name__,
                    "reservations_reclaimed_usd": "0", "automatic_retry": False})
            return False


def load_cache(prepared: PreparedComparison, directory: Path) -> dict:
    saved_plan = json.loads((directory / "plan.json").read_text())
    events = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
    wrapper = json.loads((directory / "cache.json").read_text())
    cache = wrapper["payload"]
    if (saved_plan["manifest"] != prepared.manifest or not events or events[-1]["event"] != "completed"
            or wrapper["sha256"] != digest(cache) or cache["plan_sha256"] != prepared.plan_sha256
            or set(cache["vectors"]) != set(prepared.inputs)
            or len(cache["requests"]) != len(prepared.batches)):
        raise ValueError("Incomplete, corrupt or obsolete embedding cache")
    for vector in cache["vectors"].values():
        normalize_vector(vector)
    for index, (request, keys) in enumerate(zip(cache["requests"], prepared.batches)):
        tokens = request["provider_input_tokens"]
        if (request["batch"] != index or request["input_keys"] != keys
                or request["kind"] != prepared.inputs[keys[0]].kind
                or type(tokens) is not int or not 0 < tokens <= len(keys) * MAX_INPUT_TOKENS
                or request["usage_based_usd"] != price(tokens)
                or type(request["latency_ms"]) not in (int, float)
                or not 0 <= request["latency_ms"] < float("inf")):
            raise ValueError("Cache request accounting is invalid")
    return cache


def replay(prepared: PreparedComparison, directory: Path) -> dict:
    cache = load_cache(prepared, directory)
    usage = {}
    for kind in ("passage", "query"):
        rows = [row for row in cache["requests"] if row["kind"] == kind]
        durations = sorted(row["latency_ms"] for row in rows)
        usage[kind] = {"requests": len(rows), "provider_input_tokens": sum(row["provider_input_tokens"] for row in rows),
                       "usage_based_usd": str(sum(Decimal(row["usage_based_usd"]) for row in rows)),
                       "latency_ms": {"total": sum(durations),
                                      "p50": durations[math.ceil(len(durations) * 0.5) - 1],
                                      "p95": durations[math.ceil(len(durations) * 0.95) - 1]}}
    return {"plan_sha256": prepared.plan_sha256, "manifest": prepared.manifest,
            "embedding_requests": cache["requests"],
            "embedding_usage": usage,
            "total_usage_based_usd": str(sum(Decimal(row["usage_based_usd"]) for row in cache["requests"])),
            "results": {split: compare(corpus, cache["vectors"]) for split, corpus in prepared.corpora.items()},
            "limits": "Known synthetic contracts; assistant-authored labels, not independent legal assessment. No generated answers. Dense/hybrid have no abstention threshold."}


async def main(arguments) -> bool:
    prepared = await prepare()
    directory = OUTPUT_ROOT / prepared.plan_sha256
    if arguments.replay:
        print(json.dumps(replay(prepared, directory), indent=2, allow_nan=False))
        return True
    if not arguments.run_paid:
        print(json.dumps({"dry_run": True, "credential_access": False,
                          "plan_sha256": prepared.plan_sha256, "manifest": prepared.manifest}, indent=2))
        return True
    # Delayed imports prevent normal CI/dry-run paths from touching workspace
    # settings. Suppress SDK/content logging in this one-off process.
    logging.disable(logging.CRITICAL)
    from contextlib import asynccontextmanager
    from openai import AsyncOpenAI
    from database.factory import DatabaseFactory
    from services.workspace_service import get_workspace_service

    @asynccontextmanager
    async def client_factory():
        try:
            key = await get_workspace_service().get_api_key()
            if not key:
                raise ValueError("No saved workspace API key; no call made")
            async with AsyncOpenAI(api_key=key, base_url=ENDPOINT, max_retries=0, timeout=60) as client:
                yield client
        finally:
            await DatabaseFactory.close()

    success = await collect(prepared, cap_usd=arguments.cap_usd, approved_plan=arguments.approved_plan,
                            client_factory=client_factory, directory=directory)
    print(json.dumps({"status": "complete" if success else "halted", "plan_sha256": prepared.plan_sha256,
                      "automatic_retry": False}))
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run-paid", action="store_true")
    modes.add_argument("--replay", action="store_true")
    parser.add_argument("--cap-usd", help="Explicit approved total ceiling; there is no default approval")
    parser.add_argument("--approved-plan", help="Exact plan_sha256 from the key-free dry run")
    try:
        succeeded = asyncio.run(main(parser.parse_args()))
    except Exception as error:
        print(json.dumps({"status": "refused_or_failed", "error_type": type(error).__name__}))
        succeeded = False
    raise SystemExit(0 if succeeded else 1)
