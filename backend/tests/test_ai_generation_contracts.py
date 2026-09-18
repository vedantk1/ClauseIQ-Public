"""Offline contracts for selected models, validated output and saved attribution."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clauseiq_types.common import Clause, ClauseType, ContractType, RiskLevel
from database import service as database_service
from routers import analysis, chat
from services import ai_service, document_service, rag_service
from services.ai import client_manager, generation
from services.ai.generation import AIRequestError, generation_metadata
from services.ai.token_utils import get_optimal_response_tokens
from services.chat_service import ChatService
from services.rag_service import RAGService


MODEL = "gpt-5.6-luna"
CLAUSE = {
    "heading": "Confidentiality", "text": "Both parties must keep the information confidential.",
    "clause_type": "confidentiality", "risk_level": "low", "risk_reasoning": "The obligation is mutual.",
    "key_terms": ["confidentiality"], "relationships": [],
}
SUMMARY = {
    "overview": "A mutual confidentiality agreement.", "key_parties": [],
    "important_dates": [], "major_obligations": [], "risk_highlights": [], "key_insights": [],
}


def completion(content, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, refusal=None), finish_reason=finish_reason,
    )])


@pytest.fixture(autouse=True)
def offline_token_estimates(monkeypatch):
    # Keep provider contracts independent of tiktoken's first-run vocabulary
    # download; tokenizer behavior has its own dedicated regression tests.
    monkeypatch.setattr(generation, "get_token_count", lambda text, _model: len(text))


@pytest.fixture
def provider():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client_manager.set_request_client(client)
    yield client
    client_manager.clear_request_client()


async def run_main(operation, model):
    if operation == "classification":
        return await ai_service.detect_contract_type("Synthetic contract", "contract.pdf", model)
    if operation == "extraction":
        return await ai_service.extract_clauses_with_llm("Synthetic contract", ContractType.NDA, model)
    if operation == "summary":
        return await ai_service.generate_structured_document_summary(
            "Synthetic contract", "contract.pdf", model, ContractType.NDA,
        )
    return await ai_service.generate_clause_rewrite(Clause(**CLAUSE), "Synthetic contract", ContractType.NDA, model)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [MODEL, "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5-mini", "gpt-5-nano"])
@pytest.mark.parametrize("operation,content", [
    ("classification", "nda"), ("extraction", json.dumps({"clauses": [CLAUSE]})),
    ("summary", json.dumps(SUMMARY)), ("rewrite", "Each party must protect confidential information."),
])
async def test_main_operations_honor_selected_model_and_task_budget(provider, model, operation, content):
    provider.chat.completions.create.return_value = completion(content)
    result = await run_main(operation, model)
    assert result
    request = provider.chat.completions.create.await_args.kwargs
    assert request["model"] == model
    assert request["max_completion_tokens"] == get_optimal_response_tokens(operation, model)
    assert request["reasoning_effort"] == "medium"
    if operation in {"extraction", "summary"}:
        assert request["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["classification", "extraction", "summary", "rewrite"])
@pytest.mark.parametrize("content,finish_reason", [(None, "stop"), ("Partial text", "length")])
async def test_incomplete_main_output_is_never_accepted(provider, operation, content, finish_reason):
    provider.chat.completions.create.return_value = completion(content, finish_reason)
    with pytest.raises(AIRequestError):
        await run_main(operation, MODEL)
    assert provider.chat.completions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["classification", "extraction", "summary", "rewrite"])
async def test_input_over_budget_is_rejected_before_any_provider_call(monkeypatch, provider, operation):
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "20")
    with pytest.raises(AIRequestError, match="input budget"):
        await run_main(operation, MODEL)
    provider.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,content", [
    ("classification", "invented_type"), ("extraction", "not json"),
    ("extraction", '{"clauses": [{}]}'), ("extraction", '{"clauses": null}'),
    ("summary", "not json"), ("summary", '{"overview": "Incomplete"}'),
    ("summary", json.dumps({**SUMMARY, "key_parties": "not a list"})),
])
async def test_malformed_structured_output_fails_explicitly(provider, operation, content):
    provider.chat.completions.create.return_value = completion(content)
    with pytest.raises(AIRequestError):
        await run_main(operation, MODEL)


@pytest.fixture
def rag(monkeypatch):
    instance = RAGService.__new__(RAGService)
    instance.is_available = AsyncMock(return_value=True)
    instance.conversation_history_window = 4
    instance.max_chunks_per_query = 3
    settings = SimpleNamespace(get_query_gate_model=AsyncMock(return_value="gpt-5-nano"))
    monkeypatch.setattr(database_service, "get_document_service", lambda: settings)
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,content", [("query_gate", "YES"), ("query_rewrite", "What is the notice period?")])
async def test_chat_helpers_honor_explicit_cheap_model_and_low_reasoning(provider, rag, operation, content):
    provider.chat.completions.create.return_value = completion(content)
    if operation == "query_gate":
        assert await rag._needs_conversation_context("What about that?") is True
    else:
        assert await rag._rewrite_query_with_context("What about that?", []) == content
    request = provider.chat.completions.create.await_args.kwargs
    assert request["model"] == "gpt-5-nano"
    assert request["reasoning_effort"] == "low"
    assert request["max_completion_tokens"] == get_optimal_response_tokens(operation, "gpt-5-nano")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["query_gate", "query_rewrite", "chat"])
async def test_chat_generation_failures_propagate_instead_of_substituting_success(provider, rag, operation):
    provider.chat.completions.create.return_value = completion(None)
    with pytest.raises(AIRequestError):
        if operation == "query_gate":
            await rag._needs_conversation_context("What about that?")
        elif operation == "query_rewrite":
            await rag._rewrite_query_with_context("What about that?", [])
        else:
            await rag.generate_rag_response("Question", [], model=MODEL)


@pytest.mark.asyncio
async def test_chat_uses_main_model_and_returns_generation_settings(provider, rag):
    provider.chat.completions.create.return_value = completion("There is a confidentiality obligation. [Source 1]")
    result = await rag.generate_rag_response(
        "What is required?", [{"chunk_id": "chunk-1", "content": CLAUSE["text"]}], model="gpt-5.6-sol",
    )
    request = provider.chat.completions.create.await_args.kwargs
    assert request["model"] == "gpt-5.6-sol"
    assert request["reasoning_effort"] == "medium"
    assert request["max_completion_tokens"] == get_optimal_response_tokens("chat", "gpt-5.6-sol")
    assert result["generation"] == generation_metadata("gpt-5.6-sol", "chat")


@pytest.mark.asyncio
async def test_analysis_error_is_not_replaced_by_generic_runtime_error(monkeypatch):
    error = AIRequestError("The selected model is unavailable. Choose a model in Settings.")
    monkeypatch.setattr(client_manager, "is_ai_available", lambda: True)
    monkeypatch.setattr(ai_service, "detect_contract_type", AsyncMock(side_effect=error))
    with pytest.raises(AIRequestError) as result:
        await document_service.process_document_with_llm("Synthetic contract", model=MODEL)
    assert result.value is error


@pytest.mark.asyncio
async def test_chat_error_does_not_save_an_assistant_message():
    error = AIRequestError("The selected model is unavailable. Choose a model in Settings.")
    service = ChatService.__new__(ChatService)
    service.doc_service = SimpleNamespace(
        get_workspace_model=AsyncMock(return_value=MODEL), add_chat_message_atomic=AsyncMock(return_value=True),
    )
    service.rag_service = SimpleNamespace(
        is_available=AsyncMock(return_value=True),
        retrieve_relevant_chunks=AsyncMock(return_value={"chunks": [{"chunk_id": "chunk-1", "content": "Contract"}]}),
        generate_rag_response=AsyncMock(side_effect=error),
    )
    with pytest.raises(AIRequestError) as result:
        await service._process_message_foundational(
            {"id": "doc-1", "rag_processed": True}, {"session_id": "session-1", "messages": []}, "Question", "local",
        )
    assert result.value is error
    assert service.doc_service.add_chat_message_atomic.await_count == 1
    assert service.doc_service.add_chat_message_atomic.await_args.args[2]["role"] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_setting", ["model", "budget"])
async def test_invalid_main_chat_configuration_prevents_helper_or_embedding_spend(monkeypatch, invalid_setting):
    model = "unsupported-model" if invalid_setting == "model" else MODEL
    if invalid_setting == "budget":
        monkeypatch.setenv("AI_CHAT_MAX_COMPLETION_TOKENS", "invalid")
    service = ChatService.__new__(ChatService)
    service.doc_service = SimpleNamespace(
        get_workspace_model=AsyncMock(return_value=model), add_chat_message_atomic=AsyncMock(),
    )
    service.rag_service = SimpleNamespace(
        is_available=AsyncMock(return_value=True),
        retrieve_relevant_chunks=AsyncMock(), generate_rag_response=AsyncMock(),
    )
    with pytest.raises(AIRequestError):
        await service._process_message_foundational(
            {"id": "doc-1", "rag_processed": True}, {"session_id": "session-1", "messages": []}, "Question", "local",
        )
    service.rag_service.is_available.assert_not_awaited()
    service.rag_service.retrieve_relevant_chunks.assert_not_awaited()
    service.rag_service.generate_rag_response.assert_not_awaited()
    service.doc_service.add_chat_message_atomic.assert_not_awaited()


def test_analysis_persistence_retains_model_settings():
    metadata = {name: generation_metadata(MODEL, name) for name in ("classification", "extraction", "summary")}
    document = document_service.build_document_data(
        "doc-1", "contract.pdf", "Synthetic contract", [], ContractType.NDA, "local",
        analysis_generation=metadata,
    )
    assert document["analysis_generation"] == metadata


@pytest.mark.parametrize("route", ["analysis", "rewrite", "chat"])
def test_http_generation_errors_are_explicit_and_do_not_persist_results(monkeypatch, route):
    error = AIRequestError("The selected model is unavailable. Choose a model in Settings.")
    document = {"id": "doc-1", "text": "Synthetic contract", "contract_type": "nda", "clauses": [{"id": "clause-1", **CLAUSE}]}
    storage = SimpleNamespace(
        get_workspace_api_key=AsyncMock(return_value="sk-test-placeholder"),
        get_workspace_model=AsyncMock(return_value=MODEL),
        get_document_for_workspace=AsyncMock(return_value=document), update_clause_rewrite=AsyncMock(),
        update_document_if=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(analysis, "get_document_service", lambda: storage)
    monkeypatch.setattr(chat, "get_document_service", lambda: storage)
    @asynccontextmanager
    async def request_client(_key):
        yield object()
    monkeypatch.setattr(client_manager, "workspace_openai_client", request_client)
    monkeypatch.setattr(analysis, "SourceService", lambda **_: SimpleNamespace(import_pdf=AsyncMock(return_value={
        "id": "doc-1", "text": "Synthetic contract", "source_revision_id": "source-1",
        "extraction_status": "complete",
    })))
    monkeypatch.setattr(analysis, "process_document_with_llm", AsyncMock(side_effect=error))
    monkeypatch.setattr(analysis, "generate_clause_rewrite", AsyncMock(side_effect=error))
    save = AsyncMock()
    monkeypatch.setattr(analysis, "process_and_save_analyzed_document", save)
    monkeypatch.setattr(chat, "get_chat_service", lambda: SimpleNamespace(send_message=AsyncMock(side_effect=error)))
    app = FastAPI()
    app.include_router(analysis.router, prefix="/analysis")
    app.include_router(chat.router, prefix="/chat")
    client = TestClient(app)
    if route == "analysis":
        response = client.post("/analysis/analyze/", files={"file": ("contract.pdf", b"%PDF-test", "application/pdf")})
    elif route == "rewrite":
        response = client.post("/analysis/clauses/clause-1/rewrite", json={"document_id": "doc-1"})
    else:
        response = client.post("/chat/doc-1/message", json={"message": "Question"})
    assert response.status_code == error.status_code
    assert response.json()["detail"] == str(error)
    if route == "analysis":
        assert response.headers["X-Document-ID"] == "doc-1"
        assert storage.update_document_if.await_args.args[3]["analysis_status"] == "failed"
    save.assert_not_awaited()
    storage.update_clause_rewrite.assert_not_awaited()
