"""One bounded, development-only diagnostic call; never a product review stage.

The model reports concerns, not repaired findings or a verification verdict.
Only structural and exact-reference validation happens here. A completed report
does not establish that the checker found every problem or avoided false alarms.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError

from clauseiq_types.review import ReviewFailure, ReviewUsage
from services.ai.generation import AIRequestError, create_chat_completion

from .contract import CheckResult, DiagnosticReport, MAX_DIAGNOSTIC_BYTES, validate_diagnostics

if TYPE_CHECKING:
    from .contract import PreparedCheck


MAX_RESPONSE_BYTES = MAX_DIAGNOSTIC_BYTES
MAX_TIMEOUT_SECONDS = 180


def _usage(response):
    """Retain known provider usage, even when its diagnostic output is unusable."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    try:
        return ReviewUsage(**{
            key: getattr(usage, key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        })
    except (AttributeError, TypeError, ValidationError):
        return None


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate diagnostic key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-JSON numeric value")


async def check_review(prepared: PreparedCheck, client) -> CheckResult:
    """One explicit request, zero retries, and no candidate or database writes."""
    started = time.monotonic()
    generation = prepared.generation.model_copy(deep=True)
    binding = prepared.binding.model_copy(deep=True)

    def result(status, diagnostics=None, code=None, message=None):
        generation.duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return CheckResult(
            status=status, diagnostics=diagnostics, binding=binding,
            generation=generation,
            failure=ReviewFailure(code=code, message=message) if code else None,
        )

    timeout = prepared.timeout_seconds
    if type(timeout) is not int or timeout <= 0:
        return result(
            "failed", code="INVALID_CHECK_TIMEOUT",
            message="The check timeout is invalid. Nothing was sent.",
        )
    timeout = min(timeout, MAX_TIMEOUT_SECONDS)
    try:
        bounded_client = client.with_options(max_retries=0, timeout=timeout)
        response = await asyncio.wait_for(create_chat_completion(
            bounded_client, model=generation.model_id, messages=prepared.messages,
            max_completion_tokens=generation.max_completion_tokens,
            reasoning_effort=generation.reasoning_effort,
            response_format=prepared.response_format, validate_output=False,
        ), timeout=timeout)
    except asyncio.TimeoutError:
        return result(
            "failed", code="CHECK_TIMEOUT",
            message="The check timed out. Provider usage is unknown; no automatic retry was made.",
        )
    except AIRequestError as error:
        return result("failed", code="CHECK_PROVIDER_REQUEST_FAILED", message=error.public_message)
    except Exception:
        return result(
            "failed", code="CHECK_REQUEST_FAILED",
            message="The check request did not complete. Provider usage may be unknown; no automatic retry was made.",
        )

    generation.usage = _usage(response)
    choices = getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        return result(
            "incomplete", code="EMPTY_CHECK_RESPONSE",
            message="The model did not return one diagnostic response. No diagnostics were accepted.",
        )
    choice = choices[0]
    message = getattr(choice, "message", None)
    finish = getattr(choice, "finish_reason", None)
    if getattr(message, "refusal", None) or finish == "content_filter":
        return result(
            "incomplete", code="CHECK_REFUSED",
            message="The model declined the check. No diagnostics were accepted.",
        )
    if finish == "length":
        return result(
            "incomplete", code="CHECK_OUTPUT_LIMIT",
            message="The check reached its completion limit. No partial diagnostics were accepted; no automatic retry was made.",
        )
    content = getattr(message, "content", None)
    if finish != "stop" or not isinstance(content, str) or not content.strip():
        return result(
            "incomplete", code="INCOMPLETE_CHECK_RESPONSE",
            message="The model returned an unfinished or empty check. No diagnostics were accepted.",
        )
    try:
        if len(content) > MAX_RESPONSE_BYTES or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return result(
                "incomplete", code="CHECK_RESPONSE_SIZE_LIMIT",
                message="The diagnostic response exceeded its safe byte limit. No diagnostics were accepted.",
            )
        parsed = DiagnosticReport.model_validate(json.loads(
            content, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant,
        ), strict=True)
    except (ValueError, TypeError, ValidationError, RecursionError):
        return result(
            "incomplete", code="INVALID_CHECK_SHAPE",
            message="The diagnostic response did not satisfy its required structure. No diagnostics were accepted.",
        )
    try:
        validate_diagnostics(prepared, parsed)
    except (ValueError, TypeError, ValidationError):
        return result(
            "incomplete", code="INVALID_CHECK_REFERENCES",
            message="The check did not exactly cover the supplied targets or use valid source and text references. No diagnostics were accepted.",
        )
    if not prepared.source_complete:
        return result(
            "incomplete", diagnostics=parsed, code="PARTIAL_CHECK_SOURCE",
            message="Some source pages were unavailable. These diagnostics concern only the supplied text; the check is incomplete.",
        )
    if (any(target.status == "not_assessable" for target in parsed.target_checks)
            or parsed.priority_assessment.status == "not_assessable"):
        return result(
            "incomplete", diagnostics=parsed, code="CHECK_NOT_ASSESSABLE",
            message="The model could not assess every required target or the supplied priorities. Available diagnostics do not establish a completed check.",
        )
    return result("completed", diagnostics=parsed)
