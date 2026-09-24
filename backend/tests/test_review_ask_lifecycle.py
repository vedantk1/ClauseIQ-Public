"""No paid calls: Ask claims, context isolation, storage limits and restoration."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clauseiq_types.review import (
    ReviewAskAnswerItem, ReviewCoverage, ReviewEvidence, ReviewFailure, ReviewFinding,
    ReviewGeneration, ReviewRun, ReviewUsage, ReviewWorkspaceResponse, ReviewWorkspaceUpdate, StartAskRequest,
)
from middleware.api_standardization import add_api_standardization
from middleware.local_access import local_access_middleware
from routers import review_workspace
from services import review_ask_service as lifecycle
from services.ai.generation import AIRequestError
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService
from tests.test_review_workspace import MemoryDocuments


MODEL = "gpt-6-sol"
WORKSPACE = "local"
SCOPE = {"run_id": "run-1", "finding_id": "finding-1"}


def request(revision=0, request_id="ask-1", model_id=MODEL, question="What does this mean?", include_history=True):
    return StartAskRequest(expected_revision=revision, request_id=request_id, model_id=model_id,
                           question=question, include_history=include_history)


@pytest.fixture
def setup(monkeypatch):
    text = "Synthetic service charges are payable monthly."
    source = {"content_sha256": "a" * 64, "extraction_version": "synthetic-v1", "status": "complete",
              "page_count": 1, "pages": [{"page_number": 1, "status": "extracted", "text": text,
                "spans": [{"id": "span-1", "start": 0, "end": len(text), "text": text}], "warnings": []}],
              "warnings": [], "text": text}
    evidence = ReviewEvidence(source_revision_id="source-1", span_id="span-1", page_number=1, quote=text, label="Payment")
    finding = ReviewFinding(id="finding-1", title="Monthly charges", facts="Monthly charges are due.",
        interpretation="Plan for recurring payment.", uncertainty="No payment calendar calculated.",
        next_step="Check the payment process.", suggested_question="How will invoices be delivered?", evidence=[evidence])
    run = ReviewRun(id="run-1", kind="fixture", source_revision_id="source-1", created_at="synthetic-time",
                    context={"perspective": "customer", "priorities": "Original payment priorities"}, findings=[finding])
    state = ReviewWorkspaceResponse(document_id="doc-1", source_revision_id="source-1", revision=0,
                                    runs=[run], brief={"perspective": "provider", "priorities": "Changed brief"})
    documents = MemoryDocuments({"id": "doc-1", "workspace_id": WORKSPACE, "source_revision_id": "source-1",
        "source_sha256": "a" * 64, "source_status": "stored", "has_pdf_file": True,
        "extraction_status": "complete", "source_extraction": source, "review_workspace": state.model_dump(),
        "clauses": [{"id": "legacy", "text": "Retained legacy analysis"}]})
    documents.get_workspace_generation_settings = AsyncMock(return_value={"model_id": MODEL, "reasoning_effort": "medium"})
    documents.get_workspace_api_key = AsyncMock(return_value="synthetic-client-credential")
    coverage = ReviewCoverage(page_count=1, extracted_pages=[1], omitted_pages=[])
    generation = ReviewGeneration(model_id=MODEL, reasoning_effort="medium", max_completion_tokens=4000,
        catalog_verified_on="test", prompt_version="ask-test-v1", schema_version="ask-test-v1",
        extraction_version="synthetic-v1", estimated_input_tokens=200)
    prepared = SimpleNamespace(generation=generation, coverage=coverage)
    result = SimpleNamespace(status="ready", answer=[ReviewAskAnswerItem(text="Charges recur monthly.", evidence=[evidence])],
        limitations=[], coverage=coverage, generation=generation.model_copy(update={"duration_ms": 1,
            "usage": ReviewUsage(prompt_tokens=200, completion_tokens=50, total_tokens=250)}), failure=None)
    prepare, generate, clients = Mock(return_value=prepared), AsyncMock(return_value=result), []

    @asynccontextmanager
    async def client_context(key):
        assert key == "synthetic-client-credential"
        client = object()
        clients.append(client)
        yield client

    monkeypatch.setattr(lifecycle, "prepare_ask", prepare)
    monkeypatch.setattr(lifecycle, "generate_ask", generate)
    monkeypatch.setattr(lifecycle, "workspace_openai_client", client_context)
    return SimpleNamespace(documents=documents, service=lifecycle.ReviewAskService(documents),
        generate=generate, prepare=prepare, clients=clients, result=result, run=run)


async def start(setup, req=None, run_id="run-1", finding_id="finding-1"):
    return await setup.service.start("doc-1", WORKSPACE, run_id, finding_id, req or request())


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
async def test_ask_snapshots_effort_and_replay_never_adopts_changed_settings(setup):
    setup.documents.get_workspace_generation_settings.return_value["reasoning_effort"] = "max"
    setup.prepare.return_value.generation.reasoning_effort = "max"
    setup.result.generation.reasoning_effort = "max"
    req = request().model_copy(update={"reasoning_effort": "max"})
    state = await start(setup, req)
    assert setup.prepare.call_args.kwargs["reasoning_effort"] == "max"
    assert state.ask_turns[0].generation.reasoning_effort == "max"
    setup.documents.get_workspace_generation_settings.return_value["reasoning_effort"] = "low"
    assert (await start(setup, req)).ask_turns[0].generation.reasoning_effort == "max"
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup, req.model_copy(update={"reasoning_effort": "low"}))
    assert caught.value.code == "REQUEST_ID_CONFLICT"
    setup.generate.assert_awaited_once()


async def change(setup, revision, kind, **values):
    return await setup.service.update("doc-1", WORKSPACE, ReviewWorkspaceUpdate(
        expected_revision=revision, operation={"type": kind, **values}))


@pytest.mark.asyncio
async def test_claim_precedes_provider_replay_and_reopen_are_key_free(setup):
    async def generate(prepared, client):
        stored = await setup.service.read("doc-1", WORKSPACE)
        assert stored.revision == 1 and stored.ask_turns[0].status == "processing"
        assert stored.ask_turns[0].question == request().question
        assert client is setup.clients[0]
        return setup.result
    setup.generate.side_effect = generate
    final = await start(setup)
    assert final.revision == 2 and final.ask_turns[0].status == "ready"
    assert final.ask_turns[0].completed_at and final.ask_turns[0].generation.usage.total_tokens == 250
    assert final.runs[0] == setup.run and final.personal == {}
    assert setup.prepare.call_args.args[1] == setup.run
    assert setup.prepare.call_args.args[1].context.priorities == "Original payment priorities"
    assert final.brief.priorities == "Changed brief"
    setup.documents.get_workspace_api_key.reset_mock()
    setup.documents.get_workspace_generation_settings.reset_mock()
    setup.documents.get_workspace_api_key.return_value = None
    assert await start(setup) == final
    assert await ReviewWorkspaceService(setup.documents).read("doc-1", WORKSPACE) == final
    setup.documents.get_workspace_generation_settings.assert_not_awaited()
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("question", "Different question"), ("model_id", "other"), ("include_history", False),
                                           ("run_id", "run-2"), ("finding_id", "finding-2")])
async def test_reused_id_cannot_disguise_changed_request(setup, field, value):
    await start(setup)
    values = {field: value}
    scope = {key: values.pop(key) for key in ("run_id", "finding_id") if key in values}
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup, request(**values), **scope)
    assert caught.value.code == "REQUEST_ID_CONFLICT"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_separate_ask_draft_question_markers_and_concurrent_edits_survive(setup):
    current = await change(setup, 0, "set_draft", **SCOPE, text="Draft negotiation wording")
    current = await change(setup, current.revision, "save_question", **SCOPE, text="My saved question")
    current = await change(setup, current.revision, "set_ask_draft", **SCOPE, text="Unfinished Ask")
    async def generate(*_):
        state = await setup.service.read("doc-1", WORKSPACE)
        state = await change(setup, state.revision, "set_ask_draft", **SCOPE, text="Newer unsent Ask")
        state = await change(setup, state.revision, "set_marker", **SCOPE, marker="revisit")
        await change(setup, state.revision, "set_brief", brief={"perspective": "provider", "priorities": "Even newer"})
        return setup.result
    setup.generate.side_effect = generate
    final = await start(setup, request(current.revision))
    personal = final.personal["run-1"]
    assert personal.ask_drafts["finding-1"] == "Newer unsent Ask"
    assert personal.drafts["finding-1"] == "Draft negotiation wording"
    assert personal.saved_questions["finding-1"].text == "My saved question"
    assert personal.markers["finding-1"] == "revisit"
    assert final.runs[0] == setup.run and final.brief.priorities == "Even newer"


@pytest.mark.asyncio
async def test_history_is_bounded_and_fresh_question_starts_new_chain(setup):
    state = await start(setup)
    for index in range(2, 9):
        state = await start(setup, request(state.revision, f"ask-{index}"))
    assert state.ask_turns[-1].history_turn_ids == [f"ask-{index}" for index in range(2, 8)]
    assert state.ask_turns[-1].history_truncated
    assert [turn.id for turn in setup.prepare.call_args.args[-1]] == state.ask_turns[-1].history_turn_ids
    state = await start(setup, request(state.revision, "fresh", include_history=False))
    assert state.ask_turns[-1].history_turn_ids == [] and not state.ask_turns[-1].history_truncated
    assert setup.prepare.call_args.args[-1] == []
    state = await start(setup, request(state.revision, "followup"))
    assert state.ask_turns[-1].history_turn_ids == ["fresh"] and not state.ask_turns[-1].history_truncated


@pytest.mark.asyncio
async def test_history_excludes_other_findings_runs_and_unusable_attempts(setup):
    first = await start(setup)
    raw = setup.documents.document["review_workspace"]
    raw["runs"][0]["findings"].append({**raw["runs"][0]["findings"][0], "id": "other-finding"})
    raw["runs"].append({**raw["runs"][0], "id": "other-run"})
    state = await start(setup, request(first.revision, "other-finding-question"), finding_id="other-finding")
    assert state.ask_turns[-1].history_turn_ids == []
    state = await start(setup, request(state.revision, "other-run-question"), run_id="other-run")
    assert state.ask_turns[-1].history_turn_ids == []
    setup.generate.side_effect = RuntimeError("PRIVATE")
    state = await start(setup, request(state.revision, "failed"))
    setup.generate.side_effect = None
    state = await start(setup, request(state.revision, "followup"))
    assert state.ask_turns[-1].history_turn_ids == ["ask-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id,workspace_id,run_id,finding_id,code", [
    ("other", WORKSPACE, "run-1", "finding-1", "DOCUMENT_NOT_FOUND"),
    ("doc-1", "other", "run-1", "finding-1", "DOCUMENT_NOT_FOUND"),
    ("doc-1", WORKSPACE, "missing", "finding-1", "RUN_NOT_FOUND"),
    ("doc-1", WORKSPACE, "run-1", "missing", "FINDING_NOT_FOUND"),
])
async def test_scope_is_checked_before_key_or_model_access(setup, document_id, workspace_id, run_id, finding_id, code):
    with pytest.raises(ReviewWorkspaceError) as caught:
        await setup.service.start(document_id, workspace_id, run_id, finding_id, request())
    assert caught.value.code == code
    setup.documents.get_workspace_generation_settings.assert_not_awaited()
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_revision_model_input_and_credentials_do_not_claim(setup):
    for req, code in [(request(9), "REVISION_CONFLICT"), (request(model_id="other"), "REVIEW_MODEL_CHANGED"),
                      (request().model_copy(update={"question": "  "}), "INVALID_QUESTION")]:
        with pytest.raises(ReviewWorkspaceError) as caught:
            await start(setup, req)
        assert caught.value.code == code
    setup.prepare.side_effect = AIRequestError("Full source exceeds supported input.", 400)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "ASK_INPUT_REJECTED"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.prepare.side_effect = None
    setup.documents.get_workspace_api_key.return_value = None
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "API_KEY_REQUIRED"
    assert setup.documents.writes == []
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_unconfirmed_claim_never_dispatches(setup, uncertain):
    setup.documents.fail, setup.documents.lose_confirmation = not uncertain, uncertain
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    setup.generate.assert_not_awaited()
    if uncertain:
        setup.documents.lose_confirmation = False
        assert (await start(setup)).ask_turns[0].status == "processing"
        setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_parallel_identical_submissions_dispatch_once(setup):
    states = await asyncio.gather(start(setup), start(setup))
    assert all(len(state.ask_turns) == 1 for state in states)
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_parallel_changed_payload_same_id_conflicts(setup):
    states = await asyncio.gather(start(setup), start(setup, request(question="Different")), return_exceptions=True)
    assert sum(not isinstance(state, Exception) for state in states) == 1
    error = next(state for state in states if isinstance(state, Exception))
    assert isinstance(error, ReviewWorkspaceError) and error.code == "REQUEST_ID_CONFLICT"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_processing_blocks_new_question_and_interrupt_is_free(setup):
    async def generate(*_):
        with pytest.raises(ReviewWorkspaceError) as caught:
            await start(setup, request(1, "ask-2"))
        assert caught.value.code == "ASK_ALREADY_PROCESSING"
        assert (await start(setup)).ask_turns[0].status == "processing"
        return_state = await setup.service.interrupt("doc-1", WORKSPACE, "ask-1", 1)
        assert return_state.ask_turns[0].status == "interrupted"
        return setup.result
    setup.generate.side_effect = generate
    state = await start(setup)
    assert state.ask_turns[0].status == "interrupted" and state.ask_turns[0].answer == []
    assert state.ask_turns[0].generation.usage is None
    assert await setup.service.interrupt("doc-1", WORKSPACE, "ask-1", 0) == state
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_after_claim_prevents_dispatch(setup):
    update = setup.documents.update_document_if
    async def intercept(document_id, workspace_id, expected, values):
        saved = await update(document_id, workspace_id, expected, values)
        if saved and values["review_workspace"]["ask_turns"][0]["status"] == "processing":
            await setup.service.interrupt(document_id, workspace_id, "ask-1", 1)
        return saved
    setup.documents.update_document_if = intercept
    state = await start(setup)
    assert state.ask_turns[0].status == "interrupted"
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_answer_cannot_be_interrupted(setup):
    state = await start(setup)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await setup.service.interrupt("doc-1", WORKSPACE, "ask-1", state.revision)
    assert caught.value.code == "ASK_NOT_PROCESSING"


@pytest.mark.asyncio
async def test_provider_exception_is_safe_and_never_retried(setup, caplog):
    setup.generate.side_effect = RuntimeError("PRIVATE DOCUMENT AND CREDENTIAL")
    state = await start(setup)
    assert state.ask_turns[0].status == "failed"
    assert state.ask_turns[0].failure.code == "ASK_GENERATION_FAILED"
    assert "PRIVATE DOCUMENT" not in str(state) + caplog.text
    assert await start(setup) == state
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_incomplete_with_coverage_limitations_persists(setup):
    setup.result.status = "incomplete"
    setup.result.coverage = setup.result.coverage.model_copy(update={"limitations": ["Known source limitation"]})
    setup.result.failure = ReviewFailure(code="ASK_EVIDENCE_INVALID", message="Some references were unavailable.")
    state = await start(setup)
    assert state.ask_turns[0].status == "incomplete"
    assert state.ask_turns[0].coverage.limitations == ["Known source limitation"]


@pytest.mark.asyncio
async def test_cancellation_leaves_unknown_attempt_without_replay(setup):
    setup.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await start(setup)
    state = await start(setup)
    assert state.ask_turns[0].status == "processing"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_kind", ["delete", "revision", "hash", "extraction", "run", "finding"])
async def test_late_result_never_attaches_to_changed_source_or_run(setup, change_kind):
    async def generate(*_):
        document = setup.documents.document
        if change_kind == "delete":
            setup.documents.document = None
        elif change_kind == "revision":
            document["source_revision_id"] = "new-source"
        elif change_kind == "hash":
            document["source_sha256"] = "b" * 64
        elif change_kind == "extraction":
            document["source_extraction"]["extraction_version"] = "new-extraction"
        elif change_kind == "run":
            document["review_workspace"]["runs"][0]["context"]["priorities"] = "Changed snapshot"
        else:
            document["review_workspace"]["runs"][0]["findings"][0]["facts"] = "Changed finding"
        return setup.result
    setup.generate.side_effect = generate
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == ("DOCUMENT_NOT_FOUND" if change_kind == "delete" else
                                  "ASK_REVIEW_CHANGED" if change_kind in ("run", "finding") else "REVIEW_SOURCE_CHANGED")
    assert len(setup.documents.writes) == 1


@pytest.mark.asyncio
async def test_final_cas_preserves_an_intervening_edit(setup):
    original = setup.documents.update_document_if
    edited = False
    async def update(document_id, workspace_id, expected, values):
        nonlocal edited
        if values["review_workspace"]["ask_turns"][0]["status"] == "ready" and not edited:
            edited = True
            state = await setup.service.read(document_id, workspace_id)
            await change(setup, state.revision, "set_ask_draft", **SCOPE, text="Newer draft")
        return await original(document_id, workspace_id, expected, values)
    setup.documents.update_document_if = update
    state = await start(setup)
    assert state.revision == 3 and state.personal["run-1"].ask_drafts["finding-1"] == "Newer draft"
    assert state.ask_turns[0].status == "ready"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_final_cas_conflicts_are_bounded(setup):
    original = setup.documents.update_document_if
    attempts = 0
    async def update(document_id, workspace_id, expected, values):
        nonlocal attempts
        if values["review_workspace"]["ask_turns"][0]["status"] == "ready":
            attempts += 1
            return False
        return await original(document_id, workspace_id, expected, values)
    setup.documents.update_document_if = update
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED" and attempts == lifecycle.FINAL_SAVE_ATTEMPTS
    assert (await start(setup)).ask_turns[0].status == "processing"
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_lost_final_write_does_not_recharge(setup, uncertain):
    async def generate(*_):
        setup.documents.fail, setup.documents.lose_confirmation = not uncertain, uncertain
        return setup.result
    setup.generate.side_effect = generate
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    setup.documents.fail = setup.documents.lose_confirmation = False
    state = await start(setup)
    assert state.ask_turns[0].status == ("ready" if uncertain else "processing")
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_headroom_is_checked_before_credentials(setup, monkeypatch):
    monkeypatch.setenv("REVIEW_ASK_MAX_STORAGE_BYTES", "1000")
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "ASK_STORAGE_LIMIT"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.documents.get_workspace_generation_settings.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_whole_document_limit_precedes_paid_work(setup, monkeypatch):
    monkeypatch.setattr(lifecycle, "MAX_DOCUMENT_STORAGE_BYTES", 100_000)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "ASK_STORAGE_LIMIT"
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_result_keeps_usage_without_partial_answer(setup, monkeypatch):
    async def generate(*_):
        monkeypatch.setattr(lifecycle, "MAX_ASK_RESULT_BYTES", 10)
        return setup.result
    setup.generate.side_effect = generate
    state = await start(setup)
    turn = state.ask_turns[0]
    assert turn.status == "incomplete" and turn.answer == []
    assert turn.failure.code == "ASK_RESULT_TOO_LARGE" and turn.generation.usage.total_tokens == 250
    assert await start(setup) == state


@pytest.mark.asyncio
async def test_storage_exhaustion_after_dispatch_is_not_a_preflight_rejection(setup, monkeypatch):
    async def generate(*_):
        monkeypatch.setenv("REVIEW_ASK_MAX_STORAGE_BYTES", "1")
        return setup.result
    setup.generate.side_effect = generate
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup)
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    assert "charges may apply" in str(caught.value)
    state = await setup.service.read("doc-1", WORKSPACE)
    assert state.ask_turns[0].status == "processing"
    assert await start(setup) == state
    setup.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_turn_limit_preserves_all_old_work(setup):
    state = await start(setup)
    state.ask_turns = [state.ask_turns[0].model_copy(update={"id": f"old-{index}"}, deep=True) for index in range(100)]
    setup.documents.document["review_workspace"] = state.model_dump()
    setup.documents.get_workspace_api_key.reset_mock()
    before = deepcopy(setup.documents.document)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await start(setup, request(state.revision, "new"))
    assert caught.value.code == "ASK_TURN_LIMIT" and setup.documents.document == before
    setup.documents.get_workspace_api_key.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["source", "run", "finding", "history", "quote", "anchor", "draft"])
async def test_stored_ask_scope_and_exact_citations_fail_closed(setup, corruption):
    await start(setup)
    state = setup.documents.document["review_workspace"]
    turn = state["ask_turns"][0]
    if corruption == "source": turn["source_revision_id"] = "other-source"
    elif corruption == "run": turn["run_id"] = "other-run"
    elif corruption == "finding": turn["finding_id"] = "other-finding"
    elif corruption == "history": turn["history_turn_ids"] = ["ask-1"]
    elif corruption == "quote": turn["answer"][0]["evidence"][0]["quote"] = "Altered quote"
    elif corruption == "anchor": turn["answer"][0]["evidence"][0]["span_id"] = "missing-anchor"
    else: state["personal"]["run-1"] = {"ask_drafts": {"missing-finding": "Draft"}}
    before = deepcopy(setup.documents.document)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await setup.service.read("doc-1", WORKSPACE)
    assert caught.value.code == "REVIEW_STATE_INVALID" and setup.documents.document == before


@pytest.mark.asyncio
async def test_old_workspace_defaults_are_read_only(setup):
    setup.documents.document["review_workspace"].pop("ask_turns")
    before = deepcopy(setup.documents.document)
    state = await setup.service.read("doc-1", WORKSPACE)
    assert state.ask_turns == [] and setup.documents.document == before and setup.documents.writes == []


def test_http_start_interrupt_and_safe_error_contract(setup, monkeypatch):
    monkeypatch.setattr(review_workspace, "get_document_service", lambda: setup.documents)
    app = add_api_standardization(FastAPI())
    app.include_router(review_workspace.router, prefix="/api/v1")
    client = TestClient(app)
    base = "/api/v1/documents/doc-1/review-workspace"
    path = base + "/runs/run-1/findings/finding-1/ask"
    invalid = client.post(path, json={**request().model_dump(), "workspace_id": "PRIVATE OVERRIDE"})
    assert invalid.status_code == 422 and "PRIVATE OVERRIDE" not in invalid.text
    changed = client.post(path, json=request(model_id="other").model_dump())
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "REVIEW_MODEL_CHANGED"
    response = client.post(path, json=request().model_dump())
    assert response.status_code == 200 and response.json()["data"]["ask_turns"][0]["status"] == "ready"
    assert client.post(path, json=request().model_dump()).json()["data"] == response.json()["data"]
    assert "synthetic-client-credential" not in response.text
    interrupted = client.post(base + "/ask/ask-1/interrupt", json={"expected_revision": 2})
    assert interrupted.status_code == 409 and interrupted.json()["error"]["code"] == "ASK_NOT_PROCESSING"
    setup.generate.assert_awaited_once()


@pytest.mark.parametrize("suffix,body", [
    ("/runs/run-1/findings/finding-1/ask", request().model_dump()),
    ("/ask/ask-1/interrupt", {"expected_revision": 0}),
])
@pytest.mark.parametrize("headers", [{}, {"X-ClauseIQ-Local": "1", "Origin": "https://untrusted.example"},
                                      {"X-ClauseIQ-Local": "1", "Host": "localhost.untrusted.example"}])
def test_ask_routes_preserve_local_browser_boundary(setup, monkeypatch, suffix, body, headers):
    monkeypatch.setattr(review_workspace, "get_document_service", lambda: setup.documents)
    app = add_api_standardization(FastAPI())
    app.middleware("http")(local_access_middleware(["http://localhost:3000"]))
    app.include_router(review_workspace.router, prefix="/api/v1")
    client = TestClient(app, base_url="http://localhost:8000")
    response = client.post("/api/v1/documents/doc-1/review-workspace" + suffix, headers=headers, json=body)
    assert response.status_code == 403 and response.json()["error"]["code"] == "LOCAL_ACCESS_REQUIRED"
    assert setup.documents.writes == []
    setup.documents.get_workspace_api_key.assert_not_awaited()
    setup.generate.assert_not_awaited()


def test_local_ask_and_key_free_reopen_through_routes(setup, monkeypatch):
    monkeypatch.setattr(review_workspace, "get_document_service", lambda: setup.documents)
    app = add_api_standardization(FastAPI())
    app.middleware("http")(local_access_middleware(["http://localhost:3000"]))
    app.include_router(review_workspace.router, prefix="/api/v1")
    client = TestClient(app, base_url="http://localhost:8000")
    base = "/api/v1/documents/doc-1/review-workspace"
    headers = {"X-ClauseIQ-Local": "1", "Origin": "http://localhost:3000"}
    response = client.post(base + "/runs/run-1/findings/finding-1/ask", headers=headers, json=request().model_dump())
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    setup.documents.get_workspace_api_key.reset_mock()
    reopened = client.get(base, headers=headers)
    assert reopened.status_code == 200 and reopened.json()["data"] == response.json()["data"]
    setup.documents.get_workspace_api_key.assert_not_awaited()
