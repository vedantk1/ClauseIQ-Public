"""Deterministic HTTP coverage for the account-free document workflow."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clauseiq_types.common import Clause, ClauseType, ContractType, RiskLevel
from routers import analysis, chat, documents, reports
from services.ai import client_manager
from services.ai.generation import generation_metadata
from services.document_service import build_document_data


@pytest.fixture
def route_client():
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(analysis.router, prefix="/api/v1/analysis")
    app.include_router(chat.router, prefix="/api/v1/chat")
    app.include_router(reports.router, prefix="/api/v1")
    return TestClient(app)


def document_service(monkeypatch, **methods):
    service = SimpleNamespace(**methods)
    for module in (analysis, chat, documents, reports):
        monkeypatch.setattr(module, "get_document_service", lambda: service)
    return service


@pytest.mark.parametrize(
    "method,suffix,payload,write_method",
    [
        ("PUT", "", {"is_flagged": True}, "save_user_interaction"),
        ("DELETE", "", None, "delete_user_interaction"),
        ("POST", "/notes", {"text": "Review this"}, "add_note"),
        ("PUT", "/notes/note-1", {"text": "Updated"}, "update_note"),
        ("DELETE", "/notes/note-1", None, "delete_note"),
    ],
)
@pytest.mark.parametrize("existing_document", [None, {"id": "doc-1", "clauses": [{"id": "other-clause"}]}])
def test_note_and_flag_writes_require_document_and_clause(
    monkeypatch, route_client, method, suffix, payload, write_method, existing_document
):
    writer = AsyncMock()
    service = document_service(
        monkeypatch,
        get_document_for_workspace=AsyncMock(return_value=existing_document),
        **{write_method: writer},
    )

    response = route_client.request(
        method,
        f"/api/v1/analysis/documents/doc-1/interactions/clause-1{suffix}",
        json=payload,
    )

    assert response.status_code == 404
    writer.assert_not_awaited()
    service.get_document_for_workspace.assert_awaited_once_with("doc-1", "local")


def test_browser_cannot_choose_workspace_for_note_write(monkeypatch, route_client):
    service = document_service(
        monkeypatch,
        get_document_for_workspace=AsyncMock(return_value={"clauses": [{"id": "clause-1"}]}),
        add_note=AsyncMock(return_value={"id": "note-1", "text": "Review"}),
    )

    response = route_client.post(
        "/api/v1/analysis/documents/doc-1/interactions/clause-1/notes?workspace_id=other",
        json={"text": "Review", "workspace_id": "other", "user_id": "other"},
    )

    assert response.status_code == 200
    service.get_document_for_workspace.assert_awaited_once_with("doc-1", "local")
    service.add_note.assert_awaited_once_with(
        document_id="doc-1", clause_id="clause-1", workspace_id="local", text="Review"
    )


@pytest.fixture
def interaction_library(monkeypatch):
    """Use real interaction service methods with isolated in-memory persistence."""
    from database.service import DocumentService

    state = {"interactions": {}}

    async def get_document(document_id, workspace_id):
        assert (document_id, workspace_id) == ("doc-1", "local")
        return {"id": document_id, "workspace_id": workspace_id, "clauses": [{"id": "clause-1"}]}

    async def get_interactions(document_id, workspace_id):
        assert (document_id, workspace_id) == ("doc-1", "local")
        return deepcopy(state["interactions"])

    async def save_interactions(document_id, workspace_id, values):
        assert (document_id, workspace_id) == ("doc-1", "local")
        state["interactions"] = deepcopy(values)
        return True

    adapter = SimpleNamespace(
        get_document=get_document,
        get_user_interactions=get_interactions,
        save_user_interactions=save_interactions,
    )
    service = DocumentService()
    monkeypatch.setattr(service, "_get_db", AsyncMock(return_value=adapter))
    monkeypatch.setattr(analysis, "get_document_service", lambda: service)
    return state


def test_positive_note_and_flag_http_crud(route_client, interaction_library):
    base = "/api/v1/analysis/documents/doc-1/interactions"
    clause_path = f"{base}/clause-1"

    flagged = route_client.put(clause_path, json={"is_flagged": True}).json()
    assert flagged["success"] is True
    assert flagged["meta"]["message"] == "Interaction saved successfully"
    assert flagged["data"]["interaction"]["is_flagged"] is True
    assert flagged["data"]["interaction"]["workspace_id"] == "local"

    created = route_client.post(f"{clause_path}/notes", json={"text": "Initial note"}).json()
    assert created["success"] is True
    note_id = created["data"]["note"]["id"]
    current = route_client.get(base).json()["data"]["interactions"]["clause-1"]
    assert current["notes"][0]["text"] == "Initial note"
    assert current["is_flagged"] is True

    updated = route_client.put(f"{clause_path}/notes/{note_id}", json={"text": "Edited note"}).json()
    assert updated["success"] is True
    assert updated["data"]["note"]["id"] == note_id
    assert updated["data"]["note"]["text"] == "Edited note"
    unflagged = route_client.put(clause_path, json={"is_flagged": False}).json()
    assert unflagged["success"] is True
    assert unflagged["data"]["interaction"]["is_flagged"] is False
    assert unflagged["data"]["interaction"]["notes"][0]["text"] == "Edited note"

    deleted_note = route_client.delete(f"{clause_path}/notes/{note_id}").json()
    assert deleted_note["success"] is True
    assert deleted_note["data"]["deleted"] is True
    assert interaction_library["interactions"]["clause-1"]["notes"] == []
    deleted = route_client.delete(clause_path).json()
    assert deleted["success"] is True
    assert deleted["meta"]["message"] == "Interaction deleted successfully"
    assert route_client.get(base).json()["data"]["interactions"] == {}
    assert interaction_library["interactions"] == {}


def test_interaction_responses_omit_legacy_owner_ids_without_changing_records(route_client, interaction_library):
    legacy = {
        "clause_id": "clause-1", "user_id": "legacy-owner", "workspace_id": "local",
        "is_flagged": False, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        "notes": [{"id": "note-1", "text": "The literal user_id text stays.",
                   "user_id": "legacy-owner", "created_at": "2026-01-01T00:00:00"}],
    }
    interaction_library["interactions"] = {"clause-1": deepcopy(legacy)}
    base = "/api/v1/analysis/documents/doc-1/interactions"

    read = route_client.get(base).json()["data"]["interactions"]["clause-1"]
    assert "user_id" not in read
    assert "user_id" not in read["notes"][0]
    assert read["notes"][0]["text"] == legacy["notes"][0]["text"]
    assert interaction_library["interactions"]["clause-1"] == legacy

    saved = route_client.put(f"{base}/clause-1", json={"is_flagged": True}).json()
    assert saved["success"] is True
    assert "user_id" not in saved["data"]["interaction"]
    assert "user_id" not in saved["data"]["interaction"]["notes"][0]
    assert interaction_library["interactions"]["clause-1"]["user_id"] == "legacy-owner"
    assert interaction_library["interactions"]["clause-1"]["notes"][0] == legacy["notes"][0]


@pytest.mark.parametrize("path", ["/documents/doc-1/pdf", "/reports/documents/doc-1/pdf"])
def test_pdf_and_report_require_document_in_workspace(monkeypatch, route_client, path):
    service = document_service(
        monkeypatch,
        get_document_for_workspace=AsyncMock(return_value=None),
        get_pdf_file_stream=AsyncMock(),
    )
    generate_report = AsyncMock()
    monkeypatch.setattr(reports, "generate_pdf_report", generate_report)

    response = route_client.get(f"/api/v1{path}?workspace_id=other")

    assert response.status_code == 404
    service.get_document_for_workspace.assert_awaited_once_with("doc-1", "local")
    service.get_pdf_file_stream.assert_not_awaited()
    generate_report.assert_not_awaited()


def test_rewrite_cannot_use_clause_from_another_document(monkeypatch, route_client):
    service = document_service(
        monkeypatch,
        get_document_for_workspace=AsyncMock(return_value={"clauses": [{"id": "other-clause"}]}),
        get_workspace_api_key=AsyncMock(),
    )
    generate = AsyncMock()
    monkeypatch.setattr(analysis, "generate_clause_rewrite", generate)

    response = route_client.post(
        "/api/v1/analysis/clauses/clause-1/rewrite", json={"document_id": "doc-1"}
    )

    assert response.json()["error"]["code"] == "CLAUSE_NOT_FOUND"
    service.get_workspace_api_key.assert_not_awaited()
    generate.assert_not_awaited()


def test_empty_library_bulk_delete_is_success(monkeypatch, route_client):
    document_service(monkeypatch, delete_all_documents_for_workspace=AsyncMock(return_value=0))

    response = route_client.delete("/api/v1/documents")

    assert response.status_code == 200
    assert response.json()["data"]["deleted_count"] == 0


def test_chat_session_uses_server_workspace_and_response_shape(monkeypatch, route_client):
    get_session = AsyncMock(return_value={
        "success": True,
        "session": {
            "session_id": "session-1", "document_id": "doc-1", "workspace_id": "local",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00", "messages": [],
        },
    })
    monkeypatch.setattr(chat, "get_chat_service", lambda: SimpleNamespace(get_or_create_session=get_session))

    response = route_client.post("/api/v1/chat/doc-1/session?workspace_id=other")

    assert response.status_code == 200
    assert response.json()["data"]["workspace_id"] == "local"
    assert "user_id" not in response.json()["data"]
    get_session.assert_awaited_once_with("doc-1", "local")


def test_chat_history_omits_legacy_owner_metadata_without_changing_messages(monkeypatch, route_client):
    message = {"role": "user", "content": "Keep literal user_id text.", "user_id": "legacy-owner"}
    original = deepcopy(message)
    service = SimpleNamespace(
        get_or_create_session=AsyncMock(return_value={"success": True, "session": {
            "session_id": "session-1", "document_id": "doc-1", "workspace_id": "local",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00", "messages": [message],
        }}),
        get_session_history=AsyncMock(return_value={"success": True, "session_id": "session-1",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00", "messages": [message],
        }),
    )
    monkeypatch.setattr(chat, "get_chat_service", lambda: service)

    session = route_client.post("/api/v1/chat/doc-1/session").json()["data"]
    history = route_client.get("/api/v1/chat/doc-1/history").json()["data"]

    for result in (session, history):
        assert "user_id" not in result["messages"][0]
        assert result["messages"][0]["content"] == message["content"]
    assert message == original


def test_analysis_requires_key_and_retains_upload_validation(monkeypatch, route_client):
    document_service(monkeypatch, get_workspace_api_key=AsyncMock(return_value=None))
    process = AsyncMock()
    monkeypatch.setattr(analysis, "process_document_with_llm", process)

    invalid = route_client.post(
        "/api/v1/analysis/analyze/", files={"file": ("contract.exe", b"invalid", "application/pdf")}
    )
    missing_key = route_client.post(
        "/api/v1/analysis/analyze/", files={"file": ("contract.pdf", b"%PDF-test", "application/pdf")}
    )

    assert invalid.status_code == 400
    assert missing_key.json()["error"]["code"] == "API_KEY_REQUIRED"
    process.assert_not_awaited()


def test_account_free_analysis_review_chat_rewrite_report_and_delete(monkeypatch, route_client):
    """Exercise real route/model contracts while provider and persistence are mocked."""
    stored = {}
    credential = "sk-test-placeholder"
    active_keys = []
    opened_keys = []
    pdf_bytes = b"%PDF-test-document"
    clause = Clause(
        id="clause-1", heading="Termination", text="Either party may terminate.",
        clause_type=ClauseType.TERMINATION, risk_level=RiskLevel.MEDIUM,
        risk_reasoning="Notice is undefined.", key_terms=["termination"], relationships=[],
    )
    chat_generation = generation_metadata("gpt-6-luna", "chat")
    chat_messages = []

    async def get_document(document_id, workspace_id):
        document = stored.get(document_id)
        return document if document and document["workspace_id"] == workspace_id else None

    async def save_document(**kwargs):
        document = build_document_data(**{
            key: value for key, value in kwargs.items() if key not in {"file_content", "content_type"}
        })
        document["has_pdf_file"] = True
        document["analysis_status"] = "ready"
        stored[document["id"]].update(document)
        return True, None

    async def import_pdf(content, filename, workspace_id):
        stored["doc-imported"] = {
            "id": "doc-imported", "filename": filename, "workspace_id": workspace_id,
            "text": clause.text, "source_revision_id": "source-1", "source_status": "stored",
            "extraction_status": "complete", "analysis_status": "not_started", "has_pdf_file": True,
        }
        return stored["doc-imported"]

    async def update_document_if(document_id, workspace_id, expected, values):
        document = await get_document(document_id, workspace_id)
        if not document or any(document.get(key) != value for key, value in expected.items()):
            return False
        document.update(values)
        return True

    async def pdf_stream(_document_id, workspace_id):
        assert workspace_id == "local"
        async def stream():
            yield pdf_bytes
        return {"filename": "contract.pdf", "file_size": len(pdf_bytes)}, stream()

    async def save_rewrite(document_id, clause_id, workspace_id, rewrite_suggestion, generation=None):
        document = await get_document(document_id, workspace_id)
        target = next(item for item in document["clauses"] if item["id"] == clause_id)
        target.update(rewrite_suggestion=rewrite_suggestion, rewrite_generated_at="2026-01-01T00:00:00", rewrite_generation=generation)
        return target

    async def delete_document(document_id, workspace_id):
        if await get_document(document_id, workspace_id):
            del stored[document_id]
            return True
        return False

    service = document_service(
        monkeypatch,
        get_workspace_api_key=AsyncMock(side_effect=lambda _workspace_id: credential),
        get_workspace_generation_settings=AsyncMock(return_value={"model_id": "gpt-6-luna", "reasoning_effort": "medium"}),
        get_document_for_workspace=AsyncMock(side_effect=get_document),
        update_document_if=AsyncMock(side_effect=update_document_if),
        get_pdf_file_stream=AsyncMock(side_effect=pdf_stream),
        update_clause_rewrite=AsyncMock(side_effect=save_rewrite),
        delete_document_for_workspace=AsyncMock(side_effect=delete_document),
    )

    @asynccontextmanager
    async def request_client(api_key):
        opened_keys.append(api_key)
        active_keys.append(api_key)
        try:
            yield object()
        finally:
            active_keys.pop()

    async def process(*_args, reasoning_effort=None):
        assert reasoning_effort == "medium"
        assert active_keys == [credential]
        return ContractType.NDA, [clause]

    async def answer(document_id, workspace_id, message):
        assert await get_document(document_id, workspace_id)
        assert active_keys == [credential]
        assistant = {
            "id": "message-1", "role": "assistant", "content": "Notice is not defined.",
            "timestamp": "2026-01-01T00:00:00", "sources": [], "model_used": "gpt-6-luna",
            "generation": chat_generation,
        }
        chat_messages.append(assistant)
        return {"success": True, "session_id": "session-1", "message": assistant}

    monkeypatch.setattr(client_manager, "workspace_openai_client", request_client)
    monkeypatch.setattr(analysis, "SourceService", lambda **_: SimpleNamespace(import_pdf=import_pdf))
    monkeypatch.setattr(analysis, "process_document_with_llm", process)
    monkeypatch.setattr(analysis, "generate_structured_document_summary", AsyncMock(return_value={"overview": "Test summary"}))
    monkeypatch.setattr(analysis, "process_and_save_analyzed_document", save_document)
    monkeypatch.setattr(analysis, "generate_clause_rewrite", AsyncMock(return_value="Either party may terminate with notice."))
    monkeypatch.setattr(chat, "get_chat_service", lambda: SimpleNamespace(
        send_message=AsyncMock(side_effect=answer),
        get_session_history=AsyncMock(return_value={
            "success": True, "session_id": "session-1", "messages": chat_messages,
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }),
    ))
    monkeypatch.setattr(reports, "generate_pdf_report", AsyncMock(return_value=b"%PDF-test-report"))

    uploaded = route_client.post("/api/v1/analysis/analyze/", files={"file": ("contract.pdf", pdf_bytes, "application/pdf")})
    assert uploaded.status_code == 200
    assert uploaded.json()["success"] is True
    assert uploaded.json()["data"]["workspace_id"] == "local"
    assert "user_id" not in uploaded.json()["data"]
    document_id = uploaded.json()["data"]["id"]
    detail = route_client.get(f"/api/v1/documents/{document_id}").json()["data"]
    assert detail["workspace_id"] == "local"
    assert "user_id" not in detail
    expected_analysis = {
        name: generation_metadata("gpt-6-luna", name)
        for name in ("classification", "extraction", "summary")
    }
    assert detail["analysis_generation"] == expected_analysis
    assert uploaded.json()["data"]["analysis_generation"] == expected_analysis
    assert route_client.get(f"/api/v1/documents/{document_id}/pdf").content == pdf_bytes
    sent = route_client.post(f"/api/v1/chat/{document_id}/message", json={"message": "What notice is required?"}).json()
    assert sent["success"]
    assert sent["data"]["message"]["generation"] == chat_generation
    rewritten = route_client.post("/api/v1/analysis/clauses/clause-1/rewrite", json={"document_id": document_id})
    assert rewritten.json()["data"]["cached"] is False
    rewrite_generation = generation_metadata("gpt-6-luna", "rewrite")
    assert rewritten.json()["data"]["rewrite_generation"] == rewrite_generation
    assert len(opened_keys) == 3
    assert active_keys == []

    credential = None
    clauses = route_client.get(f"/api/v1/analysis/documents/{document_id}/clauses").json()["data"]
    assert clauses["total_clauses"] == 1
    assert clauses["risk_summary"] == {"high": 0, "medium": 1, "low": 0}
    assert clauses["clauses"][0]["rewrite_generation"] == rewrite_generation
    detail = route_client.get(f"/api/v1/documents/{document_id}").json()["data"]
    assert detail["clauses"][0]["rewrite_generation"] == rewrite_generation
    history = route_client.get(f"/api/v1/chat/{document_id}/history").json()["data"]
    assert history["messages"][0]["generation"] == chat_generation
    cached = route_client.post("/api/v1/analysis/clauses/clause-1/rewrite", json={"document_id": document_id})
    assert cached.json()["data"]["cached"] is True
    assert cached.json()["data"]["rewrite_generation"] == rewrite_generation
    assert len(opened_keys) == 3
    assert route_client.get(f"/api/v1/reports/documents/{document_id}/pdf").content == b"%PDF-test-report"
    assert route_client.delete(f"/api/v1/documents/{document_id}").json()["success"]
    assert route_client.get(f"/api/v1/documents/{document_id}").status_code == 404
    service.delete_document_for_workspace.assert_awaited_once_with(document_id, "local")


def test_real_chat_service_preserves_workspace_contract(monkeypatch, route_client):
    """Exercise the real chat service against signature-checked storage and RAG doubles."""
    import openai
    from database.service import DocumentService
    from services.chat_service import ChatService
    from services.rag_service import RAGService

    storage = create_autospec(DocumentService, instance=True)
    storage.get_document_for_workspace.return_value = {
        "id": "doc-1", "workspace_id": "local", "rag_processed": True, "text": "Test contract",
    }
    storage.get_workspace_api_key.return_value = "sk-test-placeholder"
    storage.get_workspace_generation_settings.return_value = {"model_id": "gpt-6-luna", "reasoning_effort": "medium"}
    storage.add_chat_message_atomic.return_value = True
    sessions = {}

    async def get_session(document_id, workspace_id, session_data):
        assert workspace_id == "local"
        assert session_data["workspace_id"] == "local"
        assert "user_id" not in session_data
        created = document_id not in sessions
        sessions.setdefault(document_id, session_data)
        return {"created": created, "session": sessions[document_id]}

    storage.create_or_get_chat_session.side_effect = get_session
    rag = create_autospec(RAGService, instance=True)
    rag.is_available.return_value = True
    rag.retrieve_relevant_chunks.return_value = {
        "chunks": [{"chunk_id": "chunk-1", "content": "Test contract", "similarity_score": 0.8}],
    }
    rag.generate_rag_response.return_value = {"response": "Test answer", "model": "test-model"}
    real_chat = ChatService.__new__(ChatService)
    real_chat.doc_service = storage
    real_chat.rag_service = rag
    monkeypatch.setattr(chat, "get_document_service", lambda: storage)
    monkeypatch.setattr(chat, "get_chat_service", lambda: real_chat)
    provider = AsyncMock()
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kwargs: provider)

    session_response = route_client.post("/api/v1/chat/doc-1/session")
    assert session_response.json()["data"]["workspace_id"] == "local"
    message_response = route_client.post("/api/v1/chat/doc-1/message", json={"message": "Summarize"})

    assert message_response.status_code == 200
    assert message_response.json()["data"]["message"]["content"] == "Test answer"
    rag.retrieve_relevant_chunks.assert_awaited_once_with("Summarize", "doc-1", "local", [])
    assert len(storage.add_chat_message_atomic.await_args_list) == 2
    for call in storage.add_chat_message_atomic.await_args_list:
        assert call.args[:2] == ("doc-1", "local")
    provider.close.assert_awaited_once()
    assert client_manager.get_openai_client() is None


@pytest.mark.asyncio
async def test_real_analysis_persistence_pipeline_uses_workspace_signatures(monkeypatch):
    from database import service as database_service
    from database.service import DocumentService
    from services import document_service as processing
    from services import rag_service
    from services.rag_service import RAGService

    storage = create_autospec(DocumentService, instance=True)
    storage.get_document_for_workspace.return_value = {
        "id": "doc-1", "filename": "contract.pdf", "text": "Test contract",
        "source_revision_id": "source-1", "source_status": "stored", "has_pdf_file": True,
        "extraction_status": "complete", "analysis_status": "processing", "clauses": None,
    }
    storage.update_document_if.return_value = True
    rag = create_autospec(RAGService, instance=True)
    rag.process_document_for_rag.return_value = {
        "vector_stored": True, "chunk_count": 1, "chunk_ids": ["chunk-1"],
    }
    monkeypatch.setattr(database_service, "get_document_service", lambda: storage)
    monkeypatch.setattr(rag_service, "get_rag_service", lambda: rag)

    success, error = await processing.process_and_save_analyzed_document(
        doc_id="doc-1", filename="contract.pdf", extracted_text="Test contract", clauses=[],
        contract_type=ContractType.NDA, workspace_id="local", ai_structured_summary={},
        file_content=b"%PDF-test", content_type="application/pdf",
    )

    assert success and error is None
    document_id, workspace_id, expected, saved = storage.update_document_if.await_args_list[0].args
    assert document_id == "doc-1"
    assert workspace_id == "local"
    assert expected["source_revision_id"] == "source-1"
    assert saved["analysis_status"] == "ready"
    assert "user_id" not in saved
    assert storage.update_document_if.await_args_list[1].args[3]["rag_processed"] is True
    rag.process_document_for_rag.assert_awaited_once_with(
        document_id="doc-1", text="Test contract", filename="contract.pdf", workspace_id="local",
    )
    storage.save_document_for_workspace.assert_not_awaited()
    storage.store_pdf_file.assert_not_awaited()
