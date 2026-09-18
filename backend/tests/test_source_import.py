"""Source lifecycle contracts, without application data or provider calls."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import documents
from services.ai.text_extractor import TextExtractor
from services.source_service import SourceService, SourceError, validate_pdf_bytes, read_pdf_upload

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs"


class MemoryDocuments:
    def __init__(self):
        self.documents = {}
        self.files = {}
        self.events = []
        self.fail_file = False
        self.fail_update = False

    async def save_document_for_workspace(self, data, workspace_id):
        assert data["workspace_id"] == workspace_id
        self.documents[data["id"]] = deepcopy(data)
        self.events.append("document")
        return "database-id-is-not-the-document-id"

    async def get_document_for_workspace(self, doc_id, workspace_id):
        doc = self.documents.get(doc_id)
        return deepcopy(doc) if doc and doc["workspace_id"] == workspace_id else None

    async def store_pdf_file(self, doc_id, workspace_id, content, filename, content_type):
        assert await self.get_document_for_workspace(doc_id, workspace_id)
        if self.fail_file:
            return False
        self.files[doc_id] = content
        self.documents[doc_id].update(has_pdf_file=True, pdf_file_id="file-" + doc_id)
        self.events.append("file")
        return True

    async def get_pdf_file(self, doc_id, workspace_id):
        if not await self.get_document_for_workspace(doc_id, workspace_id) or doc_id not in self.files:
            return None
        return {"content": self.files[doc_id]}

    async def update_document_data(self, doc_id, workspace_id, values):
        if self.fail_update or not await self.get_document_for_workspace(doc_id, workspace_id):
            return False
        self.documents[doc_id].update(deepcopy(values))
        return True

    async def update_document_if(self, doc_id, workspace_id, expected, values):
        # No await between comparison and assignment, mirroring an atomic adapter write.
        doc = self.documents.get(doc_id)
        if not doc or doc["workspace_id"] != workspace_id or any(doc.get(k) != v for k, v in expected.items()):
            return False
        doc.update(deepcopy(values))
        return True

    async def get_workspace_api_key(self, *args):
        raise AssertionError("Local import must not inspect credentials")


@pytest.fixture
def pdf_bytes():
    return (FIXTURES / "managed-services-25p.pdf").read_bytes()


@pytest.fixture
def storage():
    return MemoryDocuments()


@pytest.mark.asyncio
async def test_import_stores_original_before_extracting_without_credentials(storage, pdf_bytes):
    real = TextExtractor()

    async def extract(content, filename):
        assert storage.events == ["document", "file"]
        return await real.extract_source(content, filename)

    source = SourceService(storage, SimpleNamespace(extract_source=extract))
    doc = await source.import_pdf(pdf_bytes, "synthetic.pdf", "local")
    assert doc["source_status"] == "stored"
    assert doc["extraction_status"] == "complete"
    assert doc["analysis_status"] == "not_started" and doc["clauses"] is None
    assert doc["source_extraction"]["page_count"] == 25
    assert doc["source_sha256"] == doc["source_extraction"]["content_sha256"]
    assert storage.files[doc["id"]] == pdf_bytes
    assert len(storage.documents) == len(storage.files) == 1
    cached = await source.extract(doc["id"], "local", restart=True)
    assert cached == doc  # Published extraction is not silently replaced.


@pytest.mark.asyncio
async def test_extraction_failure_retains_original_and_retries_same_record(storage, pdf_bytes):
    extractor = SimpleNamespace(extract_source=AsyncMock(side_effect=RuntimeError("PRIVATE_SENTINEL")))
    source = SourceService(storage, extractor)
    failed = await source.import_pdf(pdf_bytes, "synthetic.pdf", "local")
    assert failed["extraction_status"] == "failed"
    assert failed["extraction_error"] == "PDF_EXTRACTION_FAILED"
    assert "PRIVATE_SENTINEL" not in repr(failed)
    assert storage.files[failed["id"]] == pdf_bytes
    source.extractor = TextExtractor()
    ready = await source.extract(failed["id"], "local")
    for field in ("id", "source_revision_id", "source_sha256", "pdf_file_id", "upload_date"):
        assert ready[field] == failed[field]
    assert ready["extraction_status"] == "complete"
    assert len(storage.documents) == len(storage.files) == 1


@pytest.mark.asyncio
async def test_pdf_storage_failure_is_not_success_and_does_not_extract(storage, pdf_bytes):
    storage.fail_file = True
    extractor = SimpleNamespace(extract_source=AsyncMock())
    with pytest.raises(SourceError) as caught:
        await SourceService(storage, extractor).import_pdf(pdf_bytes, "synthetic.pdf", "local")
    assert caught.value.code == "SOURCE_STORAGE_FAILED"
    doc = storage.documents[caught.value.document_id]
    assert doc["source_status"] == "storage_failed" and doc["analysis_status"] == "not_started"
    assert not storage.files
    extractor.extract_source.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_source_status_write_can_recover_matching_original(storage, pdf_bytes):
    storage.fail_update = True
    source = SourceService(storage)
    with pytest.raises(SourceError) as caught:
        await source.import_pdf(pdf_bytes, "synthetic.pdf", "local")
    doc_id = caught.value.document_id
    assert storage.documents[doc_id]["source_status"] == "storing"
    assert storage.files[doc_id] == pdf_bytes
    storage.fail_update = False
    recovered = await source.extract(doc_id, "local")
    assert recovered["source_status"] == "stored" and recovered["extraction_status"] == "complete"
    assert len(storage.files) == 1


@pytest.mark.asyncio
async def test_corrupt_original_never_becomes_extracted(storage, pdf_bytes):
    source = SourceService(storage, SimpleNamespace(extract_source=AsyncMock(side_effect=ValueError())))
    doc = await source.import_pdf(pdf_bytes, "synthetic.pdf", "local")
    storage.files[doc["id"]] = b"%PDF-different"
    source.extractor.extract_source.reset_mock()
    result = await source.extract(doc["id"], "local")
    assert result["extraction_error"] == "SOURCE_INTEGRITY_FAILED"
    source.extractor.extract_source.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_workspace_and_legacy_source_are_not_mutated(storage, pdf_bytes):
    doc = await SourceService(storage).import_pdf(pdf_bytes, "synthetic.pdf", "local")
    original = deepcopy(storage.documents)
    with pytest.raises(SourceError) as caught:
        await SourceService(storage).extract(doc["id"], "another")
    assert caught.value.status_code == 404
    storage.documents["legacy"] = {"id": "legacy", "workspace_id": "local", "text": "Keep existing analysis"}
    with pytest.raises(SourceError, match="no confirmed source revision"):
        await SourceService(storage).extract("legacy", "local")
    assert storage.documents[doc["id"]] == original[doc["id"]]
    assert storage.documents["legacy"]["text"] == "Keep existing analysis"


@pytest.mark.asyncio
async def test_explicit_restart_fences_late_completion(storage, pdf_bytes):
    started, release = asyncio.Event(), asyncio.Event()
    real_result = await TextExtractor().extract_source(pdf_bytes, "synthetic.pdf")
    source = SourceService(storage, SimpleNamespace(extract_source=AsyncMock(side_effect=ValueError())))
    doc = await source.import_pdf(pdf_bytes, "synthetic.pdf", "local")

    async def slow(*args):
        started.set()
        await release.wait()
        return real_result

    source.extractor = SimpleNamespace(extract_source=slow)
    old_task = asyncio.create_task(source.extract(doc["id"], "local"))
    await started.wait()
    with pytest.raises(SourceError) as caught:
        await source.extract(doc["id"], "local")
    assert caught.value.code == "EXTRACTION_IN_PROGRESS"
    replacement = SourceService(storage, SimpleNamespace(extract_source=AsyncMock(return_value=real_result)))
    ready = await replacement.extract(doc["id"], "local", restart=True)
    release.set()
    with pytest.raises(SourceError) as superseded:
        await old_task
    assert superseded.value.code == "EXTRACTION_CONFLICT"
    assert storage.documents[doc["id"]] == ready


@pytest.mark.parametrize("content,filename", [(b"", "a.pdf"), (b"not a PDF", "a.pdf"),
    (b"%PDF-1.4", "a.exe"), (b"%PDF-1.4", "../a.pdf"), (b"%PDF-1.4", "a\\b.pdf")])
def test_invalid_upload_is_rejected_before_writes(content, filename):
    with pytest.raises(SourceError):
        validate_pdf_bytes(content, filename)


@pytest.mark.asyncio
async def test_read_enforces_actual_byte_limit(monkeypatch):
    monkeypatch.setattr("services.source_service.source_upload_limit", lambda: 8)
    upload = SimpleNamespace(filename="a.pdf", size=None, read=AsyncMock(return_value=b"%PDF-1234"))
    with pytest.raises(SourceError) as caught:
        await read_pdf_upload(upload)
    assert caught.value.status_code == 413
    upload.read.assert_awaited_once_with(9)


def test_import_source_routes_are_local_no_key_and_hide_internal_fields(monkeypatch, storage, pdf_bytes):
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    monkeypatch.setattr(documents, "get_document_service", lambda: storage)
    client = TestClient(app)
    imported = client.post("/api/v1/documents/import?workspace_id=other", files={
        "file": ("synthetic.pdf", pdf_bytes, "application/pdf")})
    assert imported.status_code == 200 and imported.json()["success"]
    doc = imported.json()["data"]
    assert doc["workspace_id"] == "local" and doc["analysis_status"] == "not_started"
    assert "pdf_file_id" not in doc and "extraction_attempt_id" not in doc
    source = client.get(f"/api/v1/documents/{doc['id']}/source").json()["data"]
    assert source["source_extraction"]["page_count"] == 25
    assert "extraction_attempt_id" not in source
    cached = client.post(f"/api/v1/documents/{doc['id']}/extract", json={}).json()["data"]
    assert cached == source
    assert client.get("/api/v1/documents/missing/source").status_code == 404


def test_failed_extraction_is_an_imported_original_not_a_ready_review(monkeypatch, storage):
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    monkeypatch.setattr(documents, "get_document_service", lambda: storage)
    response = TestClient(app).post("/api/v1/documents/import", files={
        "file": ("synthetic.pdf", b"%PDF-malformed", "application/pdf")})
    assert response.status_code == 200 and response.json()["success"]
    doc = response.json()["data"]
    assert doc["source_status"] == "stored" and doc["extraction_status"] == "failed"
    assert doc["analysis_status"] == "not_started"
    assert storage.files[doc["id"]] == b"%PDF-malformed"


def fail_persistence_once(monkeypatch, storage, stage):
    """Inject an uncertain persistence error without exposing its diagnostic text."""
    failed = False
    original_save = storage.save_document_for_workspace
    original_store = storage.store_pdf_file
    original_update = storage.update_document_data
    original_conditional = storage.update_document_if
    original_get = storage.get_document_for_workspace

    def fail(selected):
        nonlocal failed
        if stage == selected and not failed:
            failed = True
            raise RuntimeError("PRIVATE_PERSISTENCE_DETAIL")

    async def save(*args):
        result = await original_save(*args)
        fail("save_acknowledgment")
        return result

    async def store(*args):
        fail("file_store")
        return await original_store(*args)

    async def update(*args):
        fail("status_write")
        return await original_update(*args)

    async def conditional(doc_id, workspace_id, expected, values):
        if values.get("extraction_status") == "processing":
            fail("claim")
        if "source_extraction" in values:
            fail("publication")
        return await original_conditional(doc_id, workspace_id, expected, values)

    async def get(*args):
        result = await original_get(*args)
        if result and result.get("source_extraction") is not None:
            fail("final_read")
        return result

    monkeypatch.setattr(storage, "save_document_for_workspace", save)
    monkeypatch.setattr(storage, "store_pdf_file", store)
    monkeypatch.setattr(storage, "update_document_data", update)
    monkeypatch.setattr(storage, "update_document_if", conditional)
    monkeypatch.setattr(storage, "get_document_for_workspace", get)


@pytest.mark.parametrize("stage", [
    "save_acknowledgment", "file_store", "status_write", "claim", "publication", "final_read",
])
def test_import_persistence_errors_keep_recovery_id_and_hide_details(monkeypatch, storage, stage, caplog):
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    monkeypatch.setattr(documents, "get_document_service", lambda: storage)
    fail_persistence_once(monkeypatch, storage, stage)
    content = (FIXTURES / "mutual-nda.pdf").read_bytes()
    client = TestClient(app)

    response = client.post("/api/v1/documents/import", files={
        "file": ("synthetic.pdf", content, "application/pdf"),
    })

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SOURCE_SAVE_FAILED"
    document_id = error["details"]["document_id"]
    assert list(storage.documents) == [document_id]
    assert "Any stored original has not been deleted." in error["message"]
    assert "PRIVATE_PERSISTENCE_DETAIL" not in response.text + caplog.text
    assert "RuntimeError" in caplog.text
    if stage in {"save_acknowledgment", "file_store"}:
        assert storage.files == {}
    else:
        assert storage.files == {document_id: content}
        # Retry the retained record, including an uncertain processing write.
        recovered = client.post(f"/api/v1/documents/{document_id}/extract", json={"restart": True})
        assert recovered.status_code == 200
        assert recovered.json()["data"]["id"] == document_id
        assert recovered.json()["data"]["extraction_status"] == "complete"
        assert list(storage.documents) == [document_id]
        assert storage.files == {document_id: content}


def test_extract_persistence_error_keeps_known_document_id(monkeypatch, storage, caplog):
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    monkeypatch.setattr(documents, "get_document_service", lambda: storage)
    storage.get_document_for_workspace = AsyncMock(side_effect=RuntimeError("PRIVATE_PERSISTENCE_DETAIL"))

    response = TestClient(app).post("/api/v1/documents/synthetic-document-id/extract", json={})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SOURCE_SAVE_FAILED"
    assert error["details"] == {"document_id": "synthetic-document-id"}
    assert "PRIVATE_PERSISTENCE_DETAIL" not in response.text + caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(403, "SOURCE_ACCESS_DENIED"), (404, "DOCUMENT_NOT_FOUND")])
async def test_existing_source_errors_are_not_relabelled(storage, pdf_bytes, status, code):
    original = SourceError(code, "Synthetic safe rejection", status, "synthetic-document-id")
    storage.save_document_for_workspace = AsyncMock(side_effect=original)
    with pytest.raises(SourceError) as imported:
        await SourceService(storage).import_pdf(pdf_bytes, "synthetic.pdf", "local")
    assert imported.value is original
    storage.get_document_for_workspace = AsyncMock(side_effect=original)
    with pytest.raises(SourceError) as extracted:
        await SourceService(storage).extract("synthetic-document-id", "local")
    assert extracted.value is original


@pytest.mark.asyncio
async def test_failed_status_write_does_not_promise_an_original_exists(storage, pdf_bytes):
    storage.fail_file = True
    storage.fail_update = True
    with pytest.raises(SourceError) as caught:
        await SourceService(storage).import_pdf(pdf_bytes, "synthetic.pdf", "local")
    assert caught.value.code == "SOURCE_SAVE_FAILED"
    assert "Any stored original has not been deleted." in caught.value.public_message
    assert not storage.files
