"""Development checker transport and parser tests; no network or paid calls."""

import ast
import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from clauseiq_types.review import ReviewGeneration
from evaluations.review_checker import engine
from evaluations.review_checker.contract import CheckBinding, DiagnosticReport, PreparedCheck
from evaluations.review_checker.prompt import CHECK_SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION


@pytest.fixture(autouse=True)
def explicit_budget(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "100000")


@pytest.fixture
def prepared():
    return PreparedCheck(
        generation=ReviewGeneration(
            model_id="gpt-6-sol", reasoning_effort="medium", max_completion_tokens=16000,
            catalog_verified_on="2026-09-18", prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION, extraction_version="synthetic-lines-v1",
            estimated_input_tokens=1000,
        ),
        messages=[{"role": "system", "content": CHECK_SYSTEM_PROMPT},
                  {"role": "user", "content": '{"synthetic":true}'}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "review_diagnostics", "strict": True,
            "schema": DiagnosticReport.model_json_schema(),
        }},
        timeout_seconds=120,
        binding=CheckBinding(
            source_revision_id="synthetic_revision", source_sha256="a" * 64,
            extraction_sha256="b" * 64, extraction_version="synthetic-lines-v1",
            passage_version="source-passages-v1", candidate_sha256="c" * 64,
            brief_sha256="d" * 64,
        ),
        targets={"overview_1.text": "Customer pays €50. 🚫 No increase.",
                 "finding_1.facts": "Charges require written agreement."},
        item_ids=frozenset({"overview_1", "finding_1"}),
        passage_ids=frozenset({"p1_b1_v1", "p1_b2_v1"}),
        priorities="Understand charges and exit options.", source_complete=True,
    )


@pytest.fixture
def output(prepared):
    return {
        "target_checks": [{"target_id": target_id, "status": "assessed", "reason": "Examined the stated assertion."}
                          for target_id in prepared.targets],
        "claim_issues": [],
        "priority_assessment": {"status": "addressed", "explanation": "The stated priorities are surfaced.", "gaps": []},
        "limitations": [],
    }


def response(output=None, *, content=None, finish="stop", refusal=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(
            content=json.dumps(output, ensure_ascii=False) if output is not None else content,
            refusal=refusal,
        ))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=100, total_tokens=300),
    )


def mock_client(reply):
    call = AsyncMock(return_value=reply)
    bounded = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=call)))
    options = []

    def with_options(**kwargs):
        options.append(kwargs)
        return bounded

    return SimpleNamespace(with_options=with_options), call, options


def issue(prepared):
    text = prepared.targets["overview_1.text"]
    quote = "No increase."
    start = text.index(quote)
    return {"target_id": "overview_1.text", "start": start, "end": start + len(quote),
            "quote": quote, "category": "qualification_missing",
            "explanation": "The source permits increases with written agreement.", "passage_ids": ["p1_b2_v1"]}


def gap(prepared):
    quote = "exit options"
    start = prepared.priorities.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote,
            "explanation": "The candidate does not explain the stated exit priority.",
            "passage_ids": ["p1_b2_v1"], "related_item_ids": ["finding_1"]}


@pytest.mark.asyncio
async def test_one_bounded_call_binding_usage_and_no_input_mutation(prepared, output):
    before = deepcopy(prepared)
    client, call, options = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.status == "completed" and result.failure is None
    assert result.diagnostics.model_dump() == output
    assert result.binding == prepared.binding and result.binding is not prepared.binding
    assert result.generation.usage.total_tokens == 300 and result.generation.duration_ms >= 0
    assert prepared == before and prepared.generation.usage is None
    assert options == [{"max_retries": 0, "timeout": 120}]
    call.assert_awaited_once()
    request = call.call_args.kwargs
    assert request["model"] == "gpt-6-sol"
    assert request["reasoning_effort"] == "medium" and request["max_completion_tokens"] == 16000
    assert request["store"] is False and request["response_format"] == prepared.response_format
    assert "validate_output" not in request


