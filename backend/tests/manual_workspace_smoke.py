"""Opt-in isolated MongoDB/Qdrant migration and deletion smoke.

Run from backend: venv/bin/python tests/manual_workspace_smoke.py --run-isolated-live
Only localhost is used. No .env changes, application-library access, OpenAI
requests, or real credentials are required. Exact UUID-owned fixtures are
removed in finally; any cleanup failure is reported with its fixture name.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from database.interface import ConnectionConfig, DatabaseBackend
from database.mongodb_adapter import MongoDBAdapter
from database.service import DocumentService
from database.workspace_migration import initialize_workspace
from services.file_storage_service import GridFSFileStorage
from services.qdrant_vector_service import QdrantVectorService
from services.rag_service import RAGService


class IsolatedVectors:
    """Restrict every migration/service operation to the owned test collection."""
    def __init__(self, client, name):
        self.client = client
        self.name = name

    async def get_collections(self):
        collections = await self.client.get_collections()
        return SimpleNamespace(collections=[item for item in collections.collections if item.name == self.name])

    def __getattr__(self, operation):
        if operation not in {"scroll", "set_payload", "create_payload_index", "delete", "count"}:
            raise AttributeError(operation)

        async def scoped(**kwargs):
            assert kwargs.get("collection_name") == self.name, "Smoke attempted an out-of-scope vector operation"
            return await getattr(self.client, operation)(**kwargs)
        return scoped


async def run_smoke():
    suffix = uuid4().hex
    database_name = f"clauseiq_workspace_smoke_{suffix}"
    collection_name = f"clauseiq_workspace_smoke_{suffix}"
    adapter = MongoDBAdapter(ConnectionConfig(
        backend=DatabaseBackend.MONGODB,
        uri="mongodb://127.0.0.1:27017",
        database=database_name,
        min_pool_size=0,
        server_selection_timeout_ms=5000,
    ))
    vectors = AsyncQdrantClient(host="127.0.0.1", port=6333, timeout=10)
    owned_database = False
    owned_collection = False
    report = {"passed": False, "checks": [], "cleaned": [], "leftovers": []}
    try:
        await adapter.connect()
        assert database_name not in await adapter.client.list_database_names()
        assert collection_name not in {item.name for item in (await vectors.get_collections()).collections}
        owned_database = True
        # Only the exact verified-absent fixture names are used after this point.
        owned_collection = True
        await vectors.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
        )
        scoped_vectors = IsolatedVectors(vectors, collection_name)
        db = adapter.database
        bucket = AsyncIOMotorGridFSBucket(db, bucket_name="pdf_files")
        owner = "synthetic-legacy-owner"
        first_document = str(uuid4())
        other_document = str(uuid4())
        clause_id = str(uuid4())
        note_id = str(uuid4())
        synthetic_pdf = b"%PDF-1.4\n% Synthetic workspace storage fixture\n%%EOF"
        file_ids = []
        for doc_id in (first_document, first_document, other_document):
            file_ids.append(await bucket.upload_from_stream(
                "synthetic.pdf", synthetic_pdf,
                metadata={"user_id": owner, "document_id": doc_id, "content_type": "application/pdf"},
            ))
        session = {"id": str(uuid4()), "user_id": owner, "document_id": first_document,
                   "messages": [{"id": str(uuid4()), "role": "user", "content": "Synthetic review question"}]}
        original_documents = [
            {"id": first_document, "user_id": owner, "filename": "synthetic.pdf", "text": "Synthetic agreement",
             "pdf_file_id": str(file_ids[0]), "has_pdf_file": True,
             "clauses": [{"id": clause_id, "text": "Synthetic clause"}], "chat_session": session},
            {"id": other_document, "user_id": owner, "filename": "retained.pdf", "text": "Unrelated synthetic agreement",
             "pdf_file_id": str(file_ids[2]), "has_pdf_file": True},
        ]
        await db.users.insert_one({"id": owner})
        await db.documents.insert_many(deepcopy(original_documents))
        await db.user_interactions.insert_one({
            "document_id": first_document, "user_id": owner,
            "interactions": {clause_id: {"clause_id": clause_id, "user_id": owner,
                                         "notes": [{"id": note_id, "text": "Synthetic note"}]}},
        })
        await db.system_config.insert_one({"key": "document_auto_delete", "enabled": True, "days": 30})
        point_ids = [str(uuid4()) for _ in range(3)]
        payloads = [
            {"user_id": owner, "document_id": doc_id, "text": "Synthetic chunk", "chunk_index": index}
            for index, doc_id in enumerate((first_document, first_document, other_document))
        ]
        await vectors.upsert(collection_name=collection_name, points=[
            PointStruct(id=point_id, vector=[1.0] + [0.0] * 3071, payload=payload)
            for point_id, payload in zip(point_ids, payloads)
        ], wait=True)

        config = SimpleNamespace(qdrant=SimpleNamespace(collection_name=collection_name))
        with patch("database.workspace_migration.get_environment_config", return_value=config):
            first = await initialize_workspace(adapter, scoped_vectors)
            second = await initialize_workspace(adapter, scoped_vectors)
        assert first["migrated"] is True and second["migrated"] is False
        assert first["legacy_user_id"] == owner
        report["checks"].append("legacy migration and second-run idempotence")

        service = DocumentService()
        service._db = adapter
        migrated = await service.get_document_for_workspace(first_document, "local")
        assert migrated["id"] == first_document and migrated["user_id"] == owner
        assert migrated["text"] == original_documents[0]["text"]
        assert migrated["pdf_file_id"] == str(file_ids[0])
        assert migrated["clauses"][0]["id"] == clause_id
        assert migrated["chat_session"]["messages"] == session["messages"]
        assert migrated["chat_session"]["workspace_id"] == "local"
        notes = await service.get_user_interactions(first_document, "local")
        assert notes[clause_id]["notes"][0]["id"] == note_id
        assert await service.get_document_for_workspace(first_document, "another-workspace") is None
        assert await service.get_user_interactions(first_document, "another-workspace") is None
        assert (await service.get_auto_delete_config())["enabled"] is False
        stored_points = await vectors.retrieve(collection_name=collection_name, ids=point_ids, with_payload=True)
        for point in stored_points:
            assert point.payload["workspace_id"] == "local" and point.payload["user_id"] == owner
        report["checks"].append("preserved document, PDF, clause, note, chat and vector identities with scoped reads")

        storage = GridFSFileStorage()
        with patch("database.factory.DatabaseFactory.get_database", new=AsyncMock(return_value=adapter)):
            assert await storage.initialize()
        stored_file = await storage.get_file(str(file_ids[0]), "local")
        assert stored_file["content"] == synthetic_pdf
        assert await storage.get_file(str(file_ids[0]), "another-workspace") is None
        vector_service = QdrantVectorService()
        vector_service.collection_name = collection_name
        vector_service.async_client = scoped_vectors
        vector_service._initialized = True
        rag = RAGService()
        rag._vector_service = vector_service
        with patch("services.file_storage_service.get_file_storage_service", return_value=storage), \
             patch("services.rag_service.get_rag_service", return_value=rag):
            assert await service.delete_document_for_workspace(first_document, "local")
        assert await db.documents.count_documents({"id": first_document}) == 0
        assert await db.user_interactions.count_documents({"document_id": first_document}) == 0
        assert await db["pdf_files.files"].count_documents({"metadata.document_id": first_document}) == 0
        assert await db["pdf_files.chunks"].count_documents({"files_id": {"$in": file_ids[:2]}}) == 0
        assert await vector_service.get_document_chunk_count(first_document, "local") == 0
        report["checks"].append("actual service cascade removed target document, notes, chat, both PDFs, GridFS chunks and vectors")

        retained = await service.get_document_for_workspace(other_document, "local")
        assert retained["text"] == original_documents[1]["text"]
        assert (await storage.get_file(str(file_ids[2]), "local"))["content"] == synthetic_pdf
        assert await vector_service.get_document_chunk_count(other_document, "local") == 1
        report["checks"].append("unrelated document, PDF and vector remained intact")
        report["passed"] = True
    finally:
        if owned_collection:
            try:
                assert collection_name == f"clauseiq_workspace_smoke_{suffix}"
                await vectors.delete_collection(collection_name)
                assert collection_name not in {item.name for item in (await vectors.get_collections()).collections}
                report["cleaned"].append("isolated Qdrant fixture collection")
            except Exception:
                report["leftovers"].append({"qdrant_collection": collection_name})
        if owned_database:
            try:
                assert database_name == f"clauseiq_workspace_smoke_{suffix}"
                await adapter.client.drop_database(database_name)
                assert database_name not in await adapter.client.list_database_names()
                report["cleaned"].append("isolated MongoDB fixture database")
            except Exception:
                report["leftovers"].append({"mongodb_database": database_name})
        await vectors.close()
        await adapter.disconnect()
        print(json.dumps(report, indent=2))
    assert not report["leftovers"], "Isolated smoke cleanup requires attention"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-live", action="store_true", help="Explicitly permit disposable localhost fixtures")
    args = parser.parse_args()
    if not args.run_isolated_live:
        parser.error("Pass --run-isolated-live to create and remove disposable localhost fixtures.")
    asyncio.run(run_smoke())
