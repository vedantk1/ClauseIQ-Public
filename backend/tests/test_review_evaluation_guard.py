"""Paid-evaluation guard checks with disposable files and mocked provider/key I/O."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from clauseiq_types.review import ReviewCoverage, ReviewGeneration, ReviewUsage
from tests import manual_review_generation_check as check


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-project"
    backend = root / "backend"
    fixture_path = root / "tests" / "fixtures" / "pdfs" / "managed-services-25p.pdf"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_bytes(b"synthetic bytes; the extractor is mocked")
    fixture_json = backend / "fixtures" / "review_evaluations" / "managed-services-25p.json"
    fixture_json.parent.mkdir(parents=True)
    case_definition = {"case_id": "managed-services-25p", "fixture": fixture_path.name,
        "case_version": "test-v1", "page_count": 1,
        "source_anchors": {"term": {"page": 1, "quote": "A synthetic term."}},
        "criteria": [{"id": "example", "importance": "priority", "expectation": "PRIVATE EVALUATION EXPECTATION",
                      "anchors": ["term"], "must_not_claim": ["PRIVATE FORBIDDEN CLAIM"]}],
        "source_sha256": "a" * 64, "context": {
        "perspective": "customer", "role": "Synthetic customer", "priorities": "Exit",
    }}
    fixture_json.write_text(json.dumps(case_definition))
    contrast_json = fixture_json.with_name("service-terms-conflict.json")
    contrast_json.write_text(json.dumps(case_definition | {
        "case_id": "service-terms-conflict", "fixture": "service-terms-conflict.pdf",
        "context": {"perspective": "customer", "role": "Synthetic contrast customer", "priorities": "Payment timing"},
    }))
    fixture_path.with_name("service-terms-conflict.pdf").write_bytes(b"synthetic contrast bytes")
    monkeypatch.setattr(check, "ROOT", root)
    monkeypatch.setattr(check, "BACKEND", backend)
    # Do not change the test runner's logging state.
    monkeypatch.setattr(check.logging, "disable", Mock())
    extraction = SimpleNamespace(content_sha256="a" * 64, status="complete", page_count=1,
        pages=[SimpleNamespace(page_number=1, text="A synthetic term.")],
        model_dump=Mock(return_value={"synthetic": "source"}))
    extractor = SimpleNamespace(extract_source=AsyncMock(return_value=extraction))
    monkeypatch.setattr(check, "TextExtractor", Mock(return_value=extractor))
    generation = ReviewGeneration(model_id="gpt-5.6-terra", reasoning_effort="low", max_completion_tokens=4000,
        catalog_verified_on="synthetic", prompt_version="test", schema_version="test", extraction_version="test",
        estimated_input_tokens=200)
    prepared = SimpleNamespace(generation=generation,
        messages=[{"role": "system", "content": "Review synthetic text."}, {"role": "user", "content": "Synthetic agreement."}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "source_review", "strict": True, "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        }})
    prepare = Mock(return_value=prepared)
    monkeypatch.setattr(check, "prepare_review", prepare)
    spec = SimpleNamespace(context_window=1050000, input_price_per_million=2.00,
        output_price_per_million=12.00, pricing_verified_on="synthetic")
    catalog = Mock(return_value=spec)
    monkeypatch.setattr(check.AIModelConfig, "get_model_by_id", catalog)
    key = AsyncMock(return_value="mocked-credential-do-not-log")
    workspace_factory = Mock(return_value=SimpleNamespace(get_api_key=key))
    monkeypatch.setattr(check, "get_workspace_service", workspace_factory)
    close = AsyncMock()
    monkeypatch.setattr(check.DatabaseFactory, "close", close)
    client = SimpleNamespace(base_url="https://api.openai.com/v1/")
    opened = []

    @asynccontextmanager
    async def client_context(credential):
        assert credential == "mocked-credential-do-not-log"
        opened.append(client)
        yield client

    monkeypatch.setattr(check, "workspace_openai_client", client_context)
    result = SimpleNamespace(status="ready", overview_items=[], findings=[], failure=None,
        coverage=ReviewCoverage(page_count=1, extracted_pages=[1], omitted_pages=[]),
        generation=generation.model_copy(update={"usage": ReviewUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)}))
    generate = AsyncMock(return_value=result)
    monkeypatch.setattr(check, "generate_review", generate)
    report = root / ".local-only" / "review-evaluations" / "synthetic-check.json"
    return SimpleNamespace(root=root, report=report, extractor=extractor, extraction=extraction,
        prepared=prepared, prepare=prepare, key=key, workspace_factory=workspace_factory,
        close=close, client=client, opened=opened, generate=generate, result=result, catalog=catalog, spec=spec)


async def run(evaluation, cap=0.60, previous=0, case_id=check.DEFAULT_CASE):
    return await check.run_check(cap, "synthetic-check", previous, case_id)


@pytest.mark.asyncio
async def test_existing_report_prevents_every_read_and_call(evaluation, capsys):
    evaluation.report.parent.mkdir(parents=True)
    previous = '{"status":"reserved_provider_outcome_unknown"}'
    evaluation.report.write_text(previous)
    assert await run(evaluation) is False
    assert evaluation.report.read_text() == previous
    evaluation.extractor.extract_source.assert_not_awaited()
    evaluation.prepare.assert_not_called()
    evaluation.workspace_factory.assert_not_called()
    evaluation.generate.assert_not_awaited()
    evaluation.close.assert_not_awaited()
    assert "no call was made" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_complete_request_ceiling_above_cap_prevents_key_and_provider(evaluation):
    # A small local estimate cannot remove schema, byte and output reservations.
    assert evaluation.prepared.generation.estimated_input_tokens == 200
    assert await run(evaluation, cap=0.01) is False
    assert not evaluation.report.exists()
    evaluation.workspace_factory.assert_not_called()
    evaluation.key.assert_not_awaited()
    evaluation.generate.assert_not_awaited()
    assert evaluation.opened == []


@pytest.mark.asyncio
async def test_only_fixed_synthetic_fixture_hash_can_reach_prepare(evaluation):
    evaluation.extraction.content_sha256 = "b" * 64
    with pytest.raises(ValueError, match="synthetic fixture changed"):
        await run(evaluation)
    assert not evaluation.report.exists()
    evaluation.prepare.assert_not_called()
    evaluation.workspace_factory.assert_not_called()
    evaluation.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonstandard_endpoint_is_rejected_without_dispatch(evaluation):
    evaluation.client.base_url = "https://example.invalid/v1/"
    assert await run(evaluation) is False
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "nonstandard_provider_endpoint_no_call"
    assert report["result"] is None
    evaluation.generate.assert_not_awaited()
    evaluation.close.assert_awaited_once()
    evaluation.key.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_saved_key_is_reported_without_creating_provider_client(evaluation):
    evaluation.key.return_value = None
    assert await run(evaluation) is False
    assert json.loads(evaluation.report.read_text())["status"] == "no_saved_key_no_call"
    assert evaluation.opened == []
    evaluation.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_reservation_precedes_one_dispatch_and_usage_report_has_no_credential(evaluation, capsys):
    async def generate(prepared, client):
        report = json.loads(evaluation.report.read_text())
        assert report["status"] == "reserved_provider_outcome_unknown"
        assert report["result"] is None
        bound, _ = check.request_cost_ceiling(prepared, evaluation.spec)
        assert report["reserved_ceiling_usd"] == bound["reserved_ceiling_usd"]
        assert report["approved_cap_usd"] == 0.60
        assert prepared is evaluation.prepared and client is evaluation.client
        return evaluation.result
    evaluation.generate.side_effect = generate
    assert await run(evaluation) is True
    report = json.loads(evaluation.report.read_text())
    assert report["model_id"] == "gpt-5.6-terra"
    assert report["fixture"] == "managed-services-25p.pdf"
    assert report["source_sha256"] == "a" * 64
    assert report["evaluation_case"]["case_id"] == "managed-services-25p"
    assert report["evaluation_case"]["case_version"] == "test-v1"
    assert report["evaluation_case"]["criteria_reference"] == "backend/fixtures/review_evaluations/managed-services-25p.json"
    assert len(report["evaluation_case"]["case_definition_sha256"]) == 64
    assert report["evaluation_case"]["criteria_ids"] == ["example"]
    assert report["evaluation_case"]["semantic_assessment"] == "not_assessed_requires_source_review"
    assert report["status"] == "ready"
    assert report["usage_based_cost_estimate_usd"] == pytest.approx(0.0008)
    assert report["result"]["generation"]["usage"]["total_tokens"] == 150
    evaluation.catalog.assert_called_once_with("gpt-5.6-terra")
    evaluation.prepare.assert_called_once()
    document, context, model = evaluation.prepare.call_args.args
    assert document["source_revision_id"] == "synthetic-evaluation-source"
    assert context.perspective == "customer" and model == "gpt-5.6-terra"
    assert "mocked-credential-do-not-log" not in evaluation.report.read_text() + capsys.readouterr().out
    before = evaluation.report.read_text()
    assert await run(evaluation) is False
    assert evaluation.report.read_text() == before
    evaluation.generate.assert_awaited_once()
    evaluation.key.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_allowlisted_case_uses_its_own_pdf_brief_and_reference_only(evaluation):
    assert await run(evaluation, case_id="service-terms-conflict") is True
    evaluation.extractor.extract_source.assert_awaited_once_with(b"synthetic contrast bytes", "service-terms-conflict.pdf")
    _, brief, model = evaluation.prepare.call_args.args
    assert brief.role == "Synthetic contrast customer" and brief.priorities == "Payment timing"
    assert model == "gpt-5.6-terra"
    assert "PRIVATE EVALUATION EXPECTATION" not in str(evaluation.prepare.call_args)
    assert "PRIVATE FORBIDDEN CLAIM" not in str(evaluation.prepare.call_args)
    report = json.loads(evaluation.report.read_text())
    assert report["evaluation_case"]["case_id"] == "service-terms-conflict"
    assert report["evaluation_case"]["criteria_reference"].endswith("/service-terms-conflict.json")
    assert report["fixture"] == "service-terms-conflict.pdf"


@pytest.mark.asyncio
async def test_finite_approved_cap_can_exceed_previous_one_dollar_limit(evaluation):
    assert await run(evaluation, cap=3, previous=1.5) is True
    report = json.loads(evaluation.report.read_text())
    assert report["approved_cap_usd"] == 3 and report["previous_reserved_usd"] == 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [0, -1, float("nan"), float("inf")])
async def test_nonpositive_or_nonfinite_cap_fails_before_any_read(evaluation, cap):
    with pytest.raises(ValueError):
        await run(evaluation, cap=cap)
    evaluation.extractor.extract_source.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["unknown", "../managed-services-25p", "service-terms-conflict.pdf"])
async def test_unreviewed_case_fails_before_any_read_or_key(evaluation, case_id):
    with pytest.raises(ValueError, match="allowlisted"):
        await run(evaluation, case_id=case_id)
    evaluation.extractor.extract_source.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "../synthetic-check", "not/allowed", "x" * 81])
async def test_report_name_is_bounded_for_programmatic_callers_too(evaluation, name):
    with pytest.raises(ValueError, match="report name"):
        await check.run_check(1, name)
    evaluation.extractor.extract_source.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
async def test_reference_anchor_drift_refuses_dispatch_before_key(evaluation):
    evaluation.extraction.pages[0].text = "An unrelated synthetic term."
    with pytest.raises(ValueError, match="source anchor"):
        await run(evaluation)
    evaluation.prepare.assert_not_called()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_error_keeps_unknown_reservation_without_secret_or_retry(evaluation, capsys):
    evaluation.generate.side_effect = RuntimeError("PRIVATE REQUEST OR CREDENTIAL")
    assert await run(evaluation) is False
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "evaluation_interrupted_outcome_unknown"
    assert report["error_type"] == "RuntimeError"
    bound, _ = check.request_cost_ceiling(evaluation.prepared, evaluation.spec)
    assert report["reserved_ceiling_usd"] == bound["reserved_ceiling_usd"]
    assert "PRIVATE REQUEST" not in evaluation.report.read_text() + capsys.readouterr().out
    assert await run(evaluation) is False
    evaluation.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_process_preserves_no_replay_reservation(evaluation):
    evaluation.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await run(evaluation)
    assert json.loads(evaluation.report.read_text())["status"] == "reserved_provider_outcome_unknown"
    assert await run(evaluation) is False
    evaluation.generate.assert_awaited_once()
    evaluation.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_reservation_race_fails_closed_before_credential_read(evaluation, monkeypatch):
    original_open = type(evaluation.report).open
    previous = '{"status":"reserved_by_other_attempt"}'
    def raced_open(path, mode="r", *args, **kwargs):
        if path == evaluation.report and mode == "x":
            with original_open(path, "w", encoding="utf-8") as stream:
                stream.write(previous)
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(type(evaluation.report), "open", raced_open)
    with pytest.raises(FileExistsError):
        await run(evaluation)
    assert evaluation.report.read_text() == previous
    evaluation.workspace_factory.assert_not_called()
    evaluation.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_diagnostic_capture_saves_only_synthetic_message_not_request_metadata(evaluation, monkeypatch, capsys):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Synthetic provider answer"))],
                               private_metadata="MUST NOT CAPTURE")
    completion = AsyncMock(return_value=response)
    monkeypatch.setattr(check.review_generation, "create_chat_completion", completion)
    evaluation.prepared.messages[1]["content"] = "MUST NOT CAPTURE"

    async def generate(prepared, client):
        _, payload = check.request_cost_ceiling(prepared, evaluation.spec)
        kwargs = {key: value for key, value in payload.items() if key != "store"}
        assert await check.review_generation.create_chat_completion(client, **kwargs, validate_output=False) is response
        return evaluation.result

    evaluation.generate.side_effect = generate
    assert await run(evaluation) is True
    report = json.loads(evaluation.report.read_text())
    assert report["synthetic_provider_output"] == "Synthetic provider answer"
    assert "MUST NOT CAPTURE" not in evaluation.report.read_text() + capsys.readouterr().out
    assert check.review_generation.create_chat_completion is completion
    completion.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_tokens,expected_cost", [(272000, 0.5446), (272001, 1.088904)])
async def test_usage_estimate_applies_long_context_uplift_only_above_threshold(evaluation, prompt_tokens, expected_cost):
    evaluation.result.generation.usage = ReviewUsage(
        prompt_tokens=prompt_tokens, completion_tokens=50, total_tokens=prompt_tokens + 50,
    )
    assert await run(evaluation) is True
    report = json.loads(evaluation.report.read_text())
    assert report["usage_based_cost_estimate_usd"] == pytest.approx(expected_cost)
    # The reservation includes the conservative cache-write uplift independently
    # of the usage-based estimate and is never reduced to the observed cost.
    bound, _ = check.request_cost_ceiling(evaluation.prepared, evaluation.spec)
    assert report["reserved_ceiling_usd"] == bound["reserved_ceiling_usd"]
    evaluation.generate.assert_awaited_once()


def test_complete_utf8_request_and_schema_are_included_in_input_ceiling(evaluation):
    evaluation.prepared.messages[1]["content"] = "Synthetic € text 🔎"
    bound, payload = check.request_cost_ceiling(evaluation.prepared, evaluation.spec)
    expected_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert bound["serialized_request_bytes"] == expected_bytes
    assert bound["input_token_ceiling"] == expected_bytes + 4096
    assert bound["reserved_ceiling_usd"] == pytest.approx(((expected_bytes + 4096) * 2 * 1.25 + 4000 * 12) / 1_000_000)
    assert bound["long_context_pricing"] is False
    evaluation.prepared.generation.estimated_input_tokens = 300_000
    bound, _ = check.request_cost_ceiling(evaluation.prepared, evaluation.spec)
    assert bound["input_token_ceiling"] == 300_000
    assert bound["long_context_pricing"] is True
    assert bound["reserved_ceiling_usd"] == pytest.approx((300_000 * 2 * 2 * 1.25 + 4000 * 12 * 1.5) / 1_000_000)


@pytest.mark.asyncio
async def test_previous_reservation_is_part_of_total_cap_and_report(evaluation):
    assert await run(evaluation, cap=0.1, previous=0.09) is False
    assert not evaluation.report.exists()
    evaluation.key.assert_not_awaited()
    evaluation.generate.assert_not_awaited()
    assert await run(evaluation, cap=0.6, previous=0.15) is True
    report = json.loads(evaluation.report.read_text())
    assert report["previous_reserved_usd"] == 0.15
    assert report["total_reserved_ceiling_usd"] == report["reserved_ceiling_usd"] + 0.15


@pytest.mark.parametrize("mutation", [
    lambda p: p.messages[1].update(content=[{"type": "image_url", "image_url": "synthetic"}]),
    lambda p: p.messages[1].update(tools=[]),
    lambda p: p.messages.append({"role": "tool", "content": "synthetic"}),
    lambda p: p.response_format.update(tools=[]),
    lambda p: p.response_format["json_schema"].update(strict=False),
    lambda p: setattr(p.generation, "model_id", "gpt-5.6-sol"),
    lambda p: setattr(p.generation, "estimated_input_tokens", 1_049_000),
])
@pytest.mark.asyncio
async def test_unsupported_payload_or_excessive_context_is_rejected_before_key(evaluation, mutation):
    mutation(evaluation.prepared)
    with pytest.raises(ValueError):
        await run(evaluation)
    assert not evaluation.report.exists()
    evaluation.key.assert_not_awaited()
    evaluation.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [-1, float("nan"), float("inf"), 0.61])
async def test_invalid_previous_reservation_fails_before_any_read(evaluation, previous):
    with pytest.raises(ValueError):
        await run(evaluation, previous=previous)
    evaluation.extractor.extract_source.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["additional_option", "second_call"])
async def test_dispatch_rechecks_request_shape_and_blocks_additional_calls(evaluation, monkeypatch, change):
    completion = AsyncMock(return_value=SimpleNamespace(choices=[]))
    monkeypatch.setattr(check.review_generation, "create_chat_completion", completion)

    async def generate(prepared, client):
        _, payload = check.request_cost_ceiling(prepared, evaluation.spec)
        kwargs = {key: value for key, value in payload.items() if key != "store"} | {"validate_output": False}
        if change == "additional_option":
            kwargs["tools"] = []
        else:
            await check.review_generation.create_chat_completion(client, **kwargs)
        await check.review_generation.create_chat_completion(client, **kwargs)
        return evaluation.result

    evaluation.generate.side_effect = generate
    assert await run(evaluation) is False
    assert completion.await_count == (1 if change == "second_call" else 0)
    assert json.loads(evaluation.report.read_text())["status"] == "evaluation_interrupted_outcome_unknown"