@pytest.mark.asyncio
async def test_completed_diagnostics_can_report_problems_not_a_quality_pass(prepared, output):
    output["claim_issues"] = [issue(prepared)]
    output["priority_assessment"].update(status="partial", gaps=[gap(prepared)])
    client, _, _ = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.status == "completed" and result.failure is None
    assert result.diagnostics.claim_issues[0].quote == "No increase."
    assert result.diagnostics.priority_assessment.gaps
    assert not hasattr(result, "verified") and not hasattr(result, "score")


@pytest.mark.asyncio
@pytest.mark.parametrize("partial_source,unassessable_target,unassessable_priority,code", [
    (True, False, False, "PARTIAL_CHECK_SOURCE"),
    (False, True, False, "CHECK_NOT_ASSESSABLE"),
    (False, False, True, "CHECK_NOT_ASSESSABLE"),
])
async def test_explicit_incompleteness_retains_valid_diagnostics(
        prepared, output, partial_source, unassessable_target, unassessable_priority, code):
    if unassessable_target:
        output["target_checks"][0]["status"] = "not_assessable"
    if unassessable_priority:
        output["priority_assessment"]["status"] = "not_assessable"
    client, call, _ = mock_client(response(output))
    result = await engine.check_review(replace(prepared, source_complete=not partial_source), client)
    assert result.status == "incomplete" and result.failure.code == code
    assert result.diagnostics.model_dump() == output
    assert result.generation.usage.total_tokens == 300
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_assertion_and_unstated_priorities_are_valid_not_invented(prepared, output):
    output["target_checks"][0]["status"] = "no_factual_assertion"
    output["priority_assessment"]["status"] = "not_stated"
    client, _, _ = mock_client(response(output))
    result = await engine.check_review(replace(prepared, priorities=""), client)
    assert result.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda o: o["target_checks"].pop(),
    lambda o: o["target_checks"].append(deepcopy(o["target_checks"][0])),
    lambda o: o["target_checks"][0].update(target_id="unknown_target"),
    lambda o: o["target_checks"][0].update(reason=" "),
    lambda o: o["priority_assessment"].update(status="not_stated"),
    lambda o: o["priority_assessment"].update(status="partial"),
    lambda o: o.update(limitations=[" "]),
])
async def test_bad_inventory_or_cross_field_meaning_withholds_all_diagnostics(prepared, output, mutation):
    mutation(output)
    client, call, _ = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.status == "incomplete" and result.failure.code == "INVALID_CHECK_REFERENCES"
    assert result.diagnostics is None and result.generation.usage.total_tokens == 300
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda i: i.update(target_id="finding_1.facts"),
    lambda i: i.update(target_id="unknown_target"),
    lambda i: i.update(start=i["start"] + 1, end=i["end"] + 1),  # UTF-16 offset after emoji is wrong.
    lambda i: i.update(quote="PRIVATE_PROVIDER_OUTPUT"),
    lambda i: i.update(passage_ids=["invented_passage"]),
    lambda i: i.update(passage_ids=["p1_b1_v1", "p1_b1_v1"]),
    lambda i: i.update(explanation=" "),
])
async def test_issue_requires_exact_codepoint_text_and_supplied_ids(prepared, output, mutation):
    value = issue(prepared)
    mutation(value)
    output["claim_issues"] = [value]
    client, _, _ = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "INVALID_CHECK_REFERENCES" and result.diagnostics is None
    assert "PRIVATE_PROVIDER_OUTPUT" not in result.failure.message


