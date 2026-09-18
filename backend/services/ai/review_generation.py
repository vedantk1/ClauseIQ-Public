"""One bounded review call with server-resolved, exact source passages.

The provider selects passage IDs, never writes authoritative source quotations.
Each ID resolves only inside the prepared source snapshot to a complete page-local
range of stored line anchors. This establishes location, not semantic support.
No storage, credentials, retries or model fallback live in this module.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from clauseiq_types.review import (
    ReviewBrief, ReviewCoverage, ReviewEvidence, ReviewFailure, ReviewFinding,
    ReviewGeneration, ReviewModel, ReviewOverviewItem, ReviewUsage,
)
from clauseiq_types.source import SourceExtraction
from .generation import AIRequestError, create_chat_completion, generation_metadata
from .review_prompt import PROMPT_VERSION, REVIEW_SYSTEM_PROMPT, SCHEMA_VERSION
from .review_passages import PASSAGE_VERSION, build_review_passages
from .token_utils import _positive_env_integer, calculate_token_budget, get_token_count

DEFAULT_REVIEW_TIMEOUT_SECONDS = 120
MAX_REVIEW_TIMEOUT_SECONDS = 180
MAX_RESPONSE_CHARACTERS = 1_000_000
# Compact provider IDs can expand into repeated full passages. Bound the UTF-8
# JSON envelope for resolved overview/findings, not only the provider response.
# This is a per-result safety limit, not a migration or total-document-size limit.
MAX_RESOLVED_REVIEW_BYTES = 1_000_000
SOURCE_LIMITATION = (
    "All successfully extracted text was supplied. Extraction and exact quote matches "
    "do not establish complete review, legal validity or correct interpretation."
)


class GeneratedEvidence(ReviewModel):
    passage_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)


class GeneratedOverviewItem(ReviewModel):
    evidence: list[GeneratedEvidence] = Field(min_length=1, max_length=30)
    text: str = Field(min_length=1, max_length=2000)


class GeneratedFinding(ReviewModel):
    """Provider shape: IDs are assigned locally only after complete validation."""
    title: str = Field(min_length=1, max_length=300)
    evidence: list[GeneratedEvidence] = Field(min_length=1, max_length=30)
    facts: str = Field(min_length=1, max_length=10000)
    interpretation: str = Field(min_length=1, max_length=10000)
    uncertainty: str = Field(max_length=10000)
    next_step: str = Field(min_length=1, max_length=5000)
    suggested_question: str = Field(min_length=1, max_length=5000)
    basis: Literal["source_text", "not_found"]
    coverage_basis: str = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_scope(self):
        for value in (self.title, self.facts, self.interpretation, self.next_step, self.suggested_question):
            if not value.strip():
                raise ValueError("Finding content must not be blank")
        if self.basis == "not_found" and not self.coverage_basis.strip():
            raise ValueError("Missing-term observations require a stated reviewed scope")
        if self.basis == "source_text" and self.coverage_basis:
            raise ValueError("Coverage basis belongs to missing-term observations")
        return self


class GeneratedReview(ReviewModel):
    outcome: Literal["review", "unsupported"]
    overview_items: list[GeneratedOverviewItem] = Field(max_length=30)
    findings: list[GeneratedFinding] = Field(max_length=100)
    limitations: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_outcome(self):
        if any(not item.strip() or len(item) > 2000 for item in self.limitations):
            raise ValueError("Invalid limitation")
        if self.outcome == "unsupported":
            if self.overview_items or self.findings or not self.limitations:
                raise ValueError("Unsupported input must not invent review content")
        elif not self.overview_items:
            raise ValueError("A review requires a referenced overview")
        if any(not item.text.strip() for item in self.overview_items):
            raise ValueError("Overview text must not be blank")
        return self


@dataclass(frozen=True)
class PreparedReview:
    generation: ReviewGeneration
    coverage: ReviewCoverage
    messages: list[dict[str, str]]
    response_format: dict
    evidence_by_id: dict[str, ReviewEvidence]  # scoped passage ID -> canonical source range
    timeout_seconds: int


@dataclass(frozen=True)
class ReviewGenerationResult:
    status: Literal["ready", "incomplete", "failed"]
    overview_items: list[ReviewOverviewItem]
    findings: list[ReviewFinding]
    coverage: ReviewCoverage
    generation: ReviewGeneration
    failure: ReviewFailure | None = None


def _source(document):
    try:
        extraction = SourceExtraction.model_validate(document["source_extraction"], strict=True)
        if (document.get("source_status") != "stored" or document.get("has_pdf_file") is not True
                or extraction.content_sha256 != document.get("source_sha256")
                or extraction.status != document.get("extraction_status")
                or extraction.status == "unavailable" or not document.get("source_revision_id")):
            raise ValueError("Source identity or state mismatch")
        if extraction.text != "\n".join(page.text for page in extraction.pages if page.text).strip():
            raise ValueError("Flattened text does not match pages")
        span_ids = set()
        extracted_pages = []
        for page in extraction.pages:
            if page.status != "extracted":
                if page.text.strip() or page.spans:
                    raise ValueError("Unavailable page contains source text")
                continue
            if not page.text.strip() or not page.spans:
                raise ValueError("Extracted page has no anchored text")
            extracted_pages.append(page.page_number)
            end = 0
            for span in page.spans:
                if span.id in span_ids or span.start < end or page.text[end:span.start].strip():
                    raise ValueError("Duplicate, overlapping or missing spans")
                span_ids.add(span.id)
                end = span.end
            if page.text[end:].strip():
                raise ValueError("Unanchored trailing text")
        if not extracted_pages or not extraction.text:
            raise ValueError("No usable text")
        expected_status = "complete" if len(extracted_pages) == extraction.page_count else "partial"
        if extraction.status != expected_status:
            raise ValueError("Extraction status does not describe page coverage")
        return extraction, extracted_pages
    except (KeyError, TypeError, ValueError, ValidationError):
        raise AIRequestError(
            "This source has no consistent, usable page extraction. Re-extract or import the PDF before starting a review.", 409,
        ) from None


def prepare_review(document: dict, brief: ReviewBrief, model_id: str) -> PreparedReview:
    """Validate the entire source and budget before allowing a paid request."""
    extraction, extracted_pages = _source(document)
    try:
        passages = build_review_passages(extraction, document["source_revision_id"])
        # The existing saved evidence contract retains exact first/last line IDs.
        # The provider sees only scoped passage IDs and cannot replace this text.
        evidence_by_id = {
            passage.id: ReviewEvidence(
                source_revision_id=document["source_revision_id"],
                span_id=passage.span_ids[0], end_span_id=passage.span_ids[-1],
                page_number=passage.page_number, quote=passage.text, label="Source passage",
            ) for passage in passages
        }
    except (ValueError, TypeError, ValidationError):
        raise AIRequestError("The source could not be represented as bounded exact passages. Nothing was sent.", 400) from None
    metadata = generation_metadata(model_id, "review")
    omitted = [page.page_number for page in extraction.pages if page.status != "extracted"]
    limitations = [SOURCE_LIMITATION]
    if omitted:
        limitations.append(
            "Pages without usable extraction were not supplied: " + ", ".join(map(str, omitted)) + "."
        )
    coverage = ReviewCoverage(
        page_count=extraction.page_count, extracted_pages=extracted_pages,
        omitted_pages=omitted, limitations=limitations,
    )
    payload = {
        "review_brief": brief.model_dump(),
        "source_revision_id": document["source_revision_id"],
        "coverage": coverage.model_dump(),
        "passage_version": PASSAGE_VERSION,
        "pages": [
            {"page_number": page.page_number,
             "passages": [{"passage_id": passage.id, "text": passage.text,
                           "continuation_before": passage.continuation_before,
                           "continuation_after": passage.continuation_after}
                          for passage in passages if passage.page_number == page.page_number]}
            for page in extraction.pages if page.status == "extracted"
        ],
    }
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
    response_format = {"type": "json_schema", "json_schema": {
        "name": "source_review", "strict": True, "schema": GeneratedReview.model_json_schema(),
    }}
    try:
        # Count the schema as well as all source text, brief and instructions.
        estimated = sum(get_token_count(item["content"], model_id) + 8 for item in messages) + 16
        estimated += get_token_count(json.dumps(response_format, separators=(",", ":")), model_id)
        budget = calculate_token_budget(model_id, metadata["max_completion_tokens"])
        timeout = min(_positive_env_integer("AI_REVIEW_TIMEOUT_SECONDS", DEFAULT_REVIEW_TIMEOUT_SECONDS),
                      MAX_REVIEW_TIMEOUT_SECONDS)
    except (ValueError, ImportError, OSError):
        raise AIRequestError("Review input limits or tokenizer could not be checked. Check the local AI configuration.", 503) from None
    if estimated > budget:
        raise AIRequestError(
            "The full extracted source, review brief and output schema exceed the configured AI input budget. Nothing was truncated or sent. Use a smaller source or adjust the budget deliberately.", 400,
        )
    return PreparedReview(
        generation=ReviewGeneration(**metadata, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                                    extraction_version=extraction.extraction_version, estimated_input_tokens=estimated),
        coverage=coverage, messages=messages, response_format=response_format,
        evidence_by_id=evidence_by_id, timeout_seconds=timeout,
    )


def _usage(response):
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    try:
        return ReviewUsage(**{key: getattr(usage, key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
    except (AttributeError, ValidationError):
        return None


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate output key")
        result[key] = value
    return result


class _EvidenceMismatch(ValueError):
    """An exact-reference failure, without source or provider text in the error."""


class _ResolvedOutputLimit(ValueError):
    """Expanded source evidence exceeded the bounded publishable result size."""


def _resolve_evidence(evidence, prepared):
    resolved = []
    seen = set()
    for candidate in evidence:
        original = prepared.evidence_by_id.get(candidate.passage_id)
        if original is None or not candidate.label.strip() or candidate.passage_id in seen:
            raise _EvidenceMismatch("Evidence did not identify a unique source passage")
        seen.add(candidate.passage_id)
        # Never persist provider page/quote values as the authority: none are accepted.
        resolved.append(original.model_copy(update={"label": candidate.label}))
    return resolved


async def generate_review(prepared: PreparedReview, client) -> ReviewGenerationResult:
    """Perform one call; publish no normal findings from any invalid output."""
    started = time.monotonic()
    generation = prepared.generation.model_copy(deep=True)
    coverage = prepared.coverage.model_copy(deep=True)

    def failed(code, message, status="incomplete"):
        generation.duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return ReviewGenerationResult(status, [], [], coverage, generation, ReviewFailure(code=code, message=message))

    try:
        # Disable the SDK's own network/status retries, not merely app retries.
        bounded_client = client.with_options(max_retries=0, timeout=prepared.timeout_seconds)
        response = await asyncio.wait_for(create_chat_completion(
            bounded_client, model=generation.model_id, messages=prepared.messages,
            max_completion_tokens=generation.max_completion_tokens,
            reasoning_effort=generation.reasoning_effort,
            response_format=prepared.response_format, validate_output=False,
        ), timeout=prepared.timeout_seconds)
    except asyncio.TimeoutError:
        return failed("REVIEW_TIMEOUT", "The review timed out. Provider usage is unknown; no automatic retry was made.", "failed")
    except AIRequestError as error:
        return failed("PROVIDER_REQUEST_FAILED", error.public_message, "failed")
    except Exception:
        return failed("REVIEW_REQUEST_FAILED", "The review request did not complete. Provider usage may be unknown; no automatic retry was made.", "failed")

    generation.usage = _usage(response)
    choices = getattr(response, "choices", None)
    if not choices:
        return failed("EMPTY_REVIEW_RESPONSE", "The model returned no review output.")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if getattr(message, "refusal", None) or getattr(choice, "finish_reason", None) == "content_filter":
        return failed("REVIEW_REFUSED", "The model declined the review. No generated findings were published.")
    if getattr(choice, "finish_reason", None) == "length":
        return failed("REVIEW_OUTPUT_LIMIT", "The model reached its completion limit. No partial findings were published; no automatic retry was made.")
    content = getattr(message, "content", None)
    if (getattr(choice, "finish_reason", None) != "stop" or not isinstance(content, str)
            or not content.strip() or len(content) > MAX_RESPONSE_CHARACTERS):
        return failed("INCOMPLETE_REVIEW_RESPONSE", "The model returned an incomplete or empty review. No findings were published.")
    try:
        parsed = GeneratedReview.model_validate(json.loads(content, object_pairs_hook=_unique_keys))
    except (ValueError, TypeError, ValidationError, RecursionError):
        return failed("INVALID_REVIEW_SHAPE", "The generated review did not satisfy the required output structure. No generated findings were published.")
    try:
        resolved_bytes = len(b'{"overview_items":[],"findings":[]}')

        def append_bounded(items, item):
            nonlocal resolved_bytes
            # Check each resolved item immediately. Do not expand the remaining
            # references or serialize an enormous whole result before rejecting.
            resolved_bytes += len(item.model_dump_json().encode("utf-8")) + bool(items)
            if resolved_bytes > MAX_RESOLVED_REVIEW_BYTES:
                raise _ResolvedOutputLimit()
            items.append(item)

        overview = []
        findings = []
        for item in parsed.overview_items:
            append_bounded(overview, ReviewOverviewItem(
                text=item.text, evidence=_resolve_evidence(item.evidence, prepared),
            ))
        for index, item in enumerate(parsed.findings):
            append_bounded(findings, ReviewFinding(
                **item.model_dump(exclude={"evidence"}), id=f"finding_{index + 1}",
                evidence=_resolve_evidence(item.evidence, prepared),
            ))
    except _ResolvedOutputLimit:
        return failed("REVIEW_RESOLVED_OUTPUT_LIMIT", "The review and its complete source passages exceeded the safe result-size limit. No generated findings were published; no automatic retry was made.")
    except _EvidenceMismatch:
        return failed("INVALID_REVIEW_EVIDENCE", "A generated reference did not identify a unique supplied source passage. No generated findings were published.")
    except (ValueError, TypeError, ValidationError):
        return failed("INVALID_REVIEW_SHAPE", "The generated review did not satisfy the required output structure. No generated findings were published.")
    coverage.limitations = list(dict.fromkeys([*coverage.limitations, *parsed.limitations]))
    if parsed.outcome == "unsupported":
        return failed("UNSUPPORTED_REVIEW_INPUT", "The model could not review this source as an agreement. See the reported limitations.")
    generation.duration_ms = max(0, int((time.monotonic() - started) * 1000))
    if coverage.omitted_pages:
        return ReviewGenerationResult("incomplete", overview, findings, coverage, generation, ReviewFailure(
            code="PARTIAL_SOURCE", message="Only successfully extracted pages were reviewed. Some PDF pages were not supplied.",
        ))
    return ReviewGenerationResult("ready", overview, findings, coverage, generation)
