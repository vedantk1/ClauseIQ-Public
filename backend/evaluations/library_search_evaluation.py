"""Unpaid retrieval evaluation. Run: python -m evaluations.library_search_evaluation."""

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Callable
import json
import math
from statistics import mean
import time
from typing import Any

from evaluations.library_search_cases import EvaluationCorpus, Identity, RetrievalCase, prepare_corpus


def _identity(hit: dict) -> Identity:
    return (hit.get("document_id"), hit.get("source_revision_id"), hit.get("page_number"), hit.get("passage_id"))


def score_case(corpus: EvaluationCorpus, case: RetrievalCase, hits: list[dict], limit: int) -> dict:
    """Score exact source identity, not answer quality or matching words in prose."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Evaluation limit must be an integer from 1 to 20")
    selected = hits[:limit]
    expected = {corpus.dataset.anchors[key].identity() for key in case.anchors}
    expected_documents = {identity[0] for identity in expected}
    valid: set[Identity] = set()
    invalid = 0
    duplicate = 0
    for hit in selected:
        identity = _identity(hit)
        passage = corpus.passages.get(identity)
        excerpt = hit.get("excerpt")
        if (passage is None or not isinstance(excerpt, str) or not excerpt
                or excerpt not in passage.text or type(hit.get("page_number")) is not int):
            invalid += 1
            continue
        duplicate += identity in valid
        valid.add(identity)
    relevant_passages = valid & expected
    relevant_documents = {identity[0] for identity in valid} & expected_documents
    returned_documents = {hit.get("document_id") for hit in selected}
    return {
        "case_id": case.id, "category": case.category,
        "expected_documents": len(expected_documents), "expected_passages": len(expected),
        "returned_hits": len(selected), "returned_documents": len(returned_documents),
        "document_recall_at_k": len(relevant_documents) / len(expected_documents) if expected_documents else None,
        "document_precision_at_k": len(relevant_documents) / len(returned_documents) if expected_documents and returned_documents else (0.0 if expected_documents else None),
        "passage_recall_at_k": len(relevant_passages) / len(expected) if expected else None,
        "passage_precision_at_k": len(relevant_passages) / limit if expected else None,
        "unanswerable_nonempty": bool(selected) if not expected else None,
        "invalid_hits": invalid, "duplicate_hits": duplicate,
        "missing_relevant_passages": [list(identity) for identity in sorted(expected - valid)],
    }


def summarize(rows: list[dict]) -> dict:
    result: dict[str, Any] = {"cases": len(rows)}
    for metric in ("document_recall_at_k", "document_precision_at_k", "passage_recall_at_k", "passage_precision_at_k"):
        values = [row[metric] for row in rows if row[metric] is not None]
        result["macro_" + metric] = mean(values) if values else None
    negatives = [row["unanswerable_nonempty"] for row in rows if row["unanswerable_nonempty"] is not None]
    result["unanswerable_cases"] = len(negatives)
    result["unanswerable_nonempty_rate"] = mean(negatives) if negatives else None
    result["invalid_hits"] = sum(row["invalid_hits"] for row in rows)
    result["duplicate_hits"] = sum(row["duplicate_hits"] for row in rows)
    durations = sorted(row["latency_ms"] for row in rows)
    result["latency_ms"] = {
        "p50": durations[math.ceil(len(durations) * 0.5) - 1] if durations else None,
        "p95": durations[math.ceil(len(durations) * 0.95) - 1] if durations else None,
        "definition": "Nearest-rank query latency, including the search callable's index preparation but excluding fixture PDF extraction.",
    }
    return result


def evaluate_search(corpus: EvaluationCorpus, searcher: Callable, limit: int = 5) -> dict:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Evaluation limit must be an integer from 1 to 20")
    rows, groups = [], defaultdict(list)
    for case in corpus.dataset.cases:
        start = time.perf_counter()
        # Only documents and the query reach retrieval. Labels/rationales stay here.
        response = searcher(corpus.documents, case.query, limit=limit)
        latency = (time.perf_counter() - start) * 1000
        payload = response.model_dump() if hasattr(response, "model_dump") else response
        row = score_case(corpus, case, payload["results"], limit)
        row["latency_ms"] = round(latency, 3)
        row["coverage"] = payload.get("coverage")
        rows.append(row)
        groups[case.category].append(row)
    return {
        "dataset": {"id": corpus.dataset.id, "version": corpus.dataset.version,
                    "sha256": corpus.dataset_sha256, "questions": len(rows),
                    "documents": len(corpus.documents), "passages": len(corpus.passages),
                    "extraction_version": corpus.dataset.extraction_version, "passage_version": corpus.dataset.passage_version},
        "limit": limit,
        "scope": "Authored synthetic development retrieval regression; no model answers, provider calls or legal-quality assessment.",
        "metric_definitions": {
            "document": "Recall over labelled relevant documents; precision over distinct returned document IDs within the first k hits. Invalid source hits receive no credit.",
            "passage": "Recall over labelled exact document/revision/page/passage identities; precision divides relevant unique passages by k, including unfilled result slots.",
            "unanswerable": "Separate proportion of reviewed no-answer cases returning any result; excluded from answerable precision/recall means.",
            "valid_source_hit": "The hit resolves to the exact frozen source revision/page/passage and its nonempty excerpt is a verbatim substring. This is not semantic citation correctness.",
        },
        "overall": summarize(rows), "by_category": {name: summarize(group) for name, group in sorted(groups.items())},
        "cases": rows,
    }


async def _main(limit: int) -> None:
    from services.library_search import search_passages

    corpus = await prepare_corpus()
    report = evaluate_search(corpus, search_passages, limit)
    report["retriever"] = "local-lexical-baseline"
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, choices=range(1, 21), metavar="1..20")
    arguments = parser.parse_args()
    asyncio.run(_main(arguments.limit))