@pytest.mark.asyncio
async def test_gap_and_related_item_ids_are_checked(prepared, output):
    value = gap(prepared)
    value["related_item_ids"] = ["unknown_item"]
    output["priority_assessment"].update(status="partial", gaps=[value])
    client, _, _ = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "INVALID_CHECK_REFERENCES" and result.diagnostics is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda o: o.update(verified=True),
    lambda o: o.update(binding={"source_revision_id": "other_source"}),
    lambda o: o["target_checks"][0].update(status="passed"),
    lambda o: o["target_checks"][0].pop("reason"),
    lambda o: o["priority_assessment"].update(explanation="x" * 1001),
    lambda o: o.update(limitations=["warning"] * 21),
])
async def test_strict_shape_disallows_repair_score_binding_and_extra_fields(prepared, output, mutation):
    mutation(output)
    client, _, _ = mock_client(response(output))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "INVALID_CHECK_SHAPE" and result.diagnostics is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content,code", [
    ("not JSON", "INVALID_CHECK_SHAPE"),
    ('{"target_checks":[],"target_checks":[]}', "INVALID_CHECK_SHAPE"),
    ('{"unknown":NaN}', "INVALID_CHECK_SHAPE"),
    ('{"unknown":Infinity}', "INVALID_CHECK_SHAPE"),
    ('{"target_checks":[{"target_id":"x","status":"assessed","reason":"\\ud800"}]}', "INVALID_CHECK_SHAPE"),
    ("{}", "INVALID_CHECK_SHAPE"),
    ("[]", "INVALID_CHECK_SHAPE"),
    ("[" * 10000, "INVALID_CHECK_SHAPE"),
    ("\ud800", "INVALID_CHECK_SHAPE"),
    ("", "INCOMPLETE_CHECK_RESPONSE"),
    (None, "INCOMPLETE_CHECK_RESPONSE"),
])
async def test_malformed_json_is_incomplete_not_silent_empty_success(prepared, content, code):
    client, call, _ = mock_client(response(content=content))
    result = await engine.check_review(prepared, client)
    assert result.status == "incomplete" and result.failure.code == code
    assert result.diagnostics is None and result.generation.usage.total_tokens == 300
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_nested_duplicate_keys_are_rejected_even_with_valid_values(prepared, output):
    raw = json.dumps(output).replace('"status": "assessed"', '"status": "assessed", "status": "assessed"', 1)
    client, _, _ = mock_client(response(content=raw))
    assert (await engine.check_review(prepared, client)).failure.code == "INVALID_CHECK_SHAPE"


@pytest.mark.asyncio
async def test_byte_cap_counts_utf8_and_accepts_exact_boundary(prepared, output, monkeypatch):
    output["limitations"] = ["Synthetic text includes an emoji: 🙂"]
    content = json.dumps(output, ensure_ascii=False)
    byte_size = len(content.encode("utf-8"))
    assert byte_size > len(content)
    monkeypatch.setattr(engine, "MAX_RESPONSE_BYTES", byte_size)
    client, _, _ = mock_client(response(content=content))
    assert (await engine.check_review(prepared, client)).status == "completed"
    monkeypatch.setattr(engine, "MAX_RESPONSE_BYTES", byte_size - 1)
    client, call, _ = mock_client(response(content=content))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "CHECK_RESPONSE_SIZE_LIMIT" and result.diagnostics is None
    assert result.generation.usage.total_tokens == 300
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish,refusal,code", [
    ("length", None, "CHECK_OUTPUT_LIMIT"),
    ("stop", "PRIVATE_REFUSAL", "CHECK_REFUSED"),
    ("content_filter", None, "CHECK_REFUSED"),
    ("tool_calls", None, "INCOMPLETE_CHECK_RESPONSE"),
    (None, None, "INCOMPLETE_CHECK_RESPONSE"),
])
async def test_refusal_or_unfinished_output_retains_usage_without_diagnostics(prepared, output, finish, refusal, code):
    client, call, _ = mock_client(response(output, finish=finish, refusal=refusal))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == code and result.diagnostics is None
    assert result.generation.usage.total_tokens == 300 and "PRIVATE_REFUSAL" not in result.failure.message
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("choices", [[], None, {"unexpected": "shape"}, "invalid choices"])
async def test_no_response_does_not_fabricate_usage(prepared, choices):
    client, _, _ = mock_client(SimpleNamespace(choices=choices, usage=None))
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "EMPTY_CHECK_RESPONSE" and result.generation.usage is None


