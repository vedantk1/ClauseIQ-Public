"""Blank optional keys must not make local Qdrant clients select TLS."""
from pathlib import Path
import sys

import httpx
import pytest
from qdrant_client import AsyncQdrantClient, QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.environments import EnvironmentConfig, QdrantConfig


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_empty_optional_keys_are_absent_in_both_configuration_paths(value):
    settings = EnvironmentConfig(_env_file=None, qdrant_api_key=value)
    assert settings.qdrant_api_key is None
    assert settings.qdrant.api_key is None
    assert QdrantConfig(api_key=value).api_key is None


@pytest.mark.parametrize("value", ["synthetic-qdrant-key", "  synthetic-qdrant-key  "])
def test_nonblank_keys_are_preserved_exactly(value):
    settings = EnvironmentConfig(_env_file=None, qdrant_api_key=value)
    assert settings.qdrant_api_key == value
    assert settings.qdrant.api_key == value
    assert QdrantConfig(api_key=value).api_key == value


def test_public_environment_example_is_an_unkeyed_local_configuration(monkeypatch):
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    example = Path(__file__).resolve().parents[1] / ".env.example"
    settings = EnvironmentConfig(_env_file=example)
    assert settings.qdrant.api_key is None


@pytest.mark.parametrize("value,scheme", [("", "http"), (" \t", "http"), ("synthetic-qdrant-key", "https")])
@pytest.mark.asyncio
async def test_installed_clients_use_expected_protocol_without_network(value, scheme):
    settings = EnvironmentConfig(_env_file=None, qdrant_api_key=value)
    config = settings.qdrant
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"result": {"collections": []}, "status": "ok", "time": 0})

    options = dict(host="localhost", port=6333, api_key=config.api_key,
                   check_compatibility=False, transport=httpx.MockTransport(respond))
    sync_client = QdrantClient(**options)
    async_client = AsyncQdrantClient(**options)
    try:
        assert sync_client.get_collections().collections == []
        assert (await async_client.get_collections()).collections == []
    finally:
        sync_client.close()
        await async_client.close()

    assert len(requests) == 2
    assert all(request.url.scheme == scheme for request in requests)
    assert all(request.headers.get("api-key") == config.api_key for request in requests)
