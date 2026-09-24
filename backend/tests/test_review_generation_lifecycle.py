"""No paid calls: persisted claim, idempotency, recovery and scoped finalization."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clauseiq_types.review import (
    ReviewCoverage, ReviewEvidence, ReviewFailure, ReviewFinding, ReviewGeneration,
    ReviewOverviewItem, ReviewWorkspaceUpdate, StartReviewRequest,
)
from middleware.api_standardization import add_api_standardization
from routers import review_workspace
from services import review_generation_service as lifecycle
from services.ai.generation import AIRequestError
from services.review_workspace_service import ReviewWorkspaceError
from tests.test_review_workspace import MemoryDocuments


MODEL = "gpt-6-sol"
WORKSPACE = "local"


def request(revision=0, request_id="attempt-1", model_id=MODEL):
    return StartReviewRequest(expected_revision=revision, request_id=request_id, model_id=model_id)


@pytest.fixture
def setup(monkeypatch):
    text = "Synthetic service charges are payable monthly."
    source = {"content_sha256": "a" * 64, "extraction_version": "synthetic-v1", "status": "complete",
              "page_count": 1, "pages": [{"page_number": 1, "status": "extracted", "text": text,
                "spans": [{"id": "span-1", "start": 0, "end": len(text), "text": text}], "warnings": []}],
              "warnings": [], "text": text}
    documents = MemoryDocuments({"id": "doc-1", "workspace_id": WORKSPACE, "source_revision_id": "source-1",
        "source_sha256": "a" * 64, "source_status": "stored", "has_pdf_file": True,
        "extraction_status": "complete", "source_extraction": source,
        "clauses": [{"id": "legacy", "text": "Retained legacy analysis"}]})
    documents.get_workspace_generation_settings = AsyncMock(return_value={"model_id": MODEL, "reasoning_effort": "medium"})
    documents.get_workspace_api_key = AsyncMock(return_value="synthetic-client-credential")
    coverage = ReviewCoverage(page_count=1, extracted_pages=[1], omitted_pages=[])
    generation = ReviewGeneration(model_id=MODEL, reasoning_effort="low", max_completion_tokens=1000,
        catalog_verified_on="test", prompt_version="review-test-v1", schema_version="review-test-v1",
        extraction_version="synthetic-v1", estimated_input_tokens=200)
    prepared = SimpleNamespace(generation=generation, coverage=coverage)
    evidence = ReviewEvidence(source_revision_id="source-1", span_id="span-1", page_number=1, quote=text, label="Payment")
    result = SimpleNamespace(status="ready", overview_items=[ReviewOverviewItem(text="Monthly service charges", evidence=[evidence])],
        findings=[ReviewFinding(id="finding-1", title="Monthly charges", facts="Monthly charges are due.",
            interpretation="Plan for recurring payment.", uncertainty="No payment calendar calculated.",
            next_step="Check the payment process.", suggested_question="How will invoices be delivered?", evidence=[evidence])],
        coverage=coverage, generation=generation.model_copy(update={"duration_ms": 1}), failure=None)
    prepare = Mock(return_value=prepared)
    generate = AsyncMock(return_value=result)
    clients = []

    @asynccontextmanager
    async def client_context(key):
        assert key == "synthetic-client-credential"
        client = object()
        clients.append(client)
        yield client

    monkeypatch.setattr(lifecycle, "prepare_review", prepare)
    monkeypatch.setattr(lifecycle, "generate_review", generate)
    monkeypatch.setattr(lifecycle, "workspace_openai_client", client_context)
    return SimpleNamespace(documents=documents, service=lifecycle.ReviewGenerationService(documents),
        generate=generate, prepare=prepare, clients=clients, result=result)


async def start(setup, req=None):
    return await setup.service.start("doc-1", WORKSPACE, req or request())


@pytest.mark.asyncio
async def test_stale_effort_rejected_before_key_claim_or_provider(setup):
    setup.documents.get_workspace_generation_settings.return_value["reasoning_effort"] = "high"
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_REASONING_CHANGED"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.prepare.assert_not_called()
    setup.generate.assert_not_awaited()
    assert setup.documents.writes == []


@pytest.mark.asyncio
async def test_selected_effort_passes_to_preparation_and_saved_attribution(setup):
    setup.documents.get_workspace_generation_settings.return_value["reasoning_effort"] = "max"
    setup.prepare.return_value.generation.reasoning_effort = "max"
    setup.result.generation.reasoning_effort = "max"
    req = request().model_copy(update={"reasoning_effort": "max"})
    state = await start(setup, req)
    assert setup.prepare.call_args.args[-1] == "max"
    assert state.runs[0].generation.reasoning_effort == "max"
    setup.documents.get_workspace_generation_settings.return_value["reasoning_effort"] = "low"
    assert (await start(setup, req)).runs[0].generation.reasoning_effort == "max"
    setup.generate.assert_awaited_once()


async def brief(setup, revision, priorities):
    return await setup.service.update("doc-1", WORKSPACE, ReviewWorkspaceUpdate(
        expected_revision=revision, operation={"type": "set_brief", "brief": {"perspective": "customer", "priorities": priorities}},
    ))


@pytest.mark.asyncio
async def test_processing_claim_precedes_provider_and_terminal_replay_is_free(setup):
    async def generate(prepared, client):
        stored = await setup.service.read("doc-1", WORKSPACE)
        assert stored.revision == 1 and stored.runs[0].status == "processing"
        assert stored.runs[0].generation == prepared.generation
        assert client is setup.clients[0]
        return setup.result
    setup.generate.side_effect = generate
    final = await start(setup)
    assert final.revision == 2 and final.runs[0].status == "ready"
    assert final.runs[0].completed_at
    assert final.runs[0].context.perspective == "neutral"
    assert final.runs[0].generation.prompt_version == "review-test-v1"
    assert final.personal["attempt-1"].saved_questions == {}
    assert setup.documents.document["clauses"][0]["id"] == "legacy"
    assert await start(setup, request(0, model_id="changed-model")) == final
    assert len(setup.clients) == 1
    setup.generate.assert_awaited_once()
    setup.documents.get_workspace_api_key.assert_awaited_once()


@pytest.mark.asyncio
async def test_brief_snapshot_is_immutable_and_edits_during_generation_survive(setup):
    before = await brief(setup, 0, "First priorities")
    async def generate(*_):
        await brief(setup, 2, "Newer priorities")
        return setup.result
    setup.generate.side_effect = generate
    final = await start(setup, request(before.revision))
    assert final.revision == 4
    assert final.brief.priorities == "Newer priorities"
    assert final.runs[0].context.priorities == "First priorities"


@pytest.mark.asyncio
async def test_existing_personal_work_and_completed_runs_survive_new_attempt(setup):
    initial = await start(setup)
    first_run = initial.runs[0].model_copy(deep=True)
    edited = await setup.service.update("doc-1", WORKSPACE, ReviewWorkspaceUpdate(expected_revision=2,
        operation={"type": "save_question", "run_id": "attempt-1", "finding_id": "finding-1", "text": "Retained question"}))
    next_state = await start(setup, request(edited.revision, "attempt-2"))
    assert next_state.runs[0] == first_run and len(next_state.runs) == 2
    assert next_state.personal["attempt-1"].saved_questions["finding-1"].text == "Retained question"
    assert next_state.personal["attempt-2"].saved_questions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id,workspace_id", [("other", WORKSPACE), ("doc-1", "other")])
async def test_scope_rejected_before_model_key_or_provider_access(setup, document_id, workspace_id):
    with pytest.raises(ReviewWorkspaceError) as caught:
        await setup.service.start(document_id, workspace_id, request())
    assert caught.value.code == "DOCUMENT_NOT_FOUND"
    setup.documents.get_workspace_generation_settings.assert_not_awaited()
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,code", [("source_revision_id", None, "SOURCE_REVISION_REQUIRED"),
    ("has_pdf_file", False, "SOURCE_NOT_AVAILABLE"), ("source_status", "storage_failed", "SOURCE_NOT_AVAILABLE")])
async def test_unavailable_source_rejected_before_credentials(setup, field, value, code):
    setup.documents.document[field] = value
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == code
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_revision_or_model_does_not_claim_or_charge(setup):
    await brief(setup, 0, "New priorities")
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVISION_CONFLICT"
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup, request(1, model_id="gpt-6-astra"))
    assert caught.value.code == "REVIEW_MODEL_CHANGED"
    assert len(setup.documents.writes) == 1
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_input_guard_and_missing_key_do_not_create_attempts(setup):
    setup.prepare.side_effect = AIRequestError("The full source exceeds the input limit.", 400)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_INPUT_REJECTED"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.prepare.side_effect = None
    setup.documents.get_workspace_api_key.return_value = None
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "API_KEY_REQUIRED"
    assert setup.documents.writes == [] and setup.clients == []


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_unconfirmed_claim_never_calls_provider_even_when_write_landed(setup, uncertain):
    setup.documents.fail = not uncertain
    setup.documents.lose_confirmation = uncertain
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    setup.generate.assert_not_awaited()
    assert setup.clients == []
    if uncertain:
        setup.documents.lose_confirmation = False
        replay = await start(setup)
        assert replay.runs[0].status == "processing"
        setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_parallel_same_id_submissions_make_only_one_call(setup):
    results = await asyncio.gather(start(setup), start(setup))
    assert all(len(result.runs) == 1 for result in results)
    setup.generate.assert_awaited_once()
    assert (await setup.service.read("doc-1", WORKSPACE)).runs[0].status == "ready"


@pytest.mark.asyncio
async def test_interrupt_after_claim_before_dispatch_prevents_provider_call(setup):
    original = setup.documents.update_document_if
    async def update(document_id, workspace_id, expected, values):
        saved = await original(document_id, workspace_id, expected, values)
        if saved and values["review_workspace"]["runs"][0]["status"] == "processing":
            state = await setup.service.read(document_id, workspace_id)
            await setup.service.interrupt(document_id, workspace_id, "attempt-1", state.revision)
        return saved
    setup.documents.update_document_if = update
    final = await start(setup)
    assert final.runs[0].status == "interrupted"
    setup.generate.assert_not_awaited()
    assert setup.clients == []


@pytest.mark.asyncio
async def test_parallel_different_attempt_ids_have_one_paid_winner(setup):
    results = await asyncio.gather(start(setup), start(setup, request(request_id="attempt-2")), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    conflict = next(result for result in results if isinstance(result, Exception))
    assert isinstance(conflict, ReviewWorkspaceError) and conflict.code == "REVISION_CONFLICT"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_processing_blocks_new_id_replay_and_recovery_are_key_free(setup):
    async def generate(*_):
        setup.documents.get_workspace_api_key.reset_mock()
        replay = await start(setup, request(0))
        assert replay.runs[0].status == "processing"
        with pytest.raises(ReviewWorkspaceError) as caught:
            await start(setup, request(1, "attempt-2"))
        assert caught.value.code == "REVIEW_ALREADY_PROCESSING"
        interrupted = await setup.service.interrupt("doc-1", WORKSPACE, "attempt-1", 1)
        assert interrupted.runs[0].status == "interrupted"
        setup.documents.get_workspace_api_key.assert_not_awaited()
        return setup.result
    setup.generate.side_effect = generate
    final = await start(setup)
    assert final.runs[0].status == "interrupted" and final.runs[0].findings == []
    assert final.runs[0].generation.duration_ms is None
    assert "does not cancel" in final.runs[0].failure.message
    assert await setup.service.interrupt("doc-1", WORKSPACE, "attempt-1", 0) == final


@pytest.mark.asyncio
async def test_terminal_runs_cannot_be_interrupted(setup):
    initial = await start(setup)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await setup.service.interrupt("doc-1", WORKSPACE, "attempt-1", initial.revision)
    assert caught.value.code == "REVIEW_NOT_PROCESSING"
    assert await setup.service.read("doc-1", WORKSPACE) == initial


@pytest.mark.asyncio
async def test_provider_exception_persists_safe_failure_without_retry(setup, caplog):
    setup.generate.side_effect = RuntimeError("PRIVATE DOCUMENT AND SECRET")
    final = await start(setup)
    assert final.runs[0].status == "failed" and final.runs[0].failure.code == "REVIEW_GENERATION_FAILED"
    assert final.runs[0].findings == []
    assert "PRIVATE DOCUMENT" not in str(final) + caplog.text
    assert await start(setup) == final
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_incomplete_state_and_coverage_persist(setup):
    setup.result.status = "incomplete"
    setup.result.failure = ReviewFailure(code="EVIDENCE_INVALID", message="Some generated references could not be matched.")
    final = await start(setup)
    assert final.runs[0].status == "incomplete" and final.runs[0].failure.code == "EVIDENCE_INVALID"
    assert final.runs[0].coverage == setup.result.coverage


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_lost_final_save_cannot_replay_paid_work(setup, uncertain):
    async def generate(*_):
        setup.documents.fail = not uncertain
        setup.documents.lose_confirmation = uncertain
        return setup.result
    setup.generate.side_effect = generate
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    setup.documents.fail = False
    setup.documents.lose_confirmation = False
    replay = await start(setup)
    assert replay.runs[0].status == ("ready" if uncertain else "processing")
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_cancellation_leaves_durable_unknown_attempt_no_replay(setup):
    setup.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await start(setup)
    recovered = await lifecycle.ReviewGenerationService(setup.documents).start("doc-1", WORKSPACE, request())
    assert recovered.runs[0].status == "processing"
    setup.generate.assert_awaited_once()
    recovered = await setup.service.interrupt("doc-1", WORKSPACE, "attempt-1", recovered.revision)
    setup.generate.side_effect = None
    next_state = await start(setup, request(recovered.revision, "attempt-2"))
    assert [run.status for run in next_state.runs] == ["interrupted", "ready"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "revision", "hash", "extraction"])
async def test_late_result_does_not_resurrect_or_attach_to_changed_source(setup, change):
    async def generate(*_):
        if change == "delete":
            setup.documents.document = None
        elif change == "revision":
            setup.documents.document["source_revision_id"] = "replacement-source"
        elif change == "hash":
            setup.documents.document["source_sha256"] = "b" * 64
        else:
            setup.documents.document["source_extraction"]["extraction_version"] = "replacement-extractor"
        return setup.result
    setup.generate.side_effect = generate
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == ("DOCUMENT_NOT_FOUND" if change == "delete" else "REVIEW_SOURCE_CHANGED")
    assert len(setup.documents.writes) == 1


@pytest.mark.asyncio
async def test_finalization_retries_only_cas_and_preserves_intervening_edit(setup):
    original = setup.documents.update_document_if
    conflict_done = False
    async def update(document_id, workspace_id, expected, values):
        nonlocal conflict_done
        run = values["review_workspace"]["runs"][0]
        if run["status"] == "ready" and not conflict_done:
            conflict_done = True
            state = await setup.service.read(document_id, workspace_id)
            await brief(setup, state.revision, "Concurrent retained edit")
        return await original(document_id, workspace_id, expected, values)
    setup.documents.update_document_if = update
    final = await start(setup)
    assert final.brief.priorities == "Concurrent retained edit" and final.runs[0].status == "ready"
    assert final.revision == 3
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalization_conflicts_are_bounded_and_never_retry_provider(setup):
    original = setup.documents.update_document_if
    count = 0
    async def update(document_id, workspace_id, expected, values):
        nonlocal count
        if values["review_workspace"]["runs"][0]["status"] == "ready":
            count += 1
            return False
        return await original(document_id, workspace_id, expected, values)
    setup.documents.update_document_if = update
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    assert count == lifecycle.FINAL_SAVE_ATTEMPTS
    assert (await setup.service.read("doc-1", WORKSPACE)).runs[0].status == "processing"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_limit_precedes_credentials_and_paid_calls(setup):
    final = await start(setup)
    run = final.runs[0]
    final.runs = [run.model_copy(update={"id": f"old-{index}"}, deep=True) for index in range(100)]
    final.personal = {}
    setup.documents.document["review_workspace"] = final.model_dump()
    setup.documents.get_workspace_api_key.reset_mock()
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup, request(final.revision, "new"))
    assert caught.value.code == "REVIEW_RUN_LIMIT"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_awaited_once()


def test_http_start_interrupt_and_safe_error_contract(setup, monkeypatch):
    monkeypatch.setattr(review_workspace, "get_document_service", lambda: setup.documents)
    app = add_api_standardization(FastAPI())
    app.include_router(review_workspace.router, prefix="/api/v1")
    client = TestClient(app)
    path = "/api/v1/documents/doc-1/review-workspace"
    invalid = client.post(path + "/generate", json={**request().model_dump(), "workspace_id": "PRIVATE OVERRIDE"})
    assert invalid.status_code == 422 and "PRIVATE OVERRIDE" not in invalid.text
    changed = client.post(path + "/generate", json=request(model_id="other").model_dump())
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "REVIEW_MODEL_CHANGED"
    response = client.post(path + "/generate", json=request().model_dump())
    assert response.status_code == 200 and response.json()["data"]["runs"][0]["status"] == "ready"
    replay = client.post(path + "/generate", json=request().model_dump())
    assert replay.json()["data"] == response.json()["data"]
    interrupt = client.post(path + "/runs/attempt-1/interrupt", json={"expected_revision": 2})
    assert interrupt.status_code == 409 and interrupt.json()["error"]["code"] == "REVIEW_NOT_PROCESSING"
    assert "synthetic-client-credential" not in response.text
    setup.generate.assert_awaited_once()
