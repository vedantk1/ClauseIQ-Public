"""Offline D58 ablations using the unchanged, strictly validated D57 cache.

Run from backend: python -m evaluations.retrieval_refinement
No provider, credential, database, indexing or paid-dispatch path exists here.
Previously inspected question splits are regression data, NOT new holdouts.
"""

import argparse
import asyncio
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from evaluations.library_search_cases import EvaluationCorpus, Identity, ROOT
from evaluations.library_search_evaluation import evaluate_search
from evaluations.retrieval_comparison import (
    CANDIDATE_DEPTH, RESULT_LIMIT, CachedCandidates, digest, fuse_rankings,
)
from evaluations.retrieval_embeddings import OUTPUT_ROOT, load_cache, prepare, write_exclusive
from services.library_search import _query_tokens, _tokens
from services.retrieval_policy import POLICY_VERSION, document_diverse, repeated_headers


REFINEMENT_VERSION = "retrieval-header-diversity-ablation-v1"
VARIANTS = ("filtered_lexical", "filtered_dense", "filtered_hybrid", "diverse_hybrid")


class RefinedCandidates(CachedCandidates):
    def __post_init__(self):
        super().__post_init__()
        self.excluded = repeated_headers(self.corpus.passages)
        self.eligible = [identity for identity in self.identities if identity not in self.excluded]
        self.terms = {identity: Counter(_tokens(self.corpus.passages[identity].text))
                      for identity in self.eligible}
        self.frequency = Counter(term for terms in self.terms.values() for term in terms)
        self.average_length = (sum(sum(terms.values()) for terms in self.terms.values())
                               / len(self.eligible) if self.eligible else 0) or 1.0

    def lexical(self, query: str) -> list[Identity]:
        """Same BM25 constants/tokenizer as baseline, over eligible passages only."""
        query_terms = _query_tokens(query)
        scored = []
        for identity, terms in self.terms.items():
            length = sum(terms.values())
            score = 0.0
            for term in query_terms:
                occurrences = terms[term]
                if occurrences:
                    inverse_frequency = math.log1p(
                        (len(self.eligible) - self.frequency[term] + 0.5)
                        / (self.frequency[term] + 0.5)
                    )
                    denominator = occurrences + 1.2 * (1 - 0.75 + 0.75 * length / self.average_length)
                    score += inverse_frequency * occurrences * 2.2 / denominator
            if score > 0:
                scored.append((score, identity))
        scored.sort(key=lambda item: (
            -item[0], self.filenames[item[1][0]].casefold(), item[1][0], item[1][2],
            self.corpus.passages[item[1]].start,
        ))
        return [identity for _, identity in scored[:CANDIDATE_DEPTH]]

    def dense(self, query: str) -> list[Identity]:
        # Filter BEFORE taking the top candidate window, not after. A rejected
        # header must not consume a slot or hide a lower-ranked body passage.
        scores = self.matrix @ self.queries[query]
        indices = [index for index, identity in enumerate(self.identities) if identity not in self.excluded]
        return [self.identities[index] for index in sorted(
            indices, key=lambda index: (-float(scores[index]), self.identities[index])
        )[:CANDIDATE_DEPTH]]

    def ranking(self, query: str, variant: str) -> list[Identity]:
        if variant not in VARIANTS:
            raise ValueError("Unknown refinement variant")
        if variant == "filtered_lexical":
            return self.lexical(query)
        if variant == "filtered_dense":
            return self.dense(query)
        return fuse_rankings(self.dense(query), self.lexical(query))

    def search_variant(self, documents, query: str, *, limit: int, variant: str) -> dict:
        if documents is not self.corpus.documents or limit != RESULT_LIMIT:
            raise ValueError("Comparison corpus or fixed result limit changed")
        ranked = self.ranking(query, variant)
        selected = document_diverse(ranked, limit) if variant == "diverse_hybrid" else ranked[:limit]
        return {"results": [
            {"document_id": identity[0], "source_revision_id": identity[1],
             "page_number": identity[2], "passage_id": identity[3],
             "filename": self.filenames[identity[0]], "excerpt": self.corpus.passages[identity].text}
            for identity in selected
        ], "coverage": {
            "source_passages": len(self.identities), "eligible_passages": len(self.eligible),
            "excluded_header_passages": len(self.excluded),
            "documents_searchable": len({identity[0] for identity in self.eligible}),
            "policy_version": POLICY_VERSION, "abstention_threshold": None,
        }}


def compare_refinement(corpus: EvaluationCorpus, vectors: dict) -> dict:
    candidates = RefinedCandidates(corpus, vectors)
    reports = {}
    for variant in VARIANTS:
        reports[variant] = evaluate_search(
            corpus,
            lambda documents, query, *, limit: candidates.search_variant(
                documents, query, limit=limit, variant=variant),
            RESULT_LIMIT,
        )
        reports[variant]["scope"] = "Inspected synthetic regression cases; not an untouched holdout or answer-quality test."
    return {
        "candidates": reports,
        "excluded": [{"identity": list(identity), "reason": reason,
                      "text": corpus.passages[identity].text}
                     for identity, reason in sorted(candidates.excluded.items())],
    }


def replay_refinement(prepared, directory: Path) -> dict:
    # Keep the original code/input/source/dataset validator intact: changing the
    # producer or its input text invalidates this cache, not silently relabels it.
    cache = load_cache(prepared, directory)
    paths = ("evaluations/retrieval_refinement.py", "services/retrieval_policy.py")
    consumer = {
        "version": REFINEMENT_VERSION, "policy_version": POLICY_VERSION,
        "producer_plan_sha256": prepared.plan_sha256,
        "cache_payload_sha256": digest(cache),
        "code_sha256": {path: hashlib.sha256((ROOT / "backend" / path).read_bytes()).hexdigest()
                        for path in paths},
    }
    return {
        "consumer": consumer, "consumer_sha256": digest(consumer),
        "new_provider_calls": 0, "new_usage_based_usd": "0",
        "results": {split: compare_refinement(corpus, cache["vectors"])
                    for split, corpus in prepared.corpora.items()},
        "limits": "Both question splits have been inspected. Post-change regression, not independent validation. No generated answers or runtime index. All variants still lack abstention.",
        "latency_caveat": "Offline ranking with prebuilt lexical and dense indexes; excludes construction, PDF extraction and API latency. Not directly comparable with the baseline per-query lexical rebuild.",
    }


async def main(output: Path | None = None) -> None:
    prepared = await prepare()
    report = replay_refinement(prepared, OUTPUT_ROOT / prepared.plan_sha256)
    if output is not None:
        # Raw source excerpts and case-level diagnostics remain private.
        output = output.resolve()
        if not output.is_relative_to(OUTPUT_ROOT.resolve()):
            raise ValueError("Reports must stay under the private retrieval comparison directory")
        write_exclusive(output, report)
        print(json.dumps({"consumer_sha256": report["consumer_sha256"], "new_provider_calls": 0}))
    else:
        print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Exclusive private report file; never overwrite an earlier result")
    asyncio.run(main(parser.parse_args().output))
