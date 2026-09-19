"""Library summaries are scoped, content-free reads, not review generation."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from database.interface import ConnectionConfig, DatabaseBackend, DatabaseError
from database.library_summary import LIBRARY_FIELDS, library_item, library_projection
from database.mongodb_adapter import MongoDBAdapter
from database.service import DocumentService
from models.document import DocumentListResponse
from routers import documents


def run(*, run_id="run-1", kind="fixture", status="ready"):
    return {
        "id": run_id, "kind": kind, "status": status, "status_type": "string", "type": "object",
        "source_revision_id": "source-1", "created_at": "2026-09-18T10:00:00Z",
        "completed_at": None if status == "processing" else "2026-09-18T10:01:00Z",
        "generation_type": "object" if kind == "ai" else "missing",
        "coverage_type": "object" if kind == "ai" else "missing",
        "omitted_type": "array" if kind == "ai" else "missing",
        "omitted_count": 1 if status == "incomplete" else 0,
        "failure_type": "object" if status in ("failed", "interrupted") else "null",
        "overview_type": "array", "overview_count": 1 if status in ("ready", "incomplete") else 0,
        "has_overview": False, "findings_type": "array",
        "finding_ids": ["finding-1"] if status in ("ready", "incomplete") else [],
    }


def question(*, saved_at="2026-09-18T12:00:00Z"):
    return {"id": "question-1", "finding_id": "finding-1", "saved_at": saved_at,
            "type": "object", "text_type": "string", "text_length": 12}


def projected(*, runs=None, questions=None):
    return {
        "id": "doc-1", "filename": "synthetic.pdf", "upload_date": "2026-09-18T09:00:00Z",
        "source_revision_id": "source-1", "source_status": "stored", "extraction_status": "complete",
        "analysis_status": "not_started", "page_count": 25, "last_viewed": None,
        "_library": {
            "has_pdf_file": True, "state_type": "object", "document_id": "doc-1",
            "source_revision_id": "source-1", "revision": 1, "runs_type": "array",
            "runs": [run()] if runs is None else runs, "personal_type": "object",
            "personal": [] if questions is None else [{"run_id": "run-1", "type": "object",
                "questions_type": "object", "questions": questions}],
        },
    }


def summary(item):
    return library_item(item)["review_summary"]


def test_fixture_state_is_separate_from_legacy_analysis_and_counts_latest_personal_work():
    record = projected(questions=[question()])
    result = library_item(record)
    assert result["analysis_status"] == "not_started"
    assert result["page_count"] == 25
    assert result["review_summary"] == {
        "kind": "fixture", "status": "ready", "saved_question_count": 1,
        "last_activity_at": "2026-09-18T12:00:00+00:00", "can_resume": True,
    }
    assert record["_library"]["runs"][0]["status"] == "ready"


def test_old_fixture_without_status_remains_readable():
    record = projected()
    record["_library"]["runs"][0].pop("status")
    record["_library"]["runs"][0]["status_type"] = "missing"
    assert summary(record)["status"] == "ready"
    assert summary(record)["can_resume"] is True


@pytest.mark.parametrize("status", ["ready", "incomplete", "processing", "failed", "interrupted"])
def test_latest_run_matches_workspace_array_selection_without_success_fallback(status):
    record = projected(runs=[run(), run(run_id="run-2", kind="ai", status=status)], questions=[question()])
    result = summary(record)
    assert (result["kind"], result["status"]) == ("ai", status)
    assert result["saved_question_count"] == 0  # No misleading total from another run.
    assert result["can_resume"] is (status in ("ready", "incomplete"))


def test_run_order_not_timestamp_order_selects_the_displayed_run():
    record = projected(runs=[run(kind="ai"), run(run_id="run-2")])
    record["_library"]["runs"][0]["created_at"] = "2030-01-01T00:00:00Z"
    assert summary(record)["kind"] == "fixture"


@pytest.mark.parametrize("state_type", ["missing", "null"])
def test_absent_saved_workspace_never_fabricates_review_or_resume(state_type):
    record = projected()
    record["_library"] = {"state_type": state_type}
    assert summary(record) == {"kind": None, "status": "not_started", "saved_question_count": 0,
                               "last_activity_at": None, "can_resume": False}
    record.pop("source_revision_id")
    record.pop("source_status")
    assert summary(record)["can_resume"] is False
    assert "source_revision_id" not in library_item(record)


def test_empty_workspace_has_not_started_status_and_view_only_activity():
    record = projected(runs=[])
    record["last_viewed"] = "2026-09-19T10:00:00"  # Legacy UTC-naive view timestamp.
    record["updated_at"] = "2030-01-01T00:00:00Z"
    result = summary(record)
    assert result["status"] == "not_started" and result["can_resume"] is False
    assert result["last_activity_at"] == "2026-09-19T10:00:00+00:00"


def test_activity_uses_real_persisted_events_and_ignores_invalid_timestamps():
    record = projected(questions=[question(saved_at="not a timestamp")])
    record["last_viewed"] = "2026-09-18T17:00:00+05:30"
    record["upload_date"] = "2030-01-01T00:00:00Z"
    record["updated_at"] = "2030-01-01T00:00:00Z"
    assert summary(record)["last_activity_at"] == "2026-09-18T11:30:00+00:00"


@pytest.mark.parametrize("field,value", [
    ("state_type", "array"), ("document_id", "other-document"), ("source_revision_id", "other-source"),
    ("revision", True), ("revision", -1), ("runs_type", "object"), ("personal_type", "array"),
    ("has_pdf_file", False), ("runs", [None]), ("personal", [{"run_id": "missing", "type": "object"}]),
])
def test_invalid_workspace_metadata_is_unavailable_not_ready(field, value):
    record = projected()
    record["_library"][field] = value
    result = summary(record)
    assert result["status"] == "unavailable" and result["can_resume"] is False


@pytest.mark.parametrize("field,value", [
    ("source_revision_id", "other-source"), ("status", "unknown"), ("status", {}), ("kind", "unknown"),
    ("generation_type", "missing"), ("coverage_type", "missing"), ("omitted_type", "string"),
    ("omitted_count", 1), ("failure_type", "object"), ("overview_count", 0),
    ("completed_at", None), ("finding_ids", ["finding-1", "finding-1"]),
])
def test_invalid_ready_run_metadata_cannot_promote_resume(field, value):
    record = projected(runs=[run(kind="ai")])
    record["_library"]["runs"][0][field] = value
    assert summary(record)["status"] == "unavailable"
    assert summary(record)["can_resume"] is False


def test_duplicate_run_identity_and_orphaned_question_are_unavailable():
    assert summary(projected(runs=[run(), run()]))["status"] == "unavailable"
    record = projected(questions=[{**question(), "finding_id": "other-finding"}])
    assert summary(record)["status"] == "unavailable"


@pytest.mark.parametrize("length", [0, 5001, True, "12"])
def test_invalid_saved_question_length_is_not_counted_as_confirmed_work(length):
    record = projected(questions=[{**question(), "text_length": length}])
    assert summary(record)["status"] == "unavailable"
    assert summary(record)["saved_question_count"] == 0


@pytest.mark.parametrize("count", [None, "25", True, -1])
def test_unknown_or_invalid_page_count_is_not_invented(count):
    record = projected()
    record["page_count"] = count
    assert library_item(record)["page_count"] is None


def test_public_allowlist_omits_projection_internals_and_content_even_with_extra_fields():
    record = projected()
    record.update(text="private source", review_workspace={"findings": "private review"},
                  api_key="private credential", source_extraction={"text": "private extraction"})
    result = library_item(record)
    assert set(result).issubset({*LIBRARY_FIELDS, "page_count", "review_summary"})
    assert "private" not in str(result)
    assert DocumentListResponse(documents=[result]).documents[0].review_summary.status == "ready"


def test_projection_references_no_source_or_review_wording_or_credential_values():
    projection = library_projection()
    assert projection["_id"] == 0
    assert "review_workspace" not in projection and "source_extraction" not in projection
    assert projection["page_count"] == "$source_extraction.page_count"
    run_projection = projection["_library"]["runs"]["$map"]["in"]
    assert "findings" not in run_projection and "overview" not in run_projection
    question_projection = projection["_library"]["personal"]["$map"]["in"]["questions"]["$map"]["in"]
    assert "text" not in question_projection
    assert question_projection["text_type"] == {"$type": "$$question.v.text"}
    assert not any(key in str(projection) for key in ("api_key", "credential", "source_extraction.text", "evidence", "$$ROOT"))


@pytest.mark.asyncio
async def test_single_scoped_projection_keeps_pagination_and_never_loads_individual_documents():
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[projected()]))
    cursor.skip = Mock(return_value=cursor)
    cursor.limit = Mock(return_value=cursor)
    collection = SimpleNamespace(find=Mock(return_value=cursor), find_one=AsyncMock(side_effect=AssertionError("N+1 read")))
    adapter = MongoDBAdapter(ConnectionConfig(DatabaseBackend.MONGODB, "unused", "test"))
    adapter._get_collection = Mock(return_value=collection)
    result = await adapter.list_document_summaries("test-workspace", limit=25, offset=3)
    collection.find.assert_called_once_with({"workspace_id": "test-workspace"}, library_projection())
    adapter._get_collection.assert_called_once_with("documents")
    cursor.skip.assert_called_once_with(3)
    cursor.limit.assert_called_once_with(25)
    cursor.to_list.assert_awaited_once_with(length=25)
    collection.find_one.assert_not_awaited()
    assert result[0]["review_summary"]["kind"] == "fixture"


@pytest.mark.asyncio
async def test_library_default_has_no_fifty_document_cap():
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[projected() for _ in range(65)]))
    cursor.skip = Mock(return_value=cursor)
    cursor.limit = Mock(return_value=cursor)
    adapter = MongoDBAdapter(ConnectionConfig(DatabaseBackend.MONGODB, "unused", "test"))
    adapter._get_collection = Mock(return_value=SimpleNamespace(find=Mock(return_value=cursor)))
    assert len(await adapter.list_document_summaries("local")) == 65
    cursor.to_list.assert_awaited_once_with(length=None)
    cursor.limit.assert_called_once_with(0)


@pytest.mark.asyncio
async def test_route_uses_only_library_summary_path(monkeypatch):
    service = DocumentService()
    service._db = SimpleNamespace(list_document_summaries=AsyncMock(return_value=[library_item(projected())]),
                                  list_documents=AsyncMock(side_effect=AssertionError("Full list")))
    service.get_workspace_api_key = AsyncMock(side_effect=AssertionError("Credential lookup"))
    monkeypatch.setattr(documents, "get_document_service", lambda: service)
    response = await documents.list_documents(workspace_id="test-workspace")
    assert response.data.documents[0].review_summary.status == "ready"
    service._db.list_document_summaries.assert_awaited_once_with("test-workspace", 0, 0)
    service._db.list_documents.assert_not_awaited()
    service.get_workspace_api_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_projection_failure_has_safe_error_and_no_fallback(caplog):
    adapter = MongoDBAdapter(ConnectionConfig(DatabaseBackend.MONGODB, "unused", "test"))
    adapter._get_collection = Mock(side_effect=RuntimeError("private source and key detail"))
    with pytest.raises(DatabaseError, match="Failed to list document summaries"):
        await adapter.list_document_summaries("local")
    assert "private source" not in caplog.text
