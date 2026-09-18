"""Opt-in, isolated MongoDB/GridFS source-preservation smoke.

Run from backend: venv/bin/python tests/manual_source_smoke.py --run-isolated-live
Uses only the existing localhost MongoDB service and reviewed synthetic PDFs.
No application database, settings, credentials, Qdrant or OpenAI requests are
used. Cleanup removes only the exact verified-absent UUID database created by
this run; any remaining fixture is identified in the final report.
"""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from clauseiq_types.source import SourceExtraction
from database.interface import ConnectionConfig, DatabaseBackend
from database.mongodb_adapter import MongoDBAdapter
from database.service import DocumentService
from services.ai.text_extractor import TextExtractor
from services.file_storage_service import GridFSFileStorage
from services.source_service import SourceError, SourceService


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs"
WORKSPACE = "synthetic-source-workspace"


def isolated_adapter(database_name):
    return MongoDBAdapter(ConnectionConfig(
        backend=DatabaseBackend.MONGODB,
        uri="mongodb://127.0.0.1:27017",
        database=database_name,
        min_pool_size=0,
        server_selection_timeout_ms=5000,
    ))


def document_service(adapter):
    service = DocumentService()
    service._db = adapter
    return service


def check_source(document, content):
    assert document["source_status"] == "stored"
    assert document["extraction_status"] == "complete"
    assert document["analysis_status"] == "not_started"
    assert document["has_pdf_file"] is True
    digest = hashlib.sha256(content).hexdigest()
    assert document["source_sha256"] == digest
    source = SourceExtraction.model_validate(document["source_extraction"])
    assert source.content_sha256 == digest
    assert source.page_count == 25 and source.status == "complete"
    assert document["text"] == source.text
    assert [page.page_number for page in source.pages] == list(range(1, 26))
    for page in source.pages:
        assert page.status == "extracted" and page.spans
        for span in page.spans:
            assert page.text[span.start:span.end] == span.text
    return source


async def expect_source_error(operation, code):
    try:
        await operation
    except SourceError as error:
        assert error.code == code
    else:
        raise AssertionError("Expected source operation to be rejected")


