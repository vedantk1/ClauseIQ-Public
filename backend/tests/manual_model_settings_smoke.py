"""Opt-in isolated MongoDB model/effort settings smoke; no provider requests.

Run from backend: venv/bin/python tests/manual_model_settings_smoke.py --run-isolated-live
Only a verified-absent, randomly named localhost database is written and removed.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.interface import ConnectionConfig, DatabaseBackend
from database.mongodb_adapter import MongoDBAdapter
from database.service import DocumentService
from services.workspace_service import WorkspaceService
from services.ai.generation import AIRequestError


async def run_smoke():
    database_name = f"clauseiq_model_settings_smoke_{uuid4().hex}"
    adapter = MongoDBAdapter(ConnectionConfig(
        backend=DatabaseBackend.MONGODB, uri="mongodb://127.0.0.1:27017",
        database=database_name, min_pool_size=0, server_selection_timeout_ms=5000,
    ))
    owned = False
    report = {"passed": False, "cleaned": False}
    try:
        await adapter.connect()
        assert database_name not in await adapter.client.list_database_names()
        owned = True
        db = adapter.database
        await db.system_config.insert_one({"key": "system_ai_model", "model_id": "gpt-5.6-terra"})
        await db.system_config.insert_one({"key": "query_gate_model", "model_id": "gpt-5.6-luna"})
        await db.workspace_credentials.insert_one({"id": "local", "legacy_import_pending": False})
        await db.documents.insert_one({"id": "synthetic-history", "workspace_id": "local",
            "review_workspace": {"runs": [{"generation": {"model_id": "gpt-5.6-terra", "reasoning_effort": "medium"}}],
                                 "personal": {"saved_question": "Synthetic retained question"}}})
        history = deepcopy(await db.documents.find_one({"id": "synthetic-history"}))
        credential_state = deepcopy(await db.workspace_credentials.find_one({"id": "local"}))
        old_settings = deepcopy(await db.system_config.find_one({"key": "system_ai_model"}))
        documents = DocumentService()
        documents._db = adapter
        service = WorkspaceService()
        with patch("services.workspace_service.get_document_service", return_value=documents), \
             patch("database.factory.DatabaseFactory.get_database", new=AsyncMock(return_value=adapter)):
            current = await service.get_settings()
            assert (current["model_id"], current["reasoning_effort"]) == ("gpt-6-sol", "medium")
            assert current["query_gate_model_id"] == "gpt-6-sol"
            assert await db.system_config.find_one({"key": "system_ai_model"}) == old_settings
            saved = await service.update_settings({"model_id": "gpt-6-astra", "reasoning_effort": "max"})
            assert (saved["model_id"], saved["reasoning_effort"]) == ("gpt-6-astra", "max")
            try:
                await service.update_settings({"reasoning_effort": "none", "retention_days": 1})
            except AIRequestError:
                pass
            else:
                raise AssertionError("Invalid Astra/none accepted")
            assert (await service.get_settings())["reasoning_effort"] == "max"
            assert await db.system_config.find_one({"key": "document_auto_delete"}) is None
        await adapter.disconnect()
        await adapter.connect()
        fresh = DocumentService()
        fresh._db = adapter
        assert await fresh.get_workspace_generation_settings("local") == {"model_id": "gpt-6-astra", "reasoning_effort": "max"}
        assert await adapter.database.documents.find_one({"id": "synthetic-history"}) == history
        assert await adapter.database.workspace_credentials.find_one({"id": "local"}) == credential_state
        report["passed"] = True
    finally:
        if owned:
            await adapter.client.drop_database(database_name)
            report["cleaned"] = database_name not in await adapter.client.list_database_names()
        await adapter.disconnect()
        if owned and not report["cleaned"]:
            report["leftover_database"] = database_name
        print(json.dumps(report))
    assert report["passed"] and report["cleaned"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated-live", action="store_true")
    if not parser.parse_args().run_isolated_live:
        parser.error("Pass --run-isolated-live to create and remove disposable localhost data.")
    asyncio.run(run_smoke())
