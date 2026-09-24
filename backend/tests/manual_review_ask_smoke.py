"""Opt-in isolated MongoDB/GridFS Ask lifecycle smoke; synthetic and no paid AI.

Run from backend: venv/bin/python tests/manual_review_ask_smoke.py --run-isolated-live
Uses an already-running localhost MongoDB. Only a verified-absent, uniquely named
fixture database is created and removed. No application data or credentials are
read. Provider boundaries are mocked; persistence and source-file reads are real.
"""
import argparse
import asyncio
from contextlib import ExitStack, asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from clauseiq_types.review import (
    ReviewAskAnswerItem, ReviewCoverage, ReviewGeneration, ReviewUsage, ReviewWorkspaceUpdate, StartAskRequest,
)
from services.ai.text_extractor import TextExtractor
from services.file_storage_service import GridFSFileStorage
from services.review_ask_service import ReviewAskService
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService
from services.source_service import SourceService
from manual_source_smoke import document_service, isolated_adapter


PDF_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs" / "managed-services-25p.pdf"
WORKSPACE = "synthetic-ask-workspace"
MODEL = "gpt-6-sol"


async def expect_error(operation, code):
    try:
        await operation
    except ReviewWorkspaceError as error:
        assert error.code == code
    else:
        raise AssertionError("Expected scoped Ask operation to fail")