async def run_smoke():
    suffix = uuid4().hex
    database_name = f"clauseiq_source_smoke_{suffix}"
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
        await db.smoke_owner.insert_one({"id": suffix, "purpose": "source-preservation-smoke"})

        content = (FIXTURE_DIR / "managed-services-25p.pdf").read_bytes()
        legacy_id = str(uuid4())
        legacy = {
            "id": legacy_id, "workspace_id": WORKSPACE,
            "filename": "synthetic-legacy.pdf", "text": "Unrelated synthetic legacy record",
            "clauses": [{"id": "synthetic-clause", "text": "Preserve this synthetic clause"}],
            "user_interactions": {"synthetic-clause": {"notes": ["Preserve this synthetic note"]}},
            "has_pdf_file": False,
        }
        await db.documents.insert_one(deepcopy(legacy))
        legacy_before = await db.documents.find_one({"id": legacy_id})

        with ExitStack() as stack:
            # Fail closed if this local-only workflow ever starts external clients.
            provider_guards = [stack.enter_context(patch(target, side_effect=AssertionError(
                "External provider access is forbidden in the source smoke"
            ))) for target in (
                "openai.AsyncOpenAI", "openai.OpenAI",
                "qdrant_client.AsyncQdrantClient", "qdrant_client.QdrantClient",
                "services.ai.client_manager.get_openai_client",
            )]
            factory = stack.enter_context(patch(
                "database.factory.DatabaseFactory.get_database", new=AsyncMock(return_value=adapter),
            ))
            storage = GridFSFileStorage()
            assert await storage.initialize()
            storage_factory = stack.enter_context(patch(
                "services.file_storage_service.get_file_storage_service", return_value=storage,
            ))
            documents = document_service(adapter)
            sources = SourceService(documents, TextExtractor())

            stage = "import original and page-aware extraction"
            imported = await sources.import_pdf(content, "managed-services-25p.pdf", WORKSPACE)
            source_model = check_source(imported, content)
            original = await documents.get_pdf_file(imported["id"], WORKSPACE)
            assert original["content"] == content
            assert original["metadata"]["checksum"] == imported["source_sha256"]
            assert await db.documents.count_documents({}) == 2
            assert await db["pdf_files.files"].count_documents({}) == 1
            assert await db["pdf_files.chunks"].count_documents({}) >= 1
            report["checks"].append("25-page original bytes, SHA-256 and exact page spans persisted")

            stage = "reload through fresh services and connection"
            fresh_adapter = isolated_adapter(database_name)
            connections.append(fresh_adapter)
            await fresh_adapter.connect()
            factory.return_value = fresh_adapter
            fresh_storage = GridFSFileStorage()
            assert await fresh_storage.initialize()
            storage_factory.return_value = fresh_storage
            fresh_documents = document_service(fresh_adapter)
            reloaded = await fresh_documents.get_document_for_workspace(imported["id"], WORKSPACE)
            assert reloaded == imported
            check_source(reloaded, content)
            assert (await fresh_documents.get_pdf_file(imported["id"], WORKSPACE))["content"] == content
            report["checks"].append("source and PDF survive fresh service instances and a fresh database connection")

            stage = "cached retry and workspace denial"
            unexpected = SimpleNamespace(extract_source=AsyncMock(side_effect=AssertionError(
                "Published extraction must not run again"
            )))
            cached = await SourceService(fresh_documents, unexpected).extract(
                imported["id"], WORKSPACE, restart=True,
            )
            assert cached == imported
            unexpected.extract_source.assert_not_awaited()
            assert await db.documents.count_documents({}) == 2
            assert await db["pdf_files.files"].count_documents({}) == 1
            wrong_workspace = "another-synthetic-workspace"
            assert await fresh_documents.get_document_for_workspace(imported["id"], wrong_workspace) is None
            assert await fresh_documents.get_pdf_file(imported["id"], wrong_workspace) is None
            assert await fresh_storage.get_file(imported["pdf_file_id"], wrong_workspace) is None
            await expect_source_error(
                SourceService(fresh_documents).extract(imported["id"], wrong_workspace),
                "DOCUMENT_NOT_FOUND",
            )
            assert not await fresh_documents.update_document_if(
                imported["id"], wrong_workspace, {"workspace_id": WORKSPACE}, {"text": "must not write"},
            )
            assert not await fresh_documents.update_document_if(
                str(uuid4()), WORKSPACE, {}, {"text": "must not create"},
            )
            assert await fresh_documents.get_document_for_workspace(imported["id"], WORKSPACE) == imported
            report["checks"].append("cached retry retains identity and counts; wrong-scope reads/writes and missing-record upsert denied")

            stage = "failed extraction and same-original retry"
            failing = SimpleNamespace(extract_source=AsyncMock(side_effect=ValueError("synthetic forced failure")))
            failed = await SourceService(fresh_documents, failing).import_pdf(
                content, "managed-services-25p.pdf", WORKSPACE,
            )
            assert failed["source_status"] == "stored"
            assert failed["extraction_status"] == "failed"
            assert failed["extraction_error"] == "PDF_EXTRACTION_FAILED"
            assert failed["analysis_status"] == "not_started"
            assert (await fresh_documents.get_pdf_file(failed["id"], WORKSPACE))["content"] == content
            retried = await SourceService(fresh_documents, TextExtractor()).extract(failed["id"], WORKSPACE)
            check_source(retried, content)
            for field in ("id", "source_revision_id", "source_sha256", "pdf_file_id"):
                assert retried[field] == failed[field]
            assert await db.documents.count_documents({}) == 3
            assert await db["pdf_files.files"].count_documents({}) == 2
            report["checks"].append("failed extraction retains the original; retry succeeds without new document, revision or PDF")

            stage = "real duplicate claim and stale extraction fencing"
            started = asyncio.Event()
            release = asyncio.Event()

            async def paused_extract(file_content, filename):
                assert file_content == content and filename == "managed-services-25p.pdf"
                started.set()
                await release.wait()
                return source_model

            paused = SourceService(fresh_documents, SimpleNamespace(extract_source=paused_extract))
            in_flight = asyncio.create_task(paused.import_pdf(content, "managed-services-25p.pdf", WORKSPACE))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                processing = await db.documents.find_one({"extraction_status": "processing"})
                assert processing is not None
                in_flight_id = processing["id"]
                fresh_sources = SourceService(fresh_documents, TextExtractor())
                await expect_source_error(
                    fresh_sources.extract(in_flight_id, WORKSPACE), "EXTRACTION_IN_PROGRESS",
                )
                winner = await fresh_sources.extract(in_flight_id, WORKSPACE, restart=True)
                check_source(winner, content)
                assert winner["extraction_attempt_id"] != processing["extraction_attempt_id"]
                release.set()
                await expect_source_error(asyncio.wait_for(in_flight, timeout=10), "EXTRACTION_CONFLICT")
                assert await fresh_documents.get_document_for_workspace(in_flight_id, WORKSPACE) == winner
                assert await db.documents.count_documents({}) == 4
                assert await db["pdf_files.files"].count_documents({}) == 3
            finally:
                release.set()
                if not in_flight.done():
                    in_flight.cancel()
                await asyncio.gather(in_flight, return_exceptions=True)
            report["checks"].append("real MongoDB claims reject duplicate work and prevent a superseded extraction overwriting its replacement")

            stage = "unrelated record and external-access guards"
            assert await db.documents.find_one({"id": legacy_id}) == legacy_before
            assert set(await db.list_collection_names()) == {
                "smoke_owner", "documents", "pdf_files.files", "pdf_files.chunks",
            }
            for guard in provider_guards:
                guard.assert_not_called()
            report["checks"].append("unrelated synthetic legacy data unchanged; no AI or vector clients requested")
            report["passed"] = True
    except Exception as error:
        report["failed_check"] = stage
        report["error_type"] = type(error).__name__
    finally:
        if owned_database:
            try:
                assert database_name == f"clauseiq_source_smoke_{suffix}"
                assert len(suffix) == 32 and all(character in "0123456789abcdef" for character in suffix)
                assert adapter.config.database == database_name
                await adapter.client.drop_database(database_name)
                assert database_name not in await adapter.client.list_database_names()
                report["cleaned"].append("isolated MongoDB/GridFS fixture database")
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