@pytest.mark.asyncio
async def test_invalid_usage_is_not_replaced_with_zero(prepared, output):
    reply = response(output)
    reply.usage = SimpleNamespace(prompt_tokens="200", completion_tokens=100, total_tokens=300)
    client, _, _ = mock_client(reply)
    result = await engine.check_review(prepared, client)
    assert result.status == "completed" and result.generation.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,code", [
    (asyncio.TimeoutError("PRIVATE_PROVIDER_OUTPUT"), "CHECK_TIMEOUT"),
    (RuntimeError("PRIVATE_PROVIDER_OUTPUT"), "CHECK_REQUEST_FAILED"),
])
async def test_exceptions_have_no_raw_content_or_automatic_retry(prepared, exception, code, caplog):
    client, call, _ = mock_client(response())
    call.side_effect = exception
    result = await engine.check_review(prepared, client)
    assert result.status == "failed" and result.failure.code == code
    assert result.diagnostics is None and result.generation.usage is None
    assert "PRIVATE_PROVIDER_OUTPUT" not in result.failure.message
    assert "PRIVATE_PROVIDER_OUTPUT" not in caplog.text
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_wall_clock_timeout_bounds_stalled_provider(prepared, monkeypatch):
    client, call, options = mock_client(response())
    cancelled = asyncio.Event()
    original_wait_for = asyncio.wait_for

    async def stalled_provider(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def short_test_timeout(awaitable, timeout):
        assert timeout == 120
        return await original_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(engine.asyncio, "wait_for", short_test_timeout)
    call.side_effect = stalled_provider
    result = await engine.check_review(prepared, client)
    assert result.failure.code == "CHECK_TIMEOUT" and cancelled.is_set()
    assert result.generation.duration_ms < 1000
    assert options == [{"max_retries": 0, "timeout": 120}]
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_hard_ceiling_and_invalid_timeout_make_no_request(prepared, output):
    client, call, options = mock_client(response(output))
    result = await engine.check_review(replace(prepared, timeout_seconds=999), client)
    assert result.status == "completed" and options == [{"max_retries": 0, "timeout": 180}]
    call.reset_mock()
    for invalid in (0, -1, True, 1.5):
        result = await engine.check_review(replace(prepared, timeout_seconds=invalid), client)
        assert result.failure.code == "INVALID_CHECK_TIMEOUT" and result.status == "failed"
        assert result.generation.usage is None
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status,finish,refusal,expected_code", [
    (200, "stop", None, None),
    (200, "length", None, "CHECK_OUTPUT_LIMIT"),
    (200, "stop", "PRIVATE_REFUSAL", "CHECK_REFUSED"),
    (401, "stop", None, "CHECK_PROVIDER_REQUEST_FAILED"),
    (429, "stop", None, "CHECK_PROVIDER_REQUEST_FAILED"),
    (500, "stop", None, "CHECK_PROVIDER_REQUEST_FAILED"),
])
async def test_real_sdk_mock_transport_serialization_and_zero_retries(prepared, output, http_status, finish, refusal, expected_code):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if http_status != 200:
            return httpx.Response(http_status, json={"error": {"message": "PRIVATE_PROVIDER_ERROR", "type": "server_error"}})
        return httpx.Response(200, json={
            "id": "synthetic_check", "object": "chat.completion", "created": 1,
            "model": "gpt-6-sol", "choices": [{"index": 0, "finish_reason": finish,
                "message": {"role": "assistant", "content": json.dumps(output), "refusal": refusal}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = AsyncOpenAI(api_key="synthetic-test-only", http_client=transport, max_retries=4)
        result = await engine.check_review(prepared, client)
    assert len(requests) == 1  # Even retryable HTTP errors must not trigger a second paid attempt.
    request = requests[0]
    assert request["store"] is False and request["model"] == "gpt-6-sol"
    assert request["max_completion_tokens"] == 16000 and request["reasoning_effort"] == "medium"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert "validate_output" not in request
    if expected_code:
        assert result.failure.code == expected_code and result.diagnostics is None
        assert "PRIVATE_" not in result.failure.message
    else:
        assert result.status == "completed"
    if http_status == 200:
        assert result.generation.usage.total_tokens == 300


def test_production_modules_do_not_import_evaluation_checker():
    backend = Path(__file__).resolve().parents[1]
    paths = [backend / "main.py"]
    for folder in ("routers", "services", "core", "middleware", "database", "ai_models"):
        paths.extend((backend / folder).rglob("*.py"))
    for path in paths:
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                       [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(module and (module == "evaluations" or module.startswith("evaluations."))
                           for module in modules), path.relative_to(backend)


def test_prompt_distinguishes_coverage_metadata_from_contract_evidence():
    assert "Targets whose item_id is coverage are extraction/scope limitations" in CHECK_SYSTEM_PROMPT
    assert "coverage targets have no evidence item" in CHECK_SYSTEM_PROMPT
