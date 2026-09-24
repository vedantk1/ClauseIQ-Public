"""Opt-in real MongoDB/GridFS review persistence smoke, using synthetic data only.

Run from backend: venv/bin/python tests/manual_review_workspace_smoke.py --run-isolated-live
Uses the existing localhost MongoDB service. A verified-absent random database is
created for this test and explicitly cleaned up; application data, settings and
credentials are never accessed. No AI or vector provider is called.
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
    ReviewCoverage, ReviewEvidence, ReviewGeneration, ReviewOverviewItem, ReviewWorkspaceUpdate, StartReviewRequest,
)
from services.ai.text_extractor import TextExtractor
from services.file_storage_service import GridFSFileStorage
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService
from services.review_generation_service import ReviewGenerationService
from services.source_service import SourceService
from manual_source_smoke import document_service, isolated_adapter


PDF_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs" / "managed-services-25p.pdf"
WORKSPACE = "synthetic-review-workspace"


async def expect_error(operation, code):
    try:
        await operation
    except ReviewWorkspaceError as error:
        assert error.code == code
    else:
        raise AssertionError("Expected review operation to fail")


async def run_smoke():
    suffix = uuid4().hex
    database_name = f"clauseiq_review_smoke_{suffix}"
    adapter = isolated_adapter(database_name)
    connections = [adapter]
    owned_database = False
    report = {"passed": False, "checks": [], "cleaned": [], "leftovers": []}
    stage = "connect to existing localhost MongoDB"
    try:
        await adapter.connect()
        assert database_name not in await adapter.client.list_database_names()
        owned_database = True
        db = adapter.database
        assert db.name == database_name
        await db.smoke_owner.insert_one({"id": suffix, "purpose": "review-workspace-smoke"})
        legacy = {"id": str(uuid4()), "workspace_id": WORKSPACE, "filename": "legacy-synthetic.pdf",
                  "text": "Unrelated synthetic record", "clauses": [{"id": "old", "text": "Keep this"}],
                  "user_interactions": {"old": {"notes": ["Preserve this note"]}}}
        await db.documents.insert_one(deepcopy(legacy))
        legacy_before = await db.documents.find_one({"id": legacy["id"]})

        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError("External provider access forbidden")))
                      for target in ("openai.AsyncOpenAI", "openai.OpenAI", "qdrant_client.AsyncQdrantClient",
                                     "qdrant_client.QdrantClient", "services.ai.client_manager.get_openai_client")]
            factory = stack.enter_context(patch("database.factory.DatabaseFactory.get_database", new=AsyncMock(return_value=adapter)))
            files = GridFSFileStorage()
            assert await files.initialize()
            file_factory = stack.enter_context(patch("services.file_storage_service.get_file_storage_service", return_value=files))
            documents = document_service(adapter)
            documents.get_workspace_api_key = AsyncMock(side_effect=AssertionError("Credential access forbidden"))
            stage = "source import and read-only workspace"
            content = PDF_PATH.read_bytes()
            imported = await SourceService(documents, TextExtractor()).import_pdf(content, PDF_PATH.name, WORKSPACE)
            service = ReviewWorkspaceService(documents)
            current = await service.read(imported["id"], WORKSPACE)
            assert current.revision == 0 and current.fixture_available
            assert "review_workspace" not in await db.documents.find_one({"id": imported["id"]})

            stage = "fixture and independent personal work"
            current = await service.create_fixture(imported["id"], WORKSPACE, 0)
            assert len(current.runs) == 1 and current.runs[0].kind == "fixture"
            run, finding = current.runs[0], current.runs[0].findings[1]

            async def change(expected, kind, **values):
                return await service.update(imported["id"], WORKSPACE, ReviewWorkspaceUpdate(
                    expected_revision=expected, operation={"type": kind, **values},
                ))

            scope = {"run_id": run.id, "finding_id": finding.id}
            current = await change(current.revision, "save_question", **scope, text="Synthetic saved question")
            saved_id = current.personal[run.id].saved_questions[finding.id].id
            current = await change(current.revision, "set_draft", **scope, text="Synthetic newer draft")
            current = await change(current.revision, "set_marker", **scope, marker="revisit")
            current = await change(current.revision, "set_position", run_id=run.id, position={
                "view": "findings", "finding_id": finding.id, "evidence_span_id": finding.evidence[0].span_id,
            })
            report["checks"].append("fixture evidence, saved question, independent newer draft, marker and resume position persisted")

            stage = "fresh connection restoration and stale write"
            fresh_adapter = isolated_adapter(database_name)
            connections.append(fresh_adapter)
            await fresh_adapter.connect()
            factory.return_value = fresh_adapter
            fresh_files = GridFSFileStorage()
            assert await fresh_files.initialize()
            file_factory.return_value = fresh_files
            fresh_documents = document_service(fresh_adapter)
            fresh_service = ReviewWorkspaceService(fresh_documents)
            assert await fresh_service.read(imported["id"], WORKSPACE) == current
            assert (await fresh_documents.get_pdf_file(imported["id"], WORKSPACE))["content"] == content
            await expect_error(change(current.revision - 1, "set_draft", **scope, text="Obsolete draft"), "REVISION_CONFLICT")
            assert await fresh_service.read(imported["id"], WORKSPACE) == current
            report["checks"].append("fresh service and connection restore all state; stale revision cannot overwrite newer text")

            stage = "confirmed question removal preserves drafts and unrelated personal work"
            before_remove = current
            current = await change(current.revision, "remove_question", **scope)
            assert finding.id not in current.personal[run.id].saved_questions
            assert current.personal[run.id].drafts[finding.id] == "Synthetic newer draft"
            assert current.personal[run.id].markers == before_remove.personal[run.id].markers
            assert current.personal[run.id].position == before_remove.personal[run.id].position
            assert current.runs == before_remove.runs and current.ask_turns == before_remove.ask_turns
            assert await fresh_service.read(imported["id"], WORKSPACE) == current
            await expect_error(change(before_remove.revision, "remove_question", **scope), "REVISION_CONFLICT")
            assert await change(current.revision, "remove_question", **scope) == current
            current = await change(current.revision, "save_question", **scope, text="Synthetic saved question")
            assert current.personal[run.id].saved_questions[finding.id].id == saved_id

            other_scope = {"run_id": run.id, "finding_id": run.findings[0].id}
            current = await change(current.revision, "save_question", **other_scope, text="Synthetic recoverable wording")
            assert other_scope["finding_id"] not in current.personal[run.id].drafts
            current = await change(current.revision, "remove_question", **other_scope)
            assert current.personal[run.id].drafts[other_scope["finding_id"]] == "Synthetic recoverable wording"
            assert current.personal[run.id].saved_questions[finding.id].id == saved_id
            assert await fresh_service.read(imported["id"], WORKSPACE) == current
            report["checks"].append("confirmed question removal persists, preserves newer drafts/markers/run and rejects stale replay; missing draft recovers wording; fresh-revision replay is a no-op")

            stage = "competing real conditional writes"
            operations = [ReviewWorkspaceUpdate(expected_revision=current.revision, operation={
                "type": "set_brief", "brief": {"perspective": "neutral", "role": "", "priorities": priority},
            }) for priority in ("Synthetic payment priority", "Synthetic exit priority")]
            results = await asyncio.gather(*[
                fresh_service.update(imported["id"], WORKSPACE, operation) for operation in operations
            ], return_exceptions=True)
            assert sum(not isinstance(result, Exception) for result in results) == 1
            conflict = next(result for result in results if isinstance(result, Exception))
            assert isinstance(conflict, ReviewWorkspaceError) and conflict.code == "REVISION_CONFLICT"
            current = await fresh_service.read(imported["id"], WORKSPACE)
            assert current.runs[0] == run
            assert current.personal[run.id].saved_questions[finding.id].id == saved_id
            assert await fresh_service.create_fixture(imported["id"], WORKSPACE, 0) == current
            assert len(current.runs) == 1
            report["checks"].append("real MongoDB CAS permits one winner; changed brief preserves immutable run and stable question identity")

            stage = "mocked review generation preserves real persisted concurrent edits"
            # The provider/credential boundary is mocked; source/review writes,
            # competing revisions and fresh-connection reads use real MongoDB.
            coverage = ReviewCoverage(page_count=25, extracted_pages=list(range(1, 26)), omitted_pages=[])
            generation = ReviewGeneration(
                model_id="gpt-5.6-terra", reasoning_effort="low", max_completion_tokens=1000,
                catalog_verified_on="synthetic-smoke", prompt_version="synthetic-smoke-v1",
                schema_version="synthetic-smoke-v1", extraction_version=imported["source_extraction"]["extraction_version"],
                estimated_input_tokens=100,
            )
            prepared = SimpleNamespace(coverage=coverage, generation=generation)
            passage_page = next(page for page in imported["source_extraction"]["pages"] if len(page["spans"]) >= 3)
            first, last = passage_page["spans"][0], passage_page["spans"][2]
            passage = ReviewEvidence(
                source_revision_id=imported["source_revision_id"], span_id=first["id"], end_span_id=last["id"],
                page_number=passage_page["page_number"],
                quote=passage_page["text"][first["start"]:last["end"]], label="Synthetic exact multi-line passage",
            )
            assert "\n" in passage.quote and passage.span_id != passage.end_span_id
            range_finding = finding.model_copy(update={"evidence": [passage]}, deep=True)
            result = SimpleNamespace(
                status="ready", coverage=coverage, generation=generation,
                overview_items=[ReviewOverviewItem(text="Synthetic review overview", evidence=[passage])],
                findings=[range_finding], failure=None,
            )
            fresh_documents.get_workspace_api_key = AsyncMock(return_value="synthetic-mocked-credential")
            fresh_documents.get_workspace_generation_settings = AsyncMock(return_value={
                "model_id": "gpt-6-sol", "reasoning_effort": "medium"})

            @asynccontextmanager
            async def mocked_client(key):
                assert key == "synthetic-mocked-credential"
                yield object()

            stack.enter_context(patch("services.review_generation_service.workspace_openai_client", mocked_client))
            stack.enter_context(patch("services.review_generation_service.prepare_review", return_value=prepared))

            async def generate_with_edit(*_):
                processing = await fresh_service.read(imported["id"], WORKSPACE)
                assert processing.runs[-1].status == "processing"
                await fresh_service.update(imported["id"], WORKSPACE, ReviewWorkspaceUpdate(
                    expected_revision=processing.revision, operation={"type": "set_brief", "brief": {
                        "perspective": "customer", "priorities": "Concurrent synthetic priority retained",
                    }},
                ))
                return result

            provider = stack.enter_context(patch("services.review_generation_service.generate_review", new=AsyncMock(side_effect=generate_with_edit)))
            generated_service = ReviewGenerationService(fresh_documents)
            initial_request = StartReviewRequest(expected_revision=current.revision, request_id="synthetic-attempt", model_id="gpt-6-sol")
            current = await generated_service.start(imported["id"], WORKSPACE, initial_request)
            assert current.runs[-1].status == "ready"
            assert current.brief.priorities == "Concurrent synthetic priority retained"
            assert current.runs[-1].context.priorities != current.brief.priorities
            assert current.personal[run.id].saved_questions[finding.id].id == saved_id
            assert current.runs[0] == run
            assert await service.read(imported["id"], WORKSPACE) == current
            restored = await ReviewWorkspaceService(document_service(fresh_adapter)).read(imported["id"], WORKSPACE)
            assert restored.runs[-1].findings[0].evidence[0] == passage
            assert restored.runs[-1].overview_items[0].evidence[0] == passage
            assert all(item.end_span_id is None for old in restored.runs[0].findings for item in old.evidence)
            current = await fresh_service.update(imported["id"], WORKSPACE, ReviewWorkspaceUpdate(
                expected_revision=restored.revision, operation={"type": "set_position", "run_id": restored.runs[-1].id,
                    "position": {"view": "document", "finding_id": range_finding.id, "evidence_span_id": passage.span_id}},
            ))
            restored = await ReviewWorkspaceService(documents).read(imported["id"], WORKSPACE)
            assert restored == current
            assert restored.personal[restored.runs[-1].id].position.evidence_span_id == passage.span_id
            assert await ReviewGenerationService(fresh_documents).start(imported["id"], WORKSPACE, initial_request) == current
            provider.assert_awaited_once()
            report["checks"].append("mocked generation claims durably, preserves concurrent brief/personal work and immutable earlier run; replay makes no provider call")
            report["checks"].append("exact multi-line passage endpoints and original quote restore beside legacy single-line evidence; first-anchor resume survives save and reload")

            stage = "processing attempt survives lost request and explicit recovery"
            provider.side_effect = asyncio.CancelledError()
            pending_request = StartReviewRequest(expected_revision=current.revision, request_id="synthetic-interrupted", model_id="gpt-6-sol")
            try:
                await generated_service.start(imported["id"], WORKSPACE, pending_request)
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Synthetic request cancellation was not exercised")
            current = await service.read(imported["id"], WORKSPACE)
            assert current.runs[-1].status == "processing"
            calls_before = provider.await_count
            assert await ReviewGenerationService(fresh_documents).start(imported["id"], WORKSPACE, pending_request) == current
            assert provider.await_count == calls_before
            current = await generated_service.interrupt(imported["id"], WORKSPACE, "synthetic-interrupted", current.revision)
            assert current.runs[-1].status == "interrupted"
            report["checks"].append("processing attempt survives request loss and independent reload; replay never recharges; explicit interrupted recovery persists")

            stage = "scoping and legacy preservation"
            await expect_error(fresh_service.read(imported["id"], "other-workspace"), "DOCUMENT_NOT_FOUND")
            await expect_error(fresh_service.create_fixture(imported["id"], "other-workspace", 0), "DOCUMENT_NOT_FOUND")
            await expect_error(fresh_service.read(legacy["id"], WORKSPACE), "SOURCE_REVISION_REQUIRED")
            assert await db.documents.find_one({"id": legacy["id"]}) == legacy_before
            assert set(await db.list_collection_names()) == {"smoke_owner", "documents", "pdf_files.files", "pdf_files.chunks"}

            stage = "scoped deletion during generation rejects late result"
            # This source was never indexed; make existing optional vector cleanup
            # a deterministic no-op while exercising real file/document deletion.
            cleanup = SimpleNamespace(delete_document_from_rag=AsyncMock(return_value=True))
            stack.enter_context(patch("services.rag_service.get_rag_service", return_value=cleanup))
            async def delete_during_generation(*_):
                assert await fresh_documents.delete_document_for_workspace(imported["id"], WORKSPACE)
                return result
            provider.side_effect = delete_during_generation
            await expect_error(generated_service.start(imported["id"], WORKSPACE, StartReviewRequest(
                expected_revision=current.revision, request_id="synthetic-deleted", model_id="gpt-6-sol",
            )), "DOCUMENT_NOT_FOUND")
            assert await db.documents.find_one({"id": imported["id"]}) is None
            assert await db["pdf_files.files"].count_documents({}) == 0
            await expect_error(fresh_service.read(imported["id"], WORKSPACE), "DOCUMENT_NOT_FOUND")
            assert await db.documents.find_one({"id": legacy["id"]}) == legacy_before
            report["checks"].append("wrong scope rejected, legacy unchanged; deletion during generation removes nested reviews/source and cannot be undone by late output")
            documents.get_workspace_api_key.assert_not_awaited()
            for guard in guards:
                guard.assert_not_called()
            report["passed"] = True
    except Exception as error:
        report["failed_check"] = stage
        report["error_type"] = type(error).__name__
    finally:
        if owned_database:
            try:
                assert database_name == f"clauseiq_review_smoke_{suffix}"
                assert len(suffix) == 32 and all(character in "0123456789abcdef" for character in suffix)
                assert adapter.config.database == database_name
                await adapter.client.drop_database(database_name)
                assert database_name not in await adapter.client.list_database_names()
                report["cleaned"].append("isolated MongoDB/GridFS review fixture database")
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
