"""One explicit, source-scoped follow-up call; no storage, retries or fallback."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from clauseiq_types.review import (
    ReviewAskAnswerItem, ReviewAskTurn, ReviewCoverage, ReviewEvidence,
    ReviewFailure, ReviewFinding, ReviewGeneration, ReviewModel, ReviewRun,
)
from .generation import AIRequestError, create_chat_completion, generation_metadata
from .ask_citations import bind_inline_citations
from .review_ask_prompt import ASK_SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION
from .review_generation import (
    SOURCE_LIMITATION, GeneratedEvidence, _EvidenceMismatch, _resolve_evidence,
    _source, _unique_keys, _usage,
)
from .review_passages import PASSAGE_VERSION, ReviewPassage, build_review_passages
from .token_utils import _positive_env_integer, calculate_token_budget, get_token_count

MAX_HISTORY_TURNS = 6
MAX_QUESTION_CHARACTERS = 5_000
MAX_RESPONSE_CHARACTERS = 250_000
MAX_RESOLVED_ASK_BYTES = 256 * 1024
DEFAULT_ASK_TIMEOUT_SECONDS = 120
MAX_ASK_TIMEOUT_SECONDS = 180


class GeneratedAskAnswerItem(ReviewModel):
    text: str = Field(min_length=1, max_length=5000)
    evidence: list[GeneratedEvidence] = Field(max_length=10)


class GeneratedAsk(ReviewModel):
    outcome: Literal["answer", "unsupported"]
    answer: list[GeneratedAskAnswerItem] = Field(max_length=20)
    limitations: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_content(self):
        if any(not item.text.strip() for item in self.answer) or any(not item.strip() for item in self.limitations):
            raise ValueError("Answer text and limitations must not be blank")
        if self.outcome == "answer" and not self.answer:
            raise ValueError("An answer requires at least one item")
        if self.outcome == "unsupported" and (self.answer or not self.limitations):
            raise ValueError("Unsupported requests require a limitation and no answer")
        return self


@dataclass(frozen=True)
class PreparedAsk:
    generation: ReviewGeneration
    coverage: ReviewCoverage
    messages: list[dict[str, str]]
    response_format: dict
    passages: list[ReviewPassage]
    evidence_by_id: dict[str, ReviewEvidence]
    timeout_seconds: int


@dataclass(frozen=True)
class AskGenerationResult:
    status: Literal["ready", "incomplete", "failed"]
    answer: list[ReviewAskAnswerItem]
    limitations: list[str]
    generation: ReviewGeneration
    coverage: ReviewCoverage
    failure: ReviewFailure | None = None


def _validate_scope(document, run, finding, question, history):
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARACTERS:
        raise AIRequestError("Enter a nonblank question of at most 5000 characters. Nothing was sent.", 400)
    matched = [item for item in run.findings if item.id == finding.id]
    if (run.source_revision_id != document.get("source_revision_id")
            or run.status not in ("ready", "incomplete")
            or len(matched) != 1 or matched[0] != finding):
        raise AIRequestError("This finding does not belong to the selected completed source review. Reload the workspace before asking.", 409)
    if len(history) > MAX_HISTORY_TURNS:
        raise AIRequestError("Too many earlier turns were selected. Nothing was truncated or sent.", 400)
    seen = set()
    for turn in history:
        if (turn.id in seen or turn.run_id != run.id or turn.finding_id != finding.id
                or turn.source_revision_id != run.source_revision_id
                or turn.status not in ("ready", "incomplete") or not turn.answer):
            raise AIRequestError("The selected conversation does not match this finding and source. Nothing was sent.", 409)
        seen.add(turn.id)


def prepare_ask(
    document: dict, run: ReviewRun, finding: ReviewFinding, question: str,
    model_id: str, history: list[ReviewAskTurn], reasoning_effort: str | None = None,
) -> PreparedAsk:
    """Prepare all extracted text, immutable context and bounded selected history.

    The caller selects completed history turns explicitly and records their IDs.
    This function never drops source passages or silently trims a selected turn.
    The existing chat completion cap includes both reasoning and visible output.
    """
    _validate_scope(document, run, finding, question, history)
    extraction, extracted_pages = _source(document)
    try:
        passages = build_review_passages(extraction, document["source_revision_id"])
        evidence_by_id = {
            passage.id: ReviewEvidence(
                source_revision_id=document["source_revision_id"],
                span_id=passage.span_ids[0], end_span_id=passage.span_ids[-1],
                page_number=passage.page_number, quote=passage.text, label="Source passage",
            ) for passage in passages
        }
    except (ValueError, TypeError, ValidationError):
        raise AIRequestError("The source could not be represented as bounded exact passages. Nothing was sent.", 400) from None
    metadata = generation_metadata(model_id, "chat", reasoning_effort)
    omitted = [page.page_number for page in extraction.pages if page.status != "extracted"]
    limitations = [SOURCE_LIMITATION]
    if omitted:
        limitations.append("Pages without usable extraction were not supplied: " + ", ".join(map(str, omitted)) + ".")
    coverage = ReviewCoverage(
        page_count=extraction.page_count, extracted_pages=extracted_pages,
        omitted_pages=omitted, limitations=limitations,
    )
    payload = {
        "original_review_context": run.context.model_dump(),
        "selected_finding_untrusted": finding.model_dump(),
        "conversation_history_untrusted": [
            {"turn_id": turn.id, "question": turn.question,
             "answer": [item.model_dump(exclude={"inline_citations"}) for item in turn.answer],
             "limitations": turn.limitations}
            for turn in history
        ],
        "question": question,
        "source": {
            "source_revision_id": document["source_revision_id"],
            "coverage": coverage.model_dump(), "passage_version": PASSAGE_VERSION,
            "pages": [
                {"page_number": page.page_number, "passages": [
                    {"passage_id": passage.id, "text": passage.text,
                     "continuation_before": passage.continuation_before,
                     "continuation_after": passage.continuation_after}
                    for passage in passages if passage.page_number == page.page_number
                ]} for page in extraction.pages if page.status == "extracted"
            ],
        },
    }
    messages = [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
    response_format = {"type": "json_schema", "json_schema": {
        "name": "source_review_ask", "strict": True, "schema": GeneratedAsk.model_json_schema(),
    }}
    try:
        estimated = sum(get_token_count(item["content"], model_id) + 8 for item in messages) + 16
        estimated += get_token_count(json.dumps(response_format, separators=(",", ":")), model_id)
        budget = calculate_token_budget(model_id, metadata["max_completion_tokens"])
        timeout = min(_positive_env_integer("AI_REVIEW_ASK_TIMEOUT_SECONDS", DEFAULT_ASK_TIMEOUT_SECONDS),
                      MAX_ASK_TIMEOUT_SECONDS)
    except (ValueError, ImportError, OSError):
        raise AIRequestError("Ask input limits or tokenizer could not be checked. Check the local AI configuration.", 503) from None
    if estimated > budget:
        raise AIRequestError(
            "The full extracted source, finding, selected history, question and output schema exceed the configured AI input budget. Nothing was truncated or sent. Exclude earlier turns or adjust the budget deliberately.", 400,
        )
    return PreparedAsk(
        generation=ReviewGeneration(**metadata, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
                                    extraction_version=extraction.extraction_version, estimated_input_tokens=estimated),
        coverage=coverage, messages=messages, response_format=response_format,
        passages=passages, evidence_by_id=evidence_by_id, timeout_seconds=timeout,
    )


async def generate_ask(prepared: PreparedAsk, client) -> AskGenerationResult:
    """Publish a complete validated answer or safe failure, never a partial blob."""
    started = time.monotonic()
    generation = prepared.generation.model_copy(deep=True)
    coverage = prepared.coverage.model_copy(deep=True)
    limitations = []

    def failed(code, message, status="incomplete"):
        generation.duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return AskGenerationResult(status, [], limitations, generation, coverage, ReviewFailure(code=code, message=message))

    try:
        bounded_client = client.with_options(max_retries=0, timeout=prepared.timeout_seconds)
        response = await asyncio.wait_for(create_chat_completion(
            bounded_client, model=generation.model_id, messages=prepared.messages,
            max_completion_tokens=generation.max_completion_tokens,
            reasoning_effort=generation.reasoning_effort,
            response_format=prepared.response_format, validate_output=False,
        ), timeout=prepared.timeout_seconds)
    except asyncio.TimeoutError:
        return failed("ASK_TIMEOUT", "The answer timed out. Provider usage is unknown; no automatic retry was made.", "failed")
    except AIRequestError as error:
        return failed("PROVIDER_REQUEST_FAILED", error.public_message, "failed")
    except Exception:
        return failed("ASK_REQUEST_FAILED", "The answer request did not complete. Provider usage may be unknown; no automatic retry was made.", "failed")

    generation.usage = _usage(response)
    choices = getattr(response, "choices", None)
    if not choices:
        return failed("EMPTY_ASK_RESPONSE", "The model returned no answer output.")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if getattr(message, "refusal", None) or getattr(choice, "finish_reason", None) == "content_filter":
        return failed("ASK_REFUSED", "The model declined the question. No generated answer was published.")
    if getattr(choice, "finish_reason", None) == "length":
        return failed("ASK_OUTPUT_LIMIT", "The model reached its completion limit. No partial answer was published; no automatic retry was made.")
    content = getattr(message, "content", None)
    if (getattr(choice, "finish_reason", None) != "stop" or not isinstance(content, str)
            or not content.strip() or len(content) > MAX_RESPONSE_CHARACTERS):
        return failed("INCOMPLETE_ASK_RESPONSE", "The model returned an incomplete or empty answer. No answer was published.")
    try:
        parsed = GeneratedAsk.model_validate(json.loads(content, object_pairs_hook=_unique_keys))
    except (ValueError, TypeError, ValidationError, RecursionError):
        return failed("INVALID_ASK_SHAPE", "The generated answer did not satisfy the required output structure. No answer was published.")
    try:
        resolved_bytes = len(json.dumps({"answer": [], "limitations": parsed.limitations},
                                        ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        answer = []
        for item in parsed.answer:
            # Resolve against this exact request's inventory before retaining any
            # association. Neither prose nor the frontend can supply quote/page data.
            evidence = _resolve_evidence(item.evidence, prepared)
            resolved = ReviewAskAnswerItem(
                text=item.text, evidence=evidence,
                inline_citations=bind_inline_citations(item.text, [entry.passage_id for entry in item.evidence]),
            )
            resolved_bytes += len(resolved.model_dump_json().encode("utf-8")) + bool(answer)
            if resolved_bytes > MAX_RESOLVED_ASK_BYTES:
                return failed("ASK_RESOLVED_OUTPUT_LIMIT", "The answer and its complete source passages exceeded the safe result-size limit. No answer was published; no automatic retry was made.")
            answer.append(resolved)
    except _EvidenceMismatch:
        return failed("INVALID_ASK_EVIDENCE", "A generated reference did not identify a unique supplied source passage. No answer was published.")
    except (ValueError, TypeError, ValidationError):
        return failed("INVALID_ASK_SHAPE", "The generated answer did not satisfy the required output structure. No answer was published.")
    limitations = list(dict.fromkeys(parsed.limitations))
    if parsed.outcome == "unsupported":
        return failed("UNSUPPORTED_ASK_INPUT", "The model could not answer this request within the source-review scope. See the reported limitations.")
    generation.duration_ms = max(0, int((time.monotonic() - started) * 1000))
    if coverage.omitted_pages:
        return AskGenerationResult("incomplete", answer, limitations, generation, coverage, ReviewFailure(
            code="PARTIAL_SOURCE", message="Only successfully extracted pages were supplied for this answer. Some PDF pages were not supplied.",
        ))
    return AskGenerationResult("ready", answer, limitations, generation, coverage)
