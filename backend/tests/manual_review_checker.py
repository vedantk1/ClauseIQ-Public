"""Development-only checker harness for fixed, reviewed synthetic cases.

Dry-run is the default: validate/prepare the case and print bounded metadata,
without opening credentials, MongoDB or a provider, or writing a report. An
explicit --run-paid requires a separately approved finite budget and an unused
report name. It reserves one complete Terra request before reading the saved
key. There is no automatic retry, repair, regeneration or application write.
"""
import argparse
import asyncio
import json
import logging
import math
import os
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
from evaluations.review_checker import engine
from evaluations.review_checker.cases import CASE_IDS, load_checker_case
from evaluations.review_checker.preparation import prepare_check
from services.ai.client_manager import workspace_openai_client
from services.workspace_service import get_workspace_service
from tests.manual_review_generation_check import request_cost_ceiling

EVALUATION_MODEL = "gpt-5.6-terra"
DEFAULT_CASE = CASE_IDS[0]
ASSESSMENT_PENDING = "not_assessed_requires_source_review"


def _validate_budget(cap_usd, previous_reserved_usd):
    if (cap_usd is None or not math.isfinite(cap_usd) or cap_usd <= 0
            or not math.isfinite(previous_reserved_usd)
            or not 0 <= previous_reserved_usd <= cap_usd):
        raise ValueError("Use a finite positive approved cap and a finite nonnegative prior reservation within it")


def _report_destination(report_name):
    if (not isinstance(report_name, str) or not report_name or len(report_name) > 80
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in report_name)):
        raise ValueError("Use a short lowercase report name with letters, digits, hyphens or underscores")
    local_dir = ROOT / ".local-only"
    report_dir = local_dir / "review-checks"
    report_path = report_dir / f"{report_name}.json"
    if any(path.is_symlink() for path in (local_dir, report_dir, report_path)):
        raise ValueError("Checker reports must not use symlinks")
    if any(path.exists() and not path.is_dir() for path in (local_dir, report_dir)):
        raise ValueError("Checker reports require an ignored local directory")
    return report_path


def _write_report(stream, report):
    # Keep the exclusive file descriptor throughout the attempt. Do not reopen
    # a path that could have been replaced by another file or a symlink.
    stream.seek(0)
    json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def _summary(report, report_path=None):
    summary = {key: report[key] for key in (
        "status", "model_id", "evaluation_case", "binding", "estimated_input_tokens",
        "max_completion_tokens", "reserved_ceiling_usd", "input_token_ceiling",
    )}
    if report_path is not None:
        summary.update({
            "report": str(report_path.relative_to(ROOT)),
            "provider_dispatches": report.get("provider_dispatches", 0),
            "previous_reserved_usd": report["previous_reserved_usd"],
            "total_reserved_ceiling_usd": report["total_reserved_ceiling_usd"],
            "usage_based_cost_estimate_usd": report.get("usage_based_cost_estimate_usd"),
        })
    print(json.dumps(summary, indent=2, allow_nan=False))


