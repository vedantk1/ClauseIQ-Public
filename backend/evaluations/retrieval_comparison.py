"""Fixed, development-only retrieval candidates over the frozen synthetic corpus.

No provider or workspace access. Cached exact vectors are not a product index.
Labels are used only by the existing scorer, never as retrieval inputs.
"""

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from evaluations.library_search_cases import EvaluationCorpus, Identity
from evaluations.library_search_evaluation import evaluate_search
from services.library_search import search_passages


MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
CANDIDATE_DEPTH = 20
RRF_CONSTANT = 60
RESULT_LIMIT = 5
COMPARISON_VERSION = "synthetic-exact-dense-rrf-v1"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def passage_key(identity: Identity) -> str:
    return "passage:" + digest(identity)


def query_key(query: str) -> str:
    return "query:" + digest(query)


def normalize_vector(vector: list, dimensions: int = DIMENSIONS) -> list[float]:
    if (not isinstance(vector, list) or len(vector) != dimensions
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)):
        raise ValueError("Embedding dimensions or numeric values are invalid")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Embedding norm must be positive and finite")
    return [value / norm for value in vector]


def fuse_rankings(*rankings: list[Identity]) -> list[Identity]:
    """Equal-weight reciprocal rank fusion; duplicates never increase a score."""
    scores: dict[Identity, float] = {}
    for ranking in rankings:
        seen: set[Identity] = set()
        for identity in ranking[:CANDIDATE_DEPTH]:
            if identity in seen:
                continue
            seen.add(identity)
            scores[identity] = scores.get(identity, 0.0) + 1 / (RRF_CONSTANT + len(seen))
    return sorted(scores, key=lambda identity: (-scores[identity], identity))


@dataclass
class CachedCandidates:
    corpus: EvaluationCorpus
    vectors: dict[str, list[float]]

    def __post_init__(self):
        self.identities = sorted(self.corpus.passages)
        self.matrix = np.asarray([normalize_vector(self.vectors[passage_key(identity)])
                                  for identity in self.identities], dtype=np.float64)
        self.queries = {case.query: np.asarray(normalize_vector(self.vectors[query_key(case.query)]),
                                              dtype=np.float64)
                        for case in self.corpus.dataset.cases}
        self.filenames = {document["id"]: document["filename"] for document in self.corpus.documents}

    def dense(self, query: str) -> list[Identity]:
        scores = self.matrix @ self.queries[query]
        return [self.identities[index] for index in sorted(
            range(len(scores)), key=lambda index: (-float(scores[index]), self.identities[index])
        )[:CANDIDATE_DEPTH]]

    def search(self, documents, query: str, *, limit: int, hybrid: bool = False) -> dict:
        if documents is not self.corpus.documents or limit != RESULT_LIMIT:
            raise ValueError("Comparison corpus or fixed result limit changed")
        ranked = self.dense(query)
        if hybrid:
            lexical = search_passages(documents, query, limit=CANDIDATE_DEPTH)
            ranked = fuse_rankings(ranked, [
                (hit.document_id, hit.source_revision_id, hit.page_number, hit.passage_id)
                for hit in lexical.results
            ])
        results = []
        for identity in ranked[:limit]:
            passage = self.corpus.passages[identity]
            results.append({"document_id": identity[0], "source_revision_id": identity[1],
                            "page_number": identity[2], "passage_id": identity[3],
                            "filename": self.filenames[identity[0]], "excerpt": passage.text})
        return {"results": results, "coverage": {
            "documents_in_library": len(documents),
            "documents_searchable": len({identity[0] for identity in self.identities}),
            "passages_examined": len(self.identities),
            "index_complete_for_extractable_corpus": True,
            "abstention_threshold": None,
        }}


def compare(corpus: EvaluationCorpus, vectors: dict[str, list[float]]) -> dict:
    candidates = CachedCandidates(corpus, vectors)
    reports = {}
    for name, searcher in (
        ("lexical", search_passages),
        ("dense", candidates.search),
        ("hybrid", lambda documents, query, *, limit:
            candidates.search(documents, query, limit=limit, hybrid=True)),
    ):
        reports[name] = evaluate_search(corpus, searcher, RESULT_LIMIT)
        reports[name]["scope"] = "Frozen synthetic retrieval comparison, not generated-answer or legal-quality evaluation."
    return {"candidates": reports, "latency_caveat": (
        "Offline ranking only: query embedding API latency is reported separately. "
        "Lexical rebuilds its in-memory index per query; dense uses a preloaded exact matrix; "
        "hybrid includes both. Not a production/Qdrant latency or scale benchmark."
    )}
