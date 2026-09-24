"""Model/effort settings persistence and validation without provider access."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.service import DocumentService
from routers import workspace
from services import workspace_service
from services.ai.generation import AIRequestError


@pytest.fixture
def settings_service(monkeypatch):
    records = {}
    documents = DocumentService()

    async def read(key, **_):
        return deepcopy(records.get(key))

    async def save(key, value, *_):
        records[key] = deepcopy(value)
        return True

    documents.get_system_config = AsyncMock(side_effect=read)
    documents.set_system_config = AsyncMock(side_effect=save)
    service = workspace_service.WorkspaceService()
    service._credentials = AsyncMock(return_value=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    service.has_api_key = AsyncMock(return_value=False)
    monkeypatch.setattr(workspace_service, "get_document_service", lambda: documents)
    return service, documents, records


@pytest.mark.asyncio
async def test_settings_save_model_and_effort_in_one_record_and_return_them(settings_service):
    service, documents, records = settings_service
    result = await service.update_settings({"model_id": "gpt-6-astra", "reasoning_effort": "max"})
    assert result["model_id"] == "gpt-6-astra" and result["reasoning_effort"] == "max"
    documents.set_system_config.assert_awaited_once()
    assert records["system_ai_model"]["reasoning_effort"] == "max"
    assert result["query_gate_model_id"] == "gpt-6-sol"
    assert [model["id"] for model in result["available_models"]] == ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"]


@pytest.mark.asyncio
async def test_partial_updates_preserve_the_other_ai_choice(settings_service):
    service, _, _ = settings_service
    await service.update_settings({"model_id": "gpt-6-luna", "reasoning_effort": "high"})
    assert (await service.update_settings({"reasoning_effort": "max"}))["model_id"] == "gpt-6-luna"
    assert (await service.update_settings({"model_id": "gpt-6-astra"}))["reasoning_effort"] == "max"
    assert (await service.update_settings({"toast_notifications_enabled": False}))["reasoning_effort"] == "max"


@pytest.mark.asyncio
async def test_invalid_pair_has_no_partial_writes_including_retention(settings_service):
    service, documents, records = settings_service
    await service.update_settings({"model_id": "gpt-6-luna", "reasoning_effort": "none"})
    before = deepcopy(records)
    documents.set_system_config.reset_mock()
    with pytest.raises(AIRequestError):
        await service.update_settings({"model_id": "gpt-6-astra", "retention_days": 1})
    assert records == before
    documents.set_system_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_selection_and_missing_effort_resolve_without_writes(settings_service):
    service, documents, records = settings_service
    records["system_ai_model"] = {"model_id": "gpt-5.6-terra", "reasoning_effort": "high"}
    before = deepcopy(records)
    result = await service.get_settings()
    assert (result["model_id"], result["reasoning_effort"]) == ("gpt-6-sol", "medium")
    assert records == before
    documents.set_system_config.assert_not_awaited()
    records["system_ai_model"] = {"model_id": "gpt-6-luna"}
    assert (await service.get_settings())["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_failed_settings_write_cannot_report_success(settings_service):
    service, documents, records = settings_service
    documents.set_system_config.side_effect = None
    documents.set_system_config.return_value = False
    with pytest.raises(RuntimeError, match="Could not save"):
        await service.update_settings({"model_id": "gpt-6-sol", "reasoning_effort": "high"})
    assert records == {}


def test_settings_api_rejects_invalid_effort_and_astra_none_without_changes(settings_service):
    service, documents, records = settings_service
    app = FastAPI()
    app.include_router(workspace.router)
    app.dependency_overrides[workspace.get_workspace_service] = lambda: service
    client = TestClient(app)
    for body in [{"reasoning_effort": "minimal"}, {"model_id": "gpt-6-astra", "reasoning_effort": "none"}]:
        assert client.put("/workspace/settings", json=body).status_code == 422
    assert records == {}
    documents.set_system_config.assert_not_awaited()
    result = client.put("/workspace/settings", json={"model_id": "gpt-6-sol", "reasoning_effort": "xhigh"})
    assert result.status_code == 200
    assert result.json()["data"]["reasoning_effort"] == "xhigh"
