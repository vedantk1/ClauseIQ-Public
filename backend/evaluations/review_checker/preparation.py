"""Read-only preparation of one development diagnostic; no keys or app writes."""

import hashlib
import json

from pydantic import ValidationError

from clauseiq_types.review import ReviewGeneration
from services.ai.generation import AIRequestError, generation_metadata
from services.ai.review_generation import _source
from services.ai.review_passages import PASSAGE_VERSION, build_review_passages
from services.ai.token_utils import _positive_env_integer, calculate_token_budget, get_token_count
from .contract import CheckBinding, CheckCandidate, DiagnosticReport, MAX_CHECK_TARGETS, PreparedCheck
from .prompt import CHECK_SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION

CHECK_MODEL = "gpt-6-sol"
MAX_CANDIDATE_BYTES = 1_000_000
MAX_COMPLETION_TOKENS = 16_000
OUTPUT_RESERVE_TOKENS = 4096
TOKENS_PER_TARGET_RESERVE = 80
FINDING_FIELDS = ("title", "facts", "interpretation", "uncertainty", "next_step", "suggested_question", "coverage_basis")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def prepare_check(document: dict, candidate: CheckCandidate | dict, model_id: str = CHECK_MODEL) -> PreparedCheck:
    """Reject mismatches or capacity limits before any credential/provider access."""
    if model_id != CHECK_MODEL:
        raise ValueError("The development checker uses its fixed Sol model.")
    try:
        # Revalidate even a model instance; model_copy(update=...) can bypass Pydantic validation.
        raw = candidate.model_dump(warnings=False) if isinstance(candidate, CheckCandidate) else candidate
        if len(canonical_json(raw).encode("utf-8")) > MAX_CANDIDATE_BYTES:
            raise ValueError("Candidate exceeds its preparation limit.")
        snapshot = CheckCandidate.model_validate(raw).model_copy(deep=True)
        extraction, extracted_pages = _source(document)
        if snapshot.source_revision_id != document["source_revision_id"]:
            raise ValueError("Candidate source identity mismatch.")
        expected_omitted = [page.page_number for page in extraction.pages if page.status != "extracted"]
        if (snapshot.coverage.page_count != extraction.page_count
                or snapshot.coverage.extracted_pages != extracted_pages
                or snapshot.coverage.omitted_pages != expected_omitted):
            raise ValueError("Candidate coverage mismatch.")
        if len({item.id for item in snapshot.findings}) != len(snapshot.findings):
            raise ValueError("Duplicate finding identities.")
        if any(item.basis == "not_found" and not item.coverage_basis.strip() for item in snapshot.findings):
            raise ValueError("Missing-term candidates must retain their stated scope.")
        passages = build_review_passages(extraction, snapshot.source_revision_id)
        by_range = {
            (passage.page_number, passage.span_ids[0], passage.span_ids[-1], passage.text): passage.id
            for passage in passages
        }
        targets = {}
        target_payload = []
        items = []

        def add_target(item_id, field, text):
            target_id = f"{item_id}.{field}"
            targets[target_id] = text
            target_payload.append({"target_id": target_id, "item_id": item_id, "field": field, "text": text})

        def add_item(item_id, item, fields):
            evidence = []
            selected_ids = set()
            for index, reference in enumerate(item.evidence, 1):
                passage_id = by_range.get((reference.page_number, reference.span_id,
                                           reference.end_span_id or reference.span_id, reference.quote))
                if reference.source_revision_id != snapshot.source_revision_id or not passage_id or passage_id in selected_ids:
                    raise ValueError("Candidate evidence is not a unique canonical passage.")
                selected_ids.add(passage_id)
                label_field = f"evidence_{index}.label"
                add_target(item_id, label_field, reference.label)
                evidence.append({"passage_id": passage_id, "label_target_id": f"{item_id}.{label_field}"})
            for field in fields:
                add_target(item_id, field, getattr(item, field))
            entry = {"item_id": item_id, "evidence": evidence}
            if hasattr(item, "basis"):
                entry.update(basis=item.basis, original_finding_id=item.id)
            items.append(entry)

        for index, item in enumerate(snapshot.overview_items, 1):
            add_item(f"overview_{index}", item, ("text",))
        for index, item in enumerate(snapshot.findings, 1):
            add_item(f"finding_{index}", item, FINDING_FIELDS)
        for index, limitation in enumerate(snapshot.coverage.limitations, 1):
            if len(limitation) > 2000:
                raise ValueError("Candidate limitation exceeds the diagnostic field limit.")
            add_target("coverage", f"limitation_{index}", limitation)
        if len(targets) > MAX_CHECK_TARGETS:
            raise ValueError("Candidate has too many mandatory diagnostic targets.")
        metadata = generation_metadata(model_id, "review", reasoning_effort="medium")
        # A planning reserve, not a promise that the model can finish every semantic task.
        # Refuse large target inventories or undersized budgets instead of dropping fields.
        required_output = OUTPUT_RESERVE_TOKENS + TOKENS_PER_TARGET_RESERVE * len(targets)
        if not required_output <= metadata["max_completion_tokens"] <= MAX_COMPLETION_TOKENS:
            raise ValueError("Completion budget cannot accommodate the mandatory diagnostic inventory.")
        binding = CheckBinding(
            source_revision_id=snapshot.source_revision_id, source_sha256=extraction.content_sha256,
            extraction_sha256=_digest(extraction.model_dump()), extraction_version=extraction.extraction_version,
            passage_version=PASSAGE_VERSION, candidate_sha256=_digest(snapshot.model_dump()),
            brief_sha256=_digest(snapshot.context.model_dump()),
        )
        payload = {
            "brief": snapshot.context.model_dump(),
            "source": {"revision_id": snapshot.source_revision_id, "passage_version": PASSAGE_VERSION,
                       "page_count": extraction.page_count, "extracted_pages": extracted_pages,
                       "omitted_pages": expected_omitted,
                       "passages": [{"passage_id": passage.id, "page_number": passage.page_number,
                                     "text": passage.text, "continuation_before": passage.continuation_before,
                                     "continuation_after": passage.continuation_after} for passage in passages]},
            "candidate": {"items": items, "targets": target_payload},
        }
        response_format = {"type": "json_schema", "json_schema": {
            "name": "review_diagnostics", "strict": True, "schema": DiagnosticReport.model_json_schema(),
        }}
        messages = [{"role": "system", "content": CHECK_SYSTEM_PROMPT},
                    {"role": "user", "content": canonical_json(payload)}]
        estimate = sum(get_token_count(item["content"], model_id) + 8 for item in messages) + 16
        estimate += get_token_count(canonical_json(response_format), model_id)
        if estimate > calculate_token_budget(model_id, metadata["max_completion_tokens"]):
            raise ValueError("Complete checker input exceeds the configured token budget.")
        timeout = min(_positive_env_integer("AI_REVIEW_CHECK_TIMEOUT_SECONDS", 120), 180)
        return PreparedCheck(
            generation=ReviewGeneration(**metadata, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                                        extraction_version=extraction.extraction_version, estimated_input_tokens=estimate),
            messages=messages, response_format=response_format, timeout_seconds=timeout, binding=binding,
            targets=targets, item_ids=frozenset(item["item_id"] for item in items),
            passage_ids=frozenset(passage.id for passage in passages), priorities=snapshot.context.priorities,
            source_complete=extraction.status == "complete",
        )
    except (AIRequestError, ValueError, TypeError, KeyError, ValidationError, UnicodeError, ImportError, OSError):
        # Neither failed candidate material nor raw Pydantic/provider details escape preflight.
        raise ValueError("The source/candidate or checker limits are inconsistent or unsupported. Nothing was sent.") from None
