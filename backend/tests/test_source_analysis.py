"""Offline regressions for save-before-generation and legacy analysis isolation."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clauseiq_types.common import ContractType
from database import service as database_service
from routers import analysis
from services import document_service, rag_service
from services.ai import client_manager
from services.ai.generation import AIRequestError
from services.source_service import SourceService


@pytest.fixture
def source_analysis(monkeypatch):
    records, originals, events = {}, {}, []

    async def save(record, workspace_id):
        assert record["workspace_id"] == workspace_id == "local"
        records[record["id"]] = deepcopy(record)
        events.append("insert")

    async def get(document_id, workspace_id):
        record = records.get(document_id)
        return deepcopy(record) if record and record["workspace_id"] == workspace_id else None

    async def update(document_id, workspace_id, values):
        if await get(document_id, workspace_id) is None:
            return False
        records[document_id].update(deepcopy(values))
        events.append(values.get("analysis_status", "update"))
        return True

    async def conditional(document_id, workspace_id, expected, values):
        record = await get(document_id, workspace_id)
        if record is None or any(record.get(key) != value for key, value in expected.items()):
            return False
        return await update(document_id, workspace_id, values)

    async def store(document_id, workspace_id, content, filename, content_type):
        assert await get(document_id, workspace_id)
        originals[document_id] = content
        records[document_id]["has_pdf_file"] = True
        events.append("original_stored")
        return True

    async def read(document_id, workspace_id):
        assert await get(document_id, workspace_id)
        events.append("original_read")
        return {"content": originals[document_id]}

    async def extract(content, filename):
        assert content in originals.values()
        events.append("extract")
        return SimpleNamespace(text="Synthetic agreement", status="complete", model_dump=lambda: {"status": "complete"})

    storage = SimpleNamespace(
        save_document_for_workspace=AsyncMock(side_effect=save),
        get_document_for_workspace=AsyncMock(side_effect=get),
        update_document_data=AsyncMock(side_effect=update),
        update_document_if=AsyncMock(side_effect=conditional),
        store_pdf_file=AsyncMock(side_effect=store), get_pdf_file=AsyncMock(side_effect=read),
        get_workspace_api_key=AsyncMock(return_value="sk-test-placeholder"),
        get_workspace_model=AsyncMock(return_value="gpt-5.6-luna"),
    )
    extractor = SimpleNamespace(extract_source=AsyncMock(side_effect=extract))
    monkeypatch.setattr(analysis, "get_document_service", lambda: storage)
    monkeypatch.setattr(database_service, "get_document_service", lambda: storage)
    monkeypatch.setattr(analysis, "SourceService", lambda **_: SourceService(storage, extractor))

    @asynccontextmanager
    async def client(_key):
        events.append("client")
        yield object()

    async def process(*args):
        record = next(iter(records.values()))
        assert record["source_status"] == "stored"
        assert record["extraction_status"] == "complete"
        assert record["analysis_status"] == "processing"
        assert record["id"] in originals
        events.append("generate")
        return ContractType.NDA, []

    async def index(**kwargs):
        record = records[kwargs["document_id"]]
        assert record["analysis_status"] == "ready"
        assert record["clauses"] == []
        events.append("index")
        return {"vector_stored": True, "chunk_count": 1}

    processor = AsyncMock(side_effect=process)
    rag = SimpleNamespace(process_document_for_rag=AsyncMock(side_effect=index))
    monkeypatch.setattr(client_manager, "workspace_openai_client", client)
    monkeypatch.setattr(analysis, "process_document_with_llm", processor)
    monkeypatch.setattr(analysis, "generate_structured_document_summary", AsyncMock(return_value={"overview": "Synthetic summary"}))
    monkeypatch.setattr(rag_service, "get_rag_service", lambda: rag)
    app = FastAPI()
    app.include_router(analysis.router, prefix="/analysis")
    return SimpleNamespace(client=TestClient(app), records=records, originals=originals,
                           events=events, storage=storage, extractor=extractor, processor=processor, rag=rag)


def upload(context):
    return context.client.post("/analysis/analyze/", files={"file": ("synthetic.pdf", b"%PDF-synthetic", "application/pdf")})


def test_original_and_analysis_are_saved_before_optional_indexing(source_analysis):
    context = source_analysis
    response = upload(context)
    assert response.json()["success"] is True
    document_id = response.json()["data"]["id"]
    result = response.json()["data"]
    for field in ("source_revision_id", "source_sha256", "source_status", "extraction_status", "extraction_error"):
        assert result[field] == context.records[document_id].get(field)
    assert result["analysis_status"] == "ready"
    assert not {"pdf_file_id", "extraction_attempt_id"}.intersection(result)
    assert list(context.records) == list(context.originals) == [document_id]
    assert context.originals[document_id] == b"%PDF-synthetic"
    for first, second in (("original_stored", "extract"), ("extract", "generate"), ("ready", "index")):
        assert context.events.index(first) < context.events.index(second)
    context.storage.save_document_for_workspace.assert_awaited_once()
    context.storage.store_pdf_file.assert_awaited_once()
    assert context.records[document_id]["analysis_status"] == "ready"


def test_provider_failure_retains_source_and_safe_document_reference(source_analysis):
    context = source_analysis
    error = AIRequestError("The selected model is unavailable. Choose a model in Settings.")
    context.processor.side_effect = error
    response = upload(context)
    assert response.status_code == error.status_code
    assert response.json() == {"detail": error.public_message}
    document_id = response.headers["X-Document-ID"]
    assert context.originals[document_id] == b"%PDF-synthetic"
    assert context.records[document_id]["analysis_status"] == "failed"
    assert context.records[document_id]["clauses"] is None
    context.rag.process_document_for_rag.assert_not_awaited()


@pytest.mark.parametrize("status", ["partial", "unavailable", "failed"])
def test_incomplete_extraction_never_starts_provider(source_analysis, status):
    context = source_analysis
    if status == "failed":
        context.extractor.extract_source.side_effect = RuntimeError("private parser detail")
    else:
        context.extractor.extract_source.side_effect = None
        context.extractor.extract_source.return_value = SimpleNamespace(
            text="Partial only", status=status, model_dump=lambda: {"status": status},
        )
    response = upload(context)
    error = response.json()["error"]
    assert error["code"] == "PDF_EXTRACTION_FAILED"
    assert error["message"] == "Failed to extract text from PDF"
    document_id = error["details"]["document_id"]
    assert context.records[document_id]["extraction_status"] == status
    assert document_id in context.originals
    assert "client" not in context.events
    context.processor.assert_not_awaited()
    context.rag.process_document_for_rag.assert_not_awaited()


def test_unconfirmed_original_prevents_provider_and_success(source_analysis):
    context = source_analysis
    context.storage.store_pdf_file.side_effect = None
    context.storage.store_pdf_file.return_value = False
    response = upload(context)
    assert response.status_code == 503
    document_id = response.headers["X-Document-ID"]
    assert context.records[document_id]["source_status"] == "storage_failed"
    assert "client" not in context.events
    context.processor.assert_not_awaited()
    context.extractor.extract_source.assert_not_awaited()


def test_optional_rag_failure_keeps_ready_analysis(source_analysis):
    context = source_analysis
    context.rag.process_document_for_rag.side_effect = RuntimeError("synthetic index failure")
    response = upload(context)
    assert response.json()["success"] is True
    document = context.records[response.json()["data"]["id"]]
    assert document["analysis_status"] == "ready"
    assert document["ai_structured_summary"] == {"overview": "Synthetic summary"}
    assert document["ready_for_chat"] is False


def test_analysis_write_failure_keeps_original_and_never_indexes(source_analysis):
    context = source_analysis
    conditional = context.storage.update_document_if.side_effect

    async def fail_analysis_write(document_id, workspace_id, expected, values):
        if "clauses" in values:
            return False
        return await conditional(document_id, workspace_id, expected, values)

    context.storage.update_document_if.side_effect = fail_analysis_write
    response = upload(context)
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_SAVE_FAILED"
    document_id = error["details"]["document_id"]
    assert context.originals[document_id] == b"%PDF-synthetic"
    assert context.records[document_id]["analysis_status"] == "failed"
    assert context.records[document_id]["clauses"] is None
    context.rag.process_document_for_rag.assert_not_awaited()


def test_unexpected_generation_failure_returns_safe_metadata(source_analysis, caplog):
    context = source_analysis
    context.processor.side_effect = RuntimeError("private provider diagnostic")
    response = upload(context)
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_ANALYSIS_FAILED"
    assert error["message"] == "An error occurred while analyzing the document"
    document_id = error["details"]["document_id"]
    assert document_id in context.originals
    assert context.records[document_id]["analysis_status"] == "failed"
    assert "private provider diagnostic" not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"clauses": []}, {"analysis_status": "ready"}, {"has_pdf_file": False},
    {"source_status": "storage_failed"}, {"extraction_status": "partial"}, {"text": "Different source"},
])
async def test_save_rejects_existing_analysis_or_unconfirmed_source_without_writes(monkeypatch, change):
    record = {"id": "doc-1", "filename": "synthetic.pdf", "source_revision_id": "source-1",
              "source_status": "stored", "has_pdf_file": True, "extraction_status": "complete",
              "analysis_status": "processing", "clauses": None, "text": "Synthetic agreement", **change}
    storage = SimpleNamespace(get_document_for_workspace=AsyncMock(return_value=record),
                              update_document_if=AsyncMock(), save_document_for_workspace=AsyncMock(),
                              store_pdf_file=AsyncMock())
    monkeypatch.setattr(database_service, "get_document_service", lambda: storage)
    success, _ = await document_service.process_and_save_analyzed_document(
        "doc-1", "synthetic.pdf", "Synthetic agreement", [], ContractType.NDA, "local", {},
    )
    assert success is False
    storage.update_document_if.assert_not_awaited()
    storage.save_document_for_workspace.assert_not_awaited()
    storage.store_pdf_file.assert_not_awaited()


@pytest.mark.parametrize("status", ["not_started", "processing", "failed"])
def test_saved_clause_route_does_not_call_imported_sources_complete(source_analysis, status):
    context = source_analysis
    context.records["doc-1"] = {"id": "doc-1", "workspace_id": "local", "analysis_status": status,
                                "extraction_status": "complete", "clauses": None}
    response = context.client.get("/analysis/documents/doc-1/clauses")
    assert response.json()["error"]["code"] == "REVIEW_NOT_READY"
    assert response.json()["error"]["details"]["analysis_status"] == status
    context.processor.assert_not_awaited()