async def run_check(case_id=DEFAULT_CASE, *, run_paid=False, cap_usd=None,
                    report_name=None, previous_reserved_usd=0):
    """Prepare one allowlisted case, optionally reserve and dispatch it once.

    Return True for a successful dry run or a structurally completed checker.
    A completed response is never a semantic pass or a verified review.
    """
    if case_id not in CASE_IDS:
        raise ValueError("Choose an allowlisted synthetic checker case")
    report_path = None
    if run_paid:
        _validate_budget(cap_usd, previous_reserved_usd)
        report_path = _report_destination(report_name)
        if report_path.exists():
            print("This checker report already exists; no call was made. Inspect it before authorizing another attempt.")
            return False

    case = await load_checker_case(case_id)
    prepared = prepare_check(case.document, case.candidate, model_id=EVALUATION_MODEL)
    spec = AIModelConfig.get_model_by_id(EVALUATION_MODEL)
    cost_bound, expected_payload = request_cost_ceiling(prepared, spec)
    ceiling = cost_bound["reserved_ceiling_usd"]
    if not math.isfinite(ceiling) or ceiling <= 0:
        raise ValueError("The complete checker request requires a finite positive cost bound")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model_id": EVALUATION_MODEL,
        "fixture": case.fixture,
        "evaluation_case": {
            "case_id": case.case_id,
            "case_version": case.case_version,
            "case_definition_sha256": case.case_sha256,
            "semantic_calibration": ASSESSMENT_PENDING,
        },
        # Bindings are canonical server-produced identities, not model choices.
        "binding": prepared.binding.model_dump(),
        "generation": prepared.generation.model_dump(),
        "estimated_input_tokens": prepared.generation.estimated_input_tokens,
        "max_completion_tokens": prepared.generation.max_completion_tokens,
        "pricing_verified_on": spec.pricing_verified_on,
        **cost_bound,
        "status": "dry_run_prepared_no_call",
        "result": None,
    }
    if not run_paid:
        _summary(report)
        return True
    if previous_reserved_usd + ceiling > cap_usd:
        print("Prior reservations plus this conservative call ceiling exceed the approved cap; no call was made.")
        return False

    report.update({
        "approved_cap_usd": cap_usd,
        "previous_reserved_usd": previous_reserved_usd,
        "total_reserved_ceiling_usd": previous_reserved_usd + ceiling,
        "status": "reserved_provider_outcome_unknown",
        "provider_dispatches": 0,
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after preparation; exclusive creation handles another process
    # reserving the same name. A dangling report symlink also fails closed.
    _report_destination(report_name)
    with report_path.open("x+", encoding="utf-8") as stream:
        _write_report(stream, report)
        initial_database = DatabaseFactory._instance
        previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            api_key = await get_workspace_service().get_api_key()
            if not api_key:
                report["status"] = "no_saved_key_no_call"
                return False
            async with workspace_openai_client(api_key) as client:
                if str(client.base_url) != "https://api.openai.com/v1/":
                    report["status"] = "nonstandard_provider_endpoint_no_call"
                    return False
                original_completion = engine.create_chat_completion
                dispatch_count = 0

                async def one_bounded_completion(*args, **kwargs):
                    nonlocal dispatch_count
                    expected_kwargs = {key: value for key, value in expected_payload.items() if key != "store"}
                    expected_kwargs["validate_output"] = False
                    if (len(args) != 1 or str(getattr(args[0], "base_url", "")) != "https://api.openai.com/v1/"
                            or kwargs != expected_kwargs or dispatch_count):
                        raise ValueError("The checker request changed or attempted another dispatch")
                    dispatch_count += 1
                    report["provider_dispatches"] = dispatch_count
                    # Do not capture raw response text, headers or request data.
                    return await original_completion(*args, **kwargs)

                with patch.object(engine, "create_chat_completion", one_bounded_completion):
                    result = await engine.check_review(prepared, client)
                if dispatch_count != 1:
                    raise ValueError("The checker did not dispatch its one reserved request")
            report["status"] = result.status
            report["result"] = result.model_dump(mode="json")
            usage = result.generation.usage
            if usage:
                long_context = usage.prompt_tokens > 272_000
                report["usage_based_cost_estimate_usd"] = (
                    usage.prompt_tokens * spec.input_price_per_million * (2 if long_context else 1)
                    + usage.completion_tokens * spec.output_price_per_million * (1.5 if long_context else 1)
                ) / 1_000_000
            return result.status == "completed"
        except Exception as error:
            report["status"] = "evaluation_interrupted_outcome_unknown"
            report["error_type"] = type(error).__name__
            return False
        finally:
            try:
                # Do not close a pre-existing connection or initialize MongoDB
                # merely to clean up a rejected/preparation-only attempt.
                if initial_database is None and DatabaseFactory._instance is not None:
                    await DatabaseFactory.close()
            except Exception as error:
                report["cleanup_error_type"] = type(error).__name__
            finally:
                logging.disable(previous_logging_disable)
                _write_report(stream, report)
                _summary(report, report_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASE_IDS, default=DEFAULT_CASE)
    parser.add_argument("--run-paid", action="store_true", help="Requires separate approval; dry-run is the default")
    parser.add_argument("--cap-usd", type=float)
    parser.add_argument("--report-name")
    parser.add_argument("--previous-reserved-usd", type=float, default=0,
                        help="Prior confirmed costs or retained ceilings within this same approved total budget")
    args = parser.parse_args(argv)
    if args.run_paid:
        try:
            _validate_budget(args.cap_usd, args.previous_reserved_usd)
            _report_destination(args.report_name)
        except ValueError as error:
            parser.error(str(error))
    try:
        return 0 if asyncio.run(run_check(args.case, run_paid=args.run_paid, cap_usd=args.cap_usd,
                                         report_name=args.report_name,
                                         previous_reserved_usd=args.previous_reserved_usd)) else 1
    except Exception as error:
        # Preparation exceptions may contain source/candidate validation input.
        # Display no exception body or traceback in this command-line harness.
        print(json.dumps({"status": "preflight_failed_no_automatic_retry", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
