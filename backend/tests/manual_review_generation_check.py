"""One opt-in, cost-bounded Terra call against an allowlisted synthetic PDF.

Not part of Pytest. Requires separate paid-call approval. Reads the saved key via
the normal credential service; never prints it or changes app data/Settings.
The exclusive local report reserves the conservative maximum before dispatch.
Reusing its name refuses another call, including after an interrupted process.
"""
import argparse
import asyncio
import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "shared"))

from ai_models.models import AIModelConfig
from database.factory import DatabaseFactory
from clauseiq_types.review import ReviewBrief
from services.ai.client_manager import workspace_openai_client
from services.ai import review_generation
from services.ai.review_generation import generate_review, prepare_review
from services.ai.text_extractor import TextExtractor
from services.workspace_service import get_workspace_service
from tests.review_evaluation_cases import CASE_IDS, DEFAULT_CASE, load_case, validate_case_source


EVALUATION_MODEL = "gpt-5.6-terra"
REQUEST_FRAMING_TOKEN_MARGIN = 4096


def request_cost_ceiling(prepared, spec):
    """Bound this complete text-only request, not an unrelated full context window.

    Byte-level BPE cannot use more text tokens than UTF-8 bytes. Serializing all
    request fields also covers schema and message content; an additional 4096
    tokens reserves provider framing overhead. This is a conservative local
    bound for this fixed request shape, not a billing invoice or universal bound
    for images, tools, arbitrary endpoints or future request serialization.
    """
    generation = prepared.generation
    if generation.model_id != EVALUATION_MODEL:
        raise ValueError("The manual evaluation supports only its fixed Terra model")
    if (not isinstance(prepared.messages, list) or len(prepared.messages) != 2
            or [message.get("role") if isinstance(message, dict) else None for message in prepared.messages] != ["system", "user"]
            or any(set(message) != {"role", "content"} or not isinstance(message["content"], str)
                   for message in prepared.messages)):
        raise ValueError("Only the fixed two-message text request can use this spending bound")
    response_format = prepared.response_format
    if (not isinstance(response_format, dict) or set(response_format) != {"type", "json_schema"}
            or response_format.get("type") != "json_schema"
            or not isinstance(response_format["json_schema"], dict)
            or set(response_format["json_schema"]) != {"name", "strict", "schema"}
            or not isinstance(response_format["json_schema"]["name"], str)
            or response_format["json_schema"]["strict"] is not True
            or not isinstance(response_format["json_schema"]["schema"], dict)):
        raise ValueError("Only the fixed strict JSON response schema can use this spending bound")
    if (type(generation.max_completion_tokens) is not int or generation.max_completion_tokens <= 0
            or not isinstance(generation.reasoning_effort, str)
            or type(generation.estimated_input_tokens) is not int or generation.estimated_input_tokens < 0):
        raise ValueError("Invalid generation limits for the spending bound")
    payload = {
        "model": generation.model_id, "messages": prepared.messages,
        "response_format": response_format, "reasoning_effort": generation.reasoning_effort,
        "max_completion_tokens": generation.max_completion_tokens, "store": False,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    request_bytes = len(serialized.encode("utf-8"))
    byte_ceiling = request_bytes + REQUEST_FRAMING_TOKEN_MARGIN
    input_bound = max(generation.estimated_input_tokens, byte_ceiling)
    if input_bound + generation.max_completion_tokens > spec.context_window:
        raise ValueError("The conservative request bound exceeds the model context; no call is allowed")
    long_context = input_bound > 272_000
    ceiling = (input_bound * spec.input_price_per_million * 1.25 * (2 if long_context else 1) +
               generation.max_completion_tokens * spec.output_price_per_million * (1.5 if long_context else 1)) / 1_000_000
    return {
        "reserved_ceiling_usd": ceiling, "serialized_request_bytes": request_bytes,
        "input_token_ceiling": input_bound, "byte_input_token_ceiling": byte_ceiling,
        "input_bound_basis": "max(local token estimate, complete text request UTF-8 bytes + 4096 framing tokens)",
        "cache_write_multiplier": 1.25, "long_context_pricing": long_context,
    }, json.loads(serialized)


async def run_check(cap_usd: float, report_name: str, previous_reserved_usd: float = 0,
                    case_id: str = DEFAULT_CASE):
    if (not math.isfinite(cap_usd) or cap_usd <= 0
            or not math.isfinite(previous_reserved_usd) or not 0 <= previous_reserved_usd <= cap_usd):
        raise ValueError("Use a finite positive approved cap and a finite nonnegative prior reservation within it")
    if case_id not in CASE_IDS:
        raise ValueError("Choose an allowlisted synthetic evaluation case")
    if (not report_name or len(report_name) > 80
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in report_name)):
        raise ValueError("Use a short lowercase report name with letters, digits, hyphens or underscores")
    logging.disable(logging.CRITICAL)
    report_dir = ROOT / ".local-only" / "review-evaluations"
    report_path = report_dir / f"{report_name}.json"
    if report_path.exists():
        print("This evaluation report already exists; no call was made. Inspect it before authorizing another evaluation.")
        return False
    fixture = load_case(BACKEND, case_id)
    fixture_path = ROOT / "tests" / "fixtures" / "pdfs" / fixture["fixture"]
    extraction = await TextExtractor().extract_source(fixture_path.read_bytes(), fixture_path.name)
    validate_case_source(fixture, extraction)
    document = {
        "source_revision_id": "synthetic-evaluation-source", "source_sha256": extraction.content_sha256,
        "source_extraction": extraction.model_dump(), "source_status": "stored",
        "has_pdf_file": True, "extraction_status": extraction.status,
    }
    model_id = EVALUATION_MODEL
    prepared = prepare_review(document, ReviewBrief.model_validate(fixture["context"]), model_id)
    spec = AIModelConfig.get_model_by_id(model_id)
    # Recheck official Terra prices before reuse. Prior ambiguous attempts retain
    # their reservation; never assume a timeout or invalid answer cost nothing.
    cost_bound, expected_payload = request_cost_ceiling(prepared, spec)
    ceiling = cost_bound["reserved_ceiling_usd"]
    if previous_reserved_usd + ceiling > cap_usd:
        print("Prior reservations plus this conservative call ceiling exceed the approved cap; no call was made.")
        return False
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id, "fixture": fixture_path.name,
        "source_sha256": extraction.content_sha256,
        "evaluation_case": {
            "case_id": case_id, "case_version": fixture["case_version"],
            "criteria_reference": f"backend/fixtures/review_evaluations/{case_id}.json",
            "case_definition_sha256": hashlib.sha256(json.dumps(
                fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "criteria_ids": [criterion["id"] for criterion in fixture["criteria"]],
            "semantic_assessment": "not_assessed_requires_source_review",
        },
        "approved_cap_usd": cap_usd, **cost_bound,
        "previous_reserved_usd": previous_reserved_usd,
        "total_reserved_ceiling_usd": previous_reserved_usd + ceiling,
        "pricing_verified_on": spec.pricing_verified_on,
        "estimated_input_tokens": prepared.generation.estimated_input_tokens,
        "max_completion_tokens": prepared.generation.max_completion_tokens,
        "status": "reserved_provider_outcome_unknown", "result": None,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    # Reserve before any potential provider dispatch. Never replace a prior run.
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    try:
        api_key = await get_workspace_service().get_api_key()
        if not api_key:
            report["status"] = "no_saved_key_no_call"
            return False
        async with workspace_openai_client(api_key) as client:
            if str(client.base_url) != "https://api.openai.com/v1/":
                report["status"] = "nonstandard_provider_endpoint_no_call"
                return False
            # Diagnostic evidence is restricted to this allowlisted synthetic fixture
            # and ignored report. Never capture headers, credentials, raw error
            # bodies or request objects, and never enable this in app generation.
            original_completion = review_generation.create_chat_completion
            dispatch_count = 0

            async def capture_synthetic_output(*args, **kwargs):
                nonlocal dispatch_count
                # Recheck the exact bounded shape immediately before dispatch.
                # Reject any second request, additional option, tool or mutation.
                expected_kwargs = {key: value for key, value in expected_payload.items() if key != "store"}
                expected_kwargs["validate_output"] = False
                if len(args) != 1 or kwargs != expected_kwargs or dispatch_count:
                    raise ValueError("The evaluation request changed or attempted another dispatch")
                dispatch_count += 1
                response = await original_completion(*args, **kwargs)
                choices = getattr(response, "choices", None)
                if choices:
                    content = getattr(getattr(choices[0], "message", None), "content", None)
                    if isinstance(content, str) and len(content) <= 1_000_000:
                        report["synthetic_provider_output"] = content
                return response

            with patch.object(review_generation, "create_chat_completion", capture_synthetic_output):
                result = await generate_review(prepared, client)
        report["status"] = result.status
        report["result"] = {
            "overview_items": [item.model_dump() for item in result.overview_items],
            "findings": [item.model_dump() for item in result.findings],
            "coverage": result.coverage.model_dump(),
            "generation": result.generation.model_dump(),
            "failure": result.failure.model_dump() if result.failure else None,
        }
        usage = result.generation.usage
        if usage:
            # Base-rate estimate; this is not an invoice and excludes cache-write
            # premiums. The larger reserved ceiling remains the budget guard.
            long_context = usage.prompt_tokens > 272_000
            report["usage_based_cost_estimate_usd"] = (
                usage.prompt_tokens * spec.input_price_per_million * (2 if long_context else 1) +
                usage.completion_tokens * spec.output_price_per_million * (1.5 if long_context else 1)
            ) / 1_000_000
        return result.status == "ready"
    except Exception as error:
        report["status"] = "evaluation_interrupted_outcome_unknown"
        report["error_type"] = type(error).__name__
        return False
    finally:
        await DatabaseFactory.close()
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "model_id", "status", "evaluation_case", "reserved_ceiling_usd", "estimated_input_tokens", "max_completion_tokens",
            "previous_reserved_usd", "total_reserved_ceiling_usd", "input_token_ceiling", "input_bound_basis",
        )} | {"usage_based_cost_estimate_usd": report.get("usage_based_cost_estimate_usd"),
              "report": str(report_path.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-paid", action="store_true")
    parser.add_argument("--cap-usd", type=float, required=True)
    parser.add_argument("--report-name", required=True)
    parser.add_argument("--case", choices=CASE_IDS, default=DEFAULT_CASE,
                        help="Reviewed synthetic source and scenario; criteria never enter the model prompt")
    parser.add_argument("--previous-reserved-usd", type=float, default=0,
                        help="Prior confirmed costs or retained ceilings within this same approved total budget")
    args = parser.parse_args()
    if not args.run_paid or not math.isfinite(args.cap_usd) or args.cap_usd <= 0:
        parser.error("Separate approval, --run-paid and a finite positive approved cap are required.")
    if not math.isfinite(args.previous_reserved_usd) or not 0 <= args.previous_reserved_usd <= args.cap_usd:
        parser.error("Prior reserved spending must be finite, nonnegative and within the approved cap.")
    if not args.report_name or len(args.report_name) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.report_name):
        parser.error("Use a short lowercase report name with only letters, digits, hyphens or underscores.")
    raise SystemExit(0 if asyncio.run(run_check(args.cap_usd, args.report_name, args.previous_reserved_usd, args.case)) else 1)