async def run_smoke():
    suffix = uuid4().hex
    database_name = f"clauseiq_ask_smoke_{suffix}"
    adapter = isolated_adapter(database_name)
    connections, owned_database = [adapter], False
    report = {"passed": False, "checks": [], "cleaned": [], "leftovers": []}
    stage = "connect to existing localhost MongoDB"
    try:
        await adapter.connect()
        assert database_name not in await adapter.client.list_database_names()
        owned_database = True
        db = adapter.database
        assert db.name == database_name
        await db.smoke_owner.insert_one({"id": suffix, "purpose": "review-ask-smoke"})
        legacy = {"id": str(uuid4()), "workspace_id": WORKSPACE, "filename": "legacy-synthetic.pdf",
                  "text": "Unrelated synthetic record", "clauses": [{"id": "old", "text": "Keep this"}],
                  "user_interactions": {"old": {"notes": ["Preserve this note"]}}}
        await db.documents.insert_one(deepcopy(legacy))
        legacy_before = await db.documents.find_one({"id": legacy["id"]})
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError("External provider forbidden")))
                      for target in ("openai.AsyncOpenAI", "openai.OpenAI", "qdrant_client.AsyncQdrantClient",
                                     "qdrant_client.QdrantClient", "services.ai.client_manager.get_openai_client")]
            factory = stack.enter_context(patch("database.factory.DatabaseFactory.get_database", new=AsyncMock(return_value=adapter)))
            files = GridFSFileStorage()
            assert await files.initialize()
            file_factory = stack.enter_context(patch("services.file_storage_service.get_file_storage_service", return_value=files))
            documents = document_service(adapter)
            documents.get_workspace_generation_settings = AsyncMock(return_value={"model_id": MODEL, "reasoning_effort": "medium"})
            documents.get_workspace_api_key = AsyncMock(return_value="synthetic-mocked-credential")
            content = PDF_PATH.read_bytes()
            stage = "synthetic source and immutable reviewed example"
            imported = await SourceService(documents, TextExtractor()).import_pdf(content, PDF_PATH.name, WORKSPACE)
            service = ReviewAskService(documents)
            current = await service.create_fixture(imported["id"], WORKSPACE, 0)
            run, finding = current.runs[0], current.runs[0].findings[1]
            scope = {"run_id": run.id, "finding_id": finding.id}

            async def change(kind, **values):
                state = await service.read(imported["id"], WORKSPACE)
                return await service.update(imported["id"], WORKSPACE, ReviewWorkspaceUpdate(
                    expected_revision=state.revision, operation={"type": kind, **values}))

            current = await change("set_draft", **scope, text="Synthetic negotiation draft")
            current = await change("save_question", **scope, text="Synthetic saved question")
            current = await change("set_ask_draft", **scope, text="Synthetic unsent Ask")
            current = await change("set_marker", **scope, marker="revisit")
            current = await change("set_brief", brief={"perspective": "provider", "priorities": "Changed synthetic brief"})
            generation = ReviewGeneration(model_id=MODEL, reasoning_effort="medium", max_completion_tokens=4000,
                catalog_verified_on="synthetic-smoke", prompt_version="synthetic-ask-v1", schema_version="synthetic-ask-v1",
                extraction_version=imported["source_extraction"]["extraction_version"], estimated_input_tokens=100)
            coverage = ReviewCoverage(page_count=25, extracted_pages=list(range(1, 26)), omitted_pages=[])
            prepared = SimpleNamespace(generation=generation, coverage=coverage)
            result = SimpleNamespace(status="ready", answer=[ReviewAskAnswerItem(
                text="Synthetic source-linked answer for persistence testing.", evidence=[finding.evidence[0]])],
                limitations=[], failure=None, coverage=coverage, generation=generation.model_copy(update={
                    "usage": ReviewUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150), "duration_ms": 1}))

            @asynccontextmanager
            async def mocked_client(key):
                assert key == "synthetic-mocked-credential"
                yield object()

            stack.enter_context(patch("services.review_ask_service.workspace_openai_client", mocked_client))
            preparation = stack.enter_context(patch("services.review_ask_service.prepare_ask", return_value=prepared))

            async def generate_with_edit(*_):
                state = await service.read(imported["id"], WORKSPACE)
                assert state.ask_turns[-1].status == "processing"
                await change("set_ask_draft", **scope, text="Newer synthetic Ask draft")
                return result

            provider = stack.enter_context(patch("services.review_ask_service.generate_ask", new=AsyncMock(side_effect=generate_with_edit)))
            first_request = StartAskRequest(expected_revision=current.revision, request_id="synthetic-ask",
                                           model_id=MODEL, question="Synthetic question about this finding")
            stage = "durable claim and concurrent independent personal edits"
            current = await service.start(imported["id"], WORKSPACE, run.id, finding.id, first_request)
            assert current.ask_turns[0].status == "ready" and current.ask_turns[0].generation.usage.total_tokens == 150
            assert current.personal[run.id].ask_drafts[finding.id] == "Newer synthetic Ask draft"
            assert current.personal[run.id].drafts[finding.id] == "Synthetic negotiation draft"
            assert current.personal[run.id].saved_questions[finding.id].text == "Synthetic saved question"
            assert current.personal[run.id].markers[finding.id] == "revisit"
            assert current.runs[0] == run and preparation.call_args.args[1] == run
            report["checks"].append("real Ask claim/final persistence preserves concurrent Ask draft, saved question, markers and original review context")

            stage = "key-free replay and fresh connection restore"
            documents.get_workspace_api_key.reset_mock()
            documents.get_workspace_api_key.side_effect = AssertionError("Credential access forbidden during replay")
            assert await service.start(imported["id"], WORKSPACE, run.id, finding.id, first_request) == current
            documents.get_workspace_api_key.assert_not_awaited()
            provider.assert_awaited_once()
            fresh_adapter = isolated_adapter(database_name)
            connections.append(fresh_adapter)
            await fresh_adapter.connect()
            factory.return_value = fresh_adapter
            fresh_files = GridFSFileStorage()
            assert await fresh_files.initialize()
            file_factory.return_value = fresh_files
            fresh_documents = document_service(fresh_adapter)
            fresh_documents.get_workspace_api_key = AsyncMock(side_effect=AssertionError("Credential access forbidden on read"))
            assert await ReviewWorkspaceService(fresh_documents).read(imported["id"], WORKSPACE) == current
            assert (await fresh_documents.get_pdf_file(imported["id"], WORKSPACE))["content"] == content
            fresh_documents.get_workspace_api_key.assert_not_awaited()
            report["checks"].append("same request never recharges; fresh connection restores exact source evidence and original PDF without reading a key")

            stage = "history and stale-write isolation"
            documents.get_workspace_api_key.side_effect = None
            documents.get_workspace_api_key.return_value = "synthetic-mocked-credential"
            provider.side_effect = None
            provider.return_value = result
            next_request = StartAskRequest(expected_revision=current.revision, request_id="synthetic-followup", model_id=MODEL,
                                           question="Synthetic follow-up")
            current = await service.start(imported["id"], WORKSPACE, run.id, finding.id, next_request)
            assert current.ask_turns[-1].history_turn_ids == ["synthetic-ask"]
            await expect_error(service.update(imported["id"], WORKSPACE, ReviewWorkspaceUpdate(expected_revision=0,
                operation={"type": "set_ask_draft", **scope, "text": "Obsolete draft"})), "REVISION_CONFLICT")
            assert current == await service.read(imported["id"], WORKSPACE)
            report["checks"].append("same-finding history IDs persist and stale writes cannot overwrite newer draft")

            stage = "explicit interrupt fences late output"
            async def interrupt_during_generation(*_):
                state = await service.read(imported["id"], WORKSPACE)
                await service.interrupt(imported["id"], WORKSPACE, "synthetic-interrupt", state.revision)
                return result
            provider.side_effect = interrupt_during_generation
            current = await service.start(imported["id"], WORKSPACE, run.id, finding.id, StartAskRequest(
                expected_revision=current.revision, request_id="synthetic-interrupt", model_id=MODEL, question="Synthetic interruption"))
            assert current.ask_turns[-1].status == "interrupted" and current.ask_turns[-1].answer == []
            report["checks"].append("real interrupted state takes precedence over late provider output")

            stage = "scope and source deletion fence"
            await expect_error(service.read(imported["id"], "other-workspace"), "DOCUMENT_NOT_FOUND")
            await expect_error(service.start(imported["id"], WORKSPACE, run.id, "other-finding", StartAskRequest(
                expected_revision=current.revision, request_id="wrong-finding", model_id=MODEL, question="Wrong scope")), "FINDING_NOT_FOUND")
            assert await db.documents.find_one({"id": legacy["id"]}) == legacy_before
            cleanup = SimpleNamespace(delete_document_from_rag=AsyncMock(return_value=True))
            stack.enter_context(patch("services.rag_service.get_rag_service", return_value=cleanup))
            async def delete_during_generation(*_):
                assert await documents.delete_document_for_workspace(imported["id"], WORKSPACE)
                return result
            provider.side_effect = delete_during_generation
            await expect_error(service.start(imported["id"], WORKSPACE, run.id, finding.id, StartAskRequest(
                expected_revision=current.revision, request_id="synthetic-deleted", model_id=MODEL, question="Synthetic deleted source")), "DOCUMENT_NOT_FOUND")
            assert await db.documents.find_one({"id": imported["id"]}) is None
            assert await db["pdf_files.files"].count_documents({}) == 0
            assert await db.documents.find_one({"id": legacy["id"]}) == legacy_before
            assert set(await db.list_collection_names()) == {"smoke_owner", "documents", "pdf_files.files", "pdf_files.chunks"}
            report["checks"].append("wrong scope rejected and unrelated legacy state untouched; deletion cannot be undone by late answer")
            for guard in guards:
                guard.assert_not_called()
            report["passed"] = True
    except Exception as error:
        report["failed_check"], report["error_type"] = stage, type(error).__name__
    finally:
        if owned_database:
            try:
                assert database_name == f"clauseiq_ask_smoke_{suffix}"
                assert len(suffix) == 32 and all(character in "0123456789abcdef" for character in suffix)
                assert adapter.config.database == database_name
                await adapter.client.drop_database(database_name)
                assert database_name not in await adapter.client.list_database_names()
                report["cleaned"].append("isolated MongoDB/GridFS Ask fixture database")
            except Exception:
                report["leftovers"].append({"mongodb_database": database_name})
        for connection in connections:
            await connection.disconnect()
        if report["leftovers"]:
            report["passed"] = False
        print(json.dumps(report, indent=2))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-live", action="store_true", help="Permit disposable localhost MongoDB/GridFS fixtures")
    args = parser.parse_args()
    if not args.run_isolated_live:
        parser.error("Pass --run-isolated-live to create and remove disposable localhost fixtures.")
    raise SystemExit(0 if asyncio.run(run_smoke()) else 1)
