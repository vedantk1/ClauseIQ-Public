"""Focused source-storage safety checks without live services or AI calls."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.interface import ConnectionConfig, DatabaseBackend, DatabaseError
from database.mongodb_adapter import MongoDBAdapter
from database.service import DocumentService
from services import file_storage_service


def adapter_for(collection):
    adapter = MongoDBAdapter(ConnectionConfig(
        backend=DatabaseBackend.MONGODB,
        uri="mongodb://127.0.0.1:27017",
        database="synthetic_source_storage",
    ))
    adapter.database = {"documents": collection}
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("matched,modified,expected_result", [(1, 1, True), (1, 0, True), (0, 0, False)])
async def test_conditional_update_is_scoped_never_upserts_and_uses_match_count(matched, modified, expected_result):
    collection = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(
        matched_count=matched, modified_count=modified,
    )))
    adapter = adapter_for(collection)
    expected = {"source_revision_id": "source-1", "extraction_status": "processing", "extraction_attempt_id": "attempt-1"}
    updates = {"extraction_status": "ready"}
    original_expected, original_updates = deepcopy(expected), deepcopy(updates)

    result = await adapter.update_document_if("doc-1", "local", expected, updates)

    assert result is expected_result
    query, operation = collection.update_one.await_args.args
    assert query == {"$and": [{"id": "doc-1", "workspace_id": "local"}, expected]}
    assert operation["$set"]["extraction_status"] == "ready"
    assert "updated_at" in operation["$set"]
    assert collection.update_one.await_args.kwargs == {"upsert": False}
    assert expected == original_expected and updates == original_updates


class ClaimCollection:
    """Atomic equality-only collection double for lifecycle claim tests."""

    def __init__(self):
        self.record = {"id": "doc-1", "workspace_id": "local", "extraction_status": "pending"}

    async def update_one(self, query, operation, *, upsert):
        assert upsert is False
        matches = all(
            all(self.record.get(key) == value for key, value in condition.items())
            for condition in query["$and"]
        )
        if matches:
            self.record.update(deepcopy(operation["$set"]))
        return SimpleNamespace(matched_count=int(matches))


@pytest.mark.asyncio
async def test_competing_claims_have_one_winner_and_late_completion_is_rejected():
    collection = ClaimCollection()
    adapter = adapter_for(collection)
    claims = await asyncio.gather(*[
        adapter.update_document_if(
            "doc-1", "local", {"extraction_status": "pending"},
            {"extraction_status": "processing", "extraction_attempt_id": token},
        ) for token in ("attempt-1", "attempt-2")
    ])
    assert claims.count(True) == 1
    winner = collection.record["extraction_attempt_id"]
    loser = "attempt-2" if winner == "attempt-1" else "attempt-1"
    assert not await adapter.update_document_if(
        "doc-1", "local", {"extraction_status": "processing", "extraction_attempt_id": loser},
        {"extraction_status": "ready", "text": "Obsolete result"},
    )
    assert "text" not in collection.record
    assert await adapter.update_document_if(
        "doc-1", "local", {"extraction_status": "processing", "extraction_attempt_id": winner},
        {"extraction_status": "ready", "text": "Current result"},
    )
    assert collection.record["text"] == "Current result"


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id,workspace_id,expected", [
    ("doc-2", "local", {}),
    ("doc-1", "other", {}),
    ("doc-1", "other", {"workspace_id": "local"}),
    ("doc-2", "local", {"id": "doc-1"}),
])
async def test_expected_conditions_cannot_replace_identity_scope(document_id, workspace_id, expected):
    collection = ClaimCollection()
    original = deepcopy(collection.record)
    result = await adapter_for(collection).update_document_if(
        document_id, workspace_id, expected, {"extraction_status": "processing"},
    )
    assert result is False
    assert collection.record == original


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_field", ["id", "workspace_id", "_id", "workspace_id.nested"])
async def test_conditional_update_cannot_change_identity(identity_field):
    collection = SimpleNamespace(update_one=AsyncMock())
    with pytest.raises(DatabaseError, match="^Failed to conditionally update document$"):
        await adapter_for(collection).update_document_if("doc-1", "local", {}, {identity_field: "other"})
    collection.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_conditional_database_failure_is_safe_and_not_a_stale_claim(caplog):
    collection = SimpleNamespace(update_one=AsyncMock(side_effect=RuntimeError("synthetic internal detail")))
    with pytest.raises(DatabaseError, match="^Failed to conditionally update document$"):
        await adapter_for(collection).update_document_if("doc-1", "local", {}, {"extraction_status": "processing"})
    assert "synthetic internal detail" not in caplog.text


@pytest.mark.asyncio
async def test_service_conditional_update_passes_scope_and_distinguishes_failure():
    service = DocumentService()
    service._db = SimpleNamespace(update_document_if=AsyncMock(return_value=False))
    expected = {"extraction_attempt_id": "attempt-1"}
    update = {"extraction_status": "ready"}
    assert not await service.update_document_if("doc-1", "local", expected, update)
    service._db.update_document_if.assert_awaited_once_with("doc-1", "local", expected, update)
    service._db.update_document_if.side_effect = RuntimeError("synthetic internal detail")
    with pytest.raises(DatabaseError, match="^Failed to conditionally update document$"):
        await service.update_document_if("doc-1", "local", expected, update)


@pytest.fixture
def storage_context(monkeypatch):
    original = {"id": "doc-1", "workspace_id": "local", "pdf_file_id": "previous-file", "has_pdf_file": True}
    database = SimpleNamespace(
        get_document=AsyncMock(return_value=original),
        update_document=AsyncMock(return_value=True),
    )
    files = SimpleNamespace(
        store_file=AsyncMock(return_value="new-file"),
        delete_file=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(file_storage_service, "get_file_storage_service", lambda: files)
    service = DocumentService()
    service._db = database
    return service, database, files, original


async def store_pdf(service):
    return await service.store_pdf_file("doc-1", "local", b"%PDF-synthetic", "synthetic.pdf")


@pytest.mark.asyncio
async def test_pdf_requires_existing_scoped_document_before_upload(storage_context):
    service, database, files, _ = storage_context
    database.get_document.return_value = None
    assert not await store_pdf(service)
    database.get_document.assert_awaited_once_with("doc-1", "local")
    files.store_file.assert_not_awaited()
    database.update_document.assert_not_awaited()
    files.delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_success_attaches_source_and_preserves_previous_file(storage_context):
    service, database, files, original = storage_context
    assert await store_pdf(service)
    files.store_file.assert_awaited_once_with(
        file_data=b"%PDF-synthetic", filename="synthetic.pdf", content_type="application/pdf",
        workspace_id="local", metadata={"document_id": "doc-1"},
    )
    document_id, workspace_id, metadata = database.update_document.await_args.args
    assert (document_id, workspace_id) == ("doc-1", "local")
    assert metadata["pdf_file_id"] == "new-file" and metadata["has_pdf_file"] is True
    assert original["pdf_file_id"] == "previous-file"
    files.delete_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, RuntimeError("synthetic internal detail")])
async def test_pdf_pointer_failure_rolls_back_only_confirmed_unattached_new_file(storage_context, outcome):
    service, database, files, original = storage_context
    if isinstance(outcome, Exception):
        database.update_document.side_effect = outcome
    else:
        database.update_document.return_value = outcome
    assert not await store_pdf(service)
    assert database.get_document.await_count == 2
    assert all(call.args == ("doc-1", "local") for call in database.get_document.await_args_list)
    files.delete_file.assert_awaited_once_with("new-file", "local")
    assert original["pdf_file_id"] == "previous-file"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, RuntimeError("synthetic internal detail")])
async def test_pdf_uncertain_write_succeeds_when_pointer_readback_confirms_attachment(storage_context, outcome):
    service, database, files, original = storage_context
    database.get_document.side_effect = [original, {**original, "pdf_file_id": "new-file"}]
    if isinstance(outcome, Exception):
        database.update_document.side_effect = outcome
    else:
        database.update_document.return_value = outcome
    assert await store_pdf(service)
    files.delete_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, RuntimeError("synthetic internal detail")])
async def test_pdf_pointer_uncertainty_retains_file_when_readback_fails(storage_context, outcome, caplog):
    service, database, files, original = storage_context
    database.get_document.side_effect = [original, RuntimeError("synthetic pointer detail")]
    if isinstance(outcome, Exception):
        database.update_document.side_effect = outcome
    else:
        database.update_document.return_value = outcome
    assert not await store_pdf(service)
    files.delete_file.assert_not_awaited()
    assert "stored file retained" in caplog.text
    assert "synthetic internal detail" not in caplog.text
    assert "synthetic pointer detail" not in caplog.text


@pytest.mark.asyncio
async def test_pdf_attached_pointer_with_incomplete_metadata_is_retained(storage_context):
    service, database, files, original = storage_context
    database.update_document.return_value = False
    database.get_document.side_effect = [original, {**original, "pdf_file_id": "new-file", "has_pdf_file": False}]
    assert not await store_pdf(service)
    files.delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_document_removed_during_upload_rolls_back_new_file(storage_context):
    service, database, files, original = storage_context
    database.update_document.return_value = False
    database.get_document.side_effect = [original, None]
    assert not await store_pdf(service)
    files.delete_file.assert_awaited_once_with("new-file", "local")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, RuntimeError("synthetic cleanup detail")])
async def test_pdf_cleanup_failure_is_not_reported_as_success(storage_context, outcome):
    service, database, files, _ = storage_context
    database.update_document.return_value = False
    if isinstance(outcome, Exception):
        files.delete_file.side_effect = outcome
    else:
        files.delete_file.return_value = outcome
    assert not await store_pdf(service)
    files.delete_file.assert_awaited_once_with("new-file", "local")


@pytest.mark.asyncio
async def test_pdf_upload_failure_never_updates_pointer_or_deletes_existing_file(storage_context):
    service, database, files, original = storage_context
    files.store_file.side_effect = RuntimeError("synthetic upload detail")
    assert not await store_pdf(service)
    database.update_document.assert_not_awaited()
    files.delete_file.assert_not_awaited()
    assert original["pdf_file_id"] == "previous-file"
