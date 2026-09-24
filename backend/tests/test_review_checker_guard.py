"""No-network tests for the checker harness's dry-run and paid-call boundary."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from clauseiq_types.review import ReviewGeneration, ReviewUsage
from evaluations.review_checker.contract import CheckBinding
from evaluations.review_checker.engine import check_review as actual_check_review
from tests import manual_review_checker as check


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-project"
    monkeypatch.setattr(check, "ROOT", root)
    monkeypatch.setattr(check.DatabaseFactory, "_instance", None)
    case = SimpleNamespace(
        case_id=check.DEFAULT_CASE, case_version="test-case-v1", case_sha256="a" * 64,
        fixture="synthetic.pdf", document={"synthetic": "SOURCE TEXT MUST NOT PRINT"},
        candidate={"synthetic": "CANDIDATE TEXT MUST NOT PRINT"},
        expectations=["EXPECTATION MUST NOT ENTER PREPARATION"],
    )
    loader = AsyncMock(return_value=case)
    monkeypatch.setattr(check, "load_checker_case", loader)
    generation = ReviewGeneration(
        model_id="gpt-6-sol", reasoning_effort="medium", max_completion_tokens=16000,
        catalog_verified_on="synthetic", prompt_version="test", schema_version="test",
        extraction_version="test", estimated_input_tokens=200,
    )
    binding_data = {"source_sha256": "b" * 64, "candidate_sha256": "c" * 64, "brief_sha256": "d" * 64}
    prepared = SimpleNamespace(
        generation=generation,
        binding=SimpleNamespace(model_dump=Mock(return_value=binding_data)),
        messages=[{"role": "system", "content": "Check synthetic text."},
                  {"role": "user", "content": "SOURCE AND CANDIDATE MUST NOT PRINT"}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "review_check", "strict": True,
            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        }},
    )
    prepare = Mock(return_value=prepared)
    monkeypatch.setattr(check, "prepare_check", prepare)
    spec = SimpleNamespace(context_window=1_050_000, input_price_per_million=2,
                           output_price_per_million=12, pricing_verified_on="synthetic")
    catalog = Mock(return_value=spec)
    monkeypatch.setattr(check.AIModelConfig, "get_model_by_id", catalog)
    database = object()

    async def read_key():
        if check.DatabaseFactory._instance is None:
            check.DatabaseFactory._instance = database
        return "mocked-credential-must-not-print"

    key = AsyncMock(side_effect=read_key)
    workspace_factory = Mock(return_value=SimpleNamespace(get_api_key=key))
    monkeypatch.setattr(check, "get_workspace_service", workspace_factory)
    close = AsyncMock()
    monkeypatch.setattr(check.DatabaseFactory, "close", close)
    client = SimpleNamespace(base_url="https://api.openai.com/v1/")
    opened = []

    @asynccontextmanager
    async def client_context(credential):
        assert credential == "mocked-credential-must-not-print"
        opened.append(client)
        yield client

    monkeypatch.setattr(check, "workspace_openai_client", client_context)
    result_generation = generation.model_copy(update={"usage": ReviewUsage(
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
    )})
    result = SimpleNamespace(status="completed", generation=result_generation)
    result.model_dump = Mock(side_effect=lambda **kwargs: {
        "status": result.status, "diagnostics": None, "binding": binding_data,
        "generation": result.generation.model_dump(), "failure": None,
    })
    completion = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="RAW PROVIDER TEXT MUST NOT SAVE"))],
        private_metadata="PRIVATE HEADERS MUST NOT SAVE",
    ))
    monkeypatch.setattr(check.engine, "create_chat_completion", completion)

    async def run_engine(prepared_arg, client_arg):
        _, payload = check.request_cost_ceiling(prepared_arg, spec)
        kwargs = {name: value for name, value in payload.items() if name != "store"}
        await check.engine.create_chat_completion(client_arg, **kwargs, validate_output=False)
        return result

    engine_call = AsyncMock(side_effect=run_engine)
    monkeypatch.setattr(check.engine, "check_review", engine_call)
    report = root / ".local-only" / "review-checks" / "synthetic-check.json"
    return SimpleNamespace(root=root, case=case, loader=loader, prepared=prepared,
        prepare=prepare, spec=spec, catalog=catalog, key=key, workspace_factory=workspace_factory,
        database=database, close=close, client=client, opened=opened, result=result,
        engine_call=engine_call, completion=completion, report=report, run_engine=run_engine)


async def paid(evaluation, **kwargs):
    options = {"cap_usd": 1, "report_name": "synthetic-check"} | kwargs
    return await check.run_check(run_paid=True, **options)


@pytest.mark.asyncio
async def test_dry_run_prepares_metadata_without_key_database_provider_or_files(evaluation, capsys):
    assert await check.run_check() is True
    assert not evaluation.root.exists()
    evaluation.loader.assert_awaited_once_with(check.DEFAULT_CASE)
    evaluation.prepare.assert_called_once_with(evaluation.case.document, evaluation.case.candidate,
                                              model_id="gpt-6-sol")
    evaluation.catalog.assert_called_once_with("gpt-6-sol")
    evaluation.workspace_factory.assert_not_called()
    evaluation.key.assert_not_awaited()
    evaluation.close.assert_not_awaited()
    evaluation.engine_call.assert_not_awaited()
    evaluation.completion.assert_not_awaited()
    assert evaluation.opened == []
    printed = capsys.readouterr().out
    metadata = json.loads(printed)
    assert metadata["status"] == "dry_run_prepared_no_call"
    assert metadata["evaluation_case"]["semantic_calibration"] == check.ASSESSMENT_PENDING
    assert metadata["binding"]["candidate_sha256"] == "c" * 64
    assert "MUST NOT" not in printed
    assert "EXPECTATION" not in str(evaluation.prepare.call_args)


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["../case", "/some/private.json", "unknown", "synthetic.pdf"])
async def test_unknown_or_path_selection_is_refused_before_read(evaluation, case_id):
    with pytest.raises(ValueError, match="allowlisted"):
        await check.run_check(case_id)
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [None, 0, -1, float("nan"), float("inf")])
async def test_paid_requires_finite_positive_budget_before_case_read(evaluation, cap):
    with pytest.raises(ValueError, match="finite positive"):
        await paid(evaluation, cap_usd=cap)
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [-1, float("nan"), float("inf"), 1.01])
async def test_previous_reservations_must_be_finite_and_within_cap(evaluation, previous):
    with pytest.raises(ValueError):
        await paid(evaluation, previous_reserved_usd=previous)
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "", "../case", "case/name", "x" * 81])
async def test_paid_report_name_rejects_traversal_and_unbounded_input(evaluation, name):
    with pytest.raises(ValueError, match="report name"):
        await paid(evaluation, report_name=name)
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhausted_cap_does_not_read_key_or_reserve_report(evaluation):
    assert await paid(evaluation, cap_usd=0.1) is False
    assert await paid(evaluation, previous_reserved_usd=0.95) is False
    assert not evaluation.root.exists()
    evaluation.workspace_factory.assert_not_called()
    evaluation.engine_call.assert_not_awaited()
    evaluation.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_budget_can_exceed_old_one_dollar_cap(evaluation):
    assert await paid(evaluation, cap_usd=3, previous_reserved_usd=1.5) is True
    report = json.loads(evaluation.report.read_text())
    assert report["approved_cap_usd"] == 3
    assert report["previous_reserved_usd"] == 1.5
    assert report["total_reserved_ceiling_usd"] == report["reserved_ceiling_usd"] + 1.5


@pytest.mark.asyncio
async def test_existing_reservation_refuses_replay_before_case_or_credentials(evaluation):
    evaluation.report.parent.mkdir(parents=True)
    original = '{"status":"reserved_provider_outcome_unknown"}'
    evaluation.report.write_text(original)
    assert await paid(evaluation) is False
    assert evaluation.report.read_text() == original
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()
    evaluation.engine_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["report", "report_dir", "local_dir"])
async def test_symlink_report_or_directory_is_rejected_before_reads(evaluation, destination):
    target = evaluation.root.parent / "elsewhere"
    if destination == "report":
        evaluation.report.parent.mkdir(parents=True)
        evaluation.report.symlink_to(target)  # A dangling symlink is still rejected.
    elif destination == "report_dir":
        evaluation.report.parent.parent.mkdir(parents=True)
        evaluation.report.parent.symlink_to(target)
    else:
        evaluation.root.mkdir()
        evaluation.report.parent.parent.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        await paid(evaluation)
    evaluation.loader.assert_not_awaited()
    evaluation.key.assert_not_awaited()
    assert not target.exists()


@pytest.mark.asyncio
async def test_reservation_race_keeps_other_attempt_and_does_not_read_key(evaluation, monkeypatch):
    original_open = type(evaluation.report).open
    previous = '{"status":"another_attempt"}'

    def raced_open(path, mode="r", *args, **kwargs):
        if path == evaluation.report and mode == "x+":
            with original_open(path, "w", encoding="utf-8") as stream:
                stream.write(previous)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(type(evaluation.report), "open", raced_open)
    with pytest.raises(FileExistsError):
        await paid(evaluation)
    assert evaluation.report.read_text() == previous
    evaluation.key.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_failure_never_opens_credentials_or_reserves(evaluation):
    evaluation.prepare.side_effect = ValueError("PRIVATE SOURCE VALIDATION")
    with pytest.raises(ValueError):
        await paid(evaluation)
    assert not evaluation.root.exists()
    evaluation.key.assert_not_awaited()
    evaluation.engine_call.assert_not_awaited()
    evaluation.close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda p: setattr(p.generation, "model_id", "gpt-5.6-luna"),
    lambda p: p.messages[1].update(content=[{"type": "image_url", "image_url": "private"}]),
    lambda p: p.messages.append({"role": "tool", "content": "private"}),
    lambda p: p.response_format["json_schema"].update(strict=False),
    lambda p: setattr(p.generation, "estimated_input_tokens", 1_049_000),
])
async def test_changed_model_or_unbounded_payload_fails_before_key(evaluation, mutation):
    mutation(evaluation.prepared)
    with pytest.raises(ValueError):
        await paid(evaluation)
    evaluation.key.assert_not_awaited()
    evaluation.engine_call.assert_not_awaited()
    assert not evaluation.root.exists()


@pytest.mark.asyncio
async def test_reserves_before_key_and_dispatch_records_only_parsed_result(evaluation, capsys):
    original_key = evaluation.key.side_effect

    async def key_after_reservation():
        report = json.loads(evaluation.report.read_text())
        assert report["status"] == "reserved_provider_outcome_unknown"
        assert report["provider_dispatches"] == 0
        assert report["result"] is None
        assert report["reserved_ceiling_usd"] > 0
        return await original_key()

    evaluation.key.side_effect = key_after_reservation
    assert await paid(evaluation) is True
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "completed"
    assert report["provider_dispatches"] == 1
    assert report["result"]["generation"]["usage"]["total_tokens"] == 150
    assert report["usage_based_cost_estimate_usd"] == pytest.approx(0.0008)
    assert report["evaluation_case"]["case_definition_sha256"] == "a" * 64
    assert report["evaluation_case"]["semantic_calibration"] == check.ASSESSMENT_PENDING
    assert report["binding"]["source_sha256"] == "b" * 64
    assert "synthetic_provider_output" not in report
    captured = evaluation.report.read_text() + capsys.readouterr().out
    for text in ("MUST NOT", "EXPECTATION", "mocked-credential"):
        assert text not in captured
    evaluation.engine_call.assert_awaited_once_with(evaluation.prepared, evaluation.client)
    evaluation.completion.assert_awaited_once()
    evaluation.key.assert_awaited_once()
    evaluation.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_engine_dispatch_accepts_official_derived_no_retry_client(evaluation, monkeypatch):
    evaluation.prepared.binding = CheckBinding(
        source_revision_id="synthetic-source", source_sha256="a" * 64,
        extraction_sha256="b" * 64, extraction_version="test", passage_version="test",
        candidate_sha256="c" * 64, brief_sha256="d" * 64,
    )
    evaluation.prepared.timeout_seconds = 120
    evaluation.prepared.targets = {"overview-1:text": "A synthetic statement."}
    evaluation.prepared.item_ids = frozenset({"overview-1"})
    evaluation.prepared.passage_ids = frozenset({"p1_b1_v1"})
    evaluation.prepared.priorities = ""
    evaluation.prepared.source_complete = True
    derived_client = SimpleNamespace(base_url="https://api.openai.com/v1/")
    evaluation.client.with_options = Mock(return_value=derived_client)
    diagnostics = {
        "target_checks": [{"target_id": "overview-1:text", "status": "assessed", "reason": "Synthetic control."}],
        "claim_issues": [], "priority_assessment": {
            "status": "not_stated", "explanation": "No priorities supplied.", "gaps": [],
        }, "limitations": [],
    }
    evaluation.completion.return_value = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            refusal=None, content=json.dumps(diagnostics),
        ))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )
    monkeypatch.setattr(check.engine, "check_review", actual_check_review)
    assert await paid(evaluation) is True
    evaluation.client.with_options.assert_called_once_with(max_retries=0, timeout=120)
    assert evaluation.completion.call_args.args == (derived_client,)
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "completed"
    assert report["provider_dispatches"] == 1
    assert report["result"]["diagnostics"] == diagnostics
    assert report["evaluation_case"]["semantic_calibration"] == check.ASSESSMENT_PENDING


@pytest.mark.asyncio
async def test_missing_key_creates_no_client_and_never_dispatches(evaluation):
    evaluation.key.side_effect = None
    evaluation.key.return_value = None
    assert await paid(evaluation) is False
    assert json.loads(evaluation.report.read_text())["status"] == "no_saved_key_no_call"
    assert not evaluation.opened
    evaluation.engine_call.assert_not_awaited()
    evaluation.completion.assert_not_awaited()
    evaluation.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonstandard_provider_endpoint_never_dispatches(evaluation):
    evaluation.client.base_url = "https://example.invalid/v1/"
    assert await paid(evaluation) is False
    assert json.loads(evaluation.report.read_text())["status"] == "nonstandard_provider_endpoint_no_call"
    evaluation.engine_call.assert_not_awaited()
    evaluation.completion.assert_not_awaited()
    evaluation.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_database_connection_is_not_closed(evaluation, monkeypatch):
    existing = object()
    monkeypatch.setattr(check.DatabaseFactory, "_instance", existing)
    assert await paid(evaluation) is True
    assert check.DatabaseFactory._instance is existing
    evaluation.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_opened_before_key_error_is_closed_without_error_body(evaluation, capsys):
    async def broken_key():
        check.DatabaseFactory._instance = evaluation.database
        raise RuntimeError("PRIVATE KEY OR DATABASE URI")
    evaluation.key.side_effect = broken_key
    assert await paid(evaluation) is False
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "evaluation_interrupted_outcome_unknown"
    assert report["error_type"] == "RuntimeError"
    assert report["provider_dispatches"] == 0
    assert "PRIVATE" not in evaluation.report.read_text() + capsys.readouterr().out
    evaluation.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["additional_option", "mutated_text", "different_client", "second_call", "no_call"])
async def test_dispatch_guard_checks_exact_request_and_only_one_call(evaluation, mode):
    async def changed_engine(prepared, client):
        _, payload = check.request_cost_ceiling(prepared, evaluation.spec)
        kwargs = {name: value for name, value in payload.items() if name != "store"}
        kwargs["validate_output"] = False
        if mode == "no_call":
            return evaluation.result
        if mode == "additional_option":
            kwargs["tools"] = []
        elif mode == "mutated_text":
            kwargs["messages"][1]["content"] = "Changed after budget preparation"
        elif mode == "different_client":
            client = object()
        elif mode == "second_call":
            await check.engine.create_chat_completion(client, **kwargs)
        await check.engine.create_chat_completion(client, **kwargs)
        return evaluation.result
    evaluation.engine_call.side_effect = changed_engine
    assert await paid(evaluation) is False
    assert evaluation.completion.await_count == (1 if mode == "second_call" else 0)
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "evaluation_interrupted_outcome_unknown"
    assert report["reserved_ceiling_usd"] > 0


@pytest.mark.asyncio
async def test_provider_error_keeps_reservation_and_does_not_retry_or_record_body(evaluation, capsys):
    evaluation.completion.side_effect = RuntimeError("PRIVATE PROVIDER REQUEST")
    assert await paid(evaluation) is False
    report = json.loads(evaluation.report.read_text())
    assert report["error_type"] == "RuntimeError"
    assert report["provider_dispatches"] == 1
    assert report["reserved_ceiling_usd"] > 0
    assert "PRIVATE" not in evaluation.report.read_text() + capsys.readouterr().out
    original = evaluation.report.read_text()
    assert await paid(evaluation) is False
    assert evaluation.report.read_text() == original
    evaluation.completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_retains_unknown_reservation(evaluation):
    evaluation.completion.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await paid(evaluation)
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == "reserved_provider_outcome_unknown"
    assert report["provider_dispatches"] == 1
    assert await paid(evaluation) is False
    evaluation.completion.assert_awaited_once()
    evaluation.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "failed"])
async def test_noncomplete_checks_are_not_success_or_automatically_retried(evaluation, status):
    evaluation.result.status = status
    assert await paid(evaluation) is False
    report = json.loads(evaluation.report.read_text())
    assert report["status"] == status
    assert report["result"]["status"] == status
    evaluation.completion.assert_awaited_once()


def test_cli_defaults_to_dry_run_without_budget_or_name(evaluation, monkeypatch):
    runner = AsyncMock(return_value=True)
    monkeypatch.setattr(check, "run_check", runner)
    assert check.main([]) == 0
    runner.assert_awaited_once_with(check.DEFAULT_CASE, run_paid=False, cap_usd=None,
                                    report_name=None, previous_reserved_usd=0)


def test_cli_preflight_exception_displays_type_only(evaluation, monkeypatch, capsys):
    runner = AsyncMock(side_effect=ValueError("PRIVATE SOURCE VALIDATION"))
    monkeypatch.setattr(check, "run_check", runner)
    assert check.main([]) == 1
    text = capsys.readouterr().out
    assert "PRIVATE" not in text
    assert json.loads(text)["error_type"] == "ValueError"
