"""Credential persistence, restart, migration and response privacy without AI calls."""
import base64
import copy
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.encryption_service import EncryptionService, decrypt_legacy_api_key
from services import workspace_service
from routers import workspace
from middleware.api_standardization import add_api_standardization


class Collection:
    def __init__(self, record=None):
        self.record = record

    async def find_one(self, query):
        return copy.deepcopy(self.record)

    async def update_one(self, query, update, **kwargs):
        self.record = {**(self.record or {}), **query, **update.get("$set", {})}
        for field in update.get("$unset", {}):
            self.record.pop(field, None)


@pytest.fixture
def credential_service(monkeypatch, tmp_path):
    encryption = EncryptionService(tmp_path / "private-state")
    monkeypatch.setattr(workspace_service, "get_encryption_service", lambda: encryption)
    collection = Collection()
    service = workspace_service.WorkspaceService()
    monkeypatch.setattr(service, "_credentials", AsyncMock(return_value=collection))
    return service, collection, encryption


def test_key_file_is_private_and_survives_restart(tmp_path):
    service = EncryptionService(tmp_path)
    ciphertext = service.encrypt("test-credential-not-real")
    assert "test-credential-not-real" not in ciphertext
    assert EncryptionService(tmp_path).decrypt(ciphertext) == "test-credential-not-real"
    if os.name == "posix":
        assert service.key_path.stat().st_mode & 0o777 == 0o600


def test_missing_state_does_not_generate_key_on_read(tmp_path):
    service = EncryptionService(tmp_path)
    with pytest.raises(ValueError, match="Restore"):
        service.decrypt(Fernet(Fernet.generate_key()).encrypt(b"test").decode())
    assert not service.key_path.exists()


def test_key_file_symlinks_are_not_followed(tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(Fernet.generate_key())
    service = EncryptionService(tmp_path / "state")
    service.key_path.parent.mkdir()
    service.key_path.symlink_to(original)
    with pytest.raises(ValueError):
        service.encrypt("test")


@pytest.mark.asyncio
async def test_api_key_roundtrip_never_stores_plaintext(credential_service):
    service, collection, encryption = credential_service
    await service.set_api_key("sk-test-fixture-not-a-real-key")
    assert "sk-test-fixture-not-a-real-key" not in repr(collection.record)
    assert await service.get_api_key() == "sk-test-fixture-not-a-real-key"
    await service.delete_api_key()
    assert not await service.has_api_key()
    assert "encrypted_key" not in collection.record
    assert collection.record["legacy_import_pending"] is False


@pytest.mark.asyncio
async def test_failed_decryption_is_recoverable_by_explicit_key_reentry(credential_service, monkeypatch, tmp_path):
    service, collection, encryption = credential_service
    await service.set_api_key("sk-test-fixture-not-a-real-key")
    replacement = EncryptionService(tmp_path / "new-state")
    monkeypatch.setattr(workspace_service, "get_encryption_service", lambda: replacement)
    assert await service.get_api_key() is None
    assert not replacement.key_path.exists()
    await service.set_api_key("sk-test-replacement-not-a-real-key")
    assert await service.get_api_key() == "sk-test-replacement-not-a-real-key"


@pytest.mark.asyncio
async def test_removed_credential_is_not_reimported(credential_service, monkeypatch):
    service, collection, _ = credential_service
    await service.delete_api_key()
    db = AsyncMock(side_effect=AssertionError("Do not read legacy accounts after deletion"))
    monkeypatch.setattr(workspace_service.DatabaseFactory, "get_database", db)
    await service.initialize_credentials("old-owner")
    db.assert_not_called()


def test_old_encryption_can_be_read_only_for_migration(monkeypatch):
    secret = "fixture-legacy-encryption-secret-not-real"
    monkeypatch.setenv("API_KEY_ENCRYPTION_SECRET", secret)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                    salt=b"clauseiq_api_key_salt_v1", iterations=100000)
    cipher = Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode()))).encrypt(b"fixture-key").decode()
    assert decrypt_legacy_api_key(cipher) == "fixture-key"


def test_key_and_validation_responses_never_echo_credentials(credential_service):
    service, collection, _ = credential_service
    app = FastAPI()
    add_api_standardization(app)
    app.include_router(workspace.router)
    app.dependency_overrides[workspace.get_workspace_service] = lambda: service
    client = TestClient(app)
    key = "sk-test-fixture-not-a-real-key"
    response = client.put("/workspace/api-key", json={"api_key": key})
    assert response.status_code == 200
    assert response.json()["data"] == {"has_api_key": True}
    assert key not in response.text
    assert collection.record["encrypted_key"] not in response.text
    response = client.put("/workspace/api-key", json={"api_key": key, "unexpected": key})
    assert response.status_code == 422
    assert key not in response.text
    response = client.put("/workspace/api-key", json={"api_key": "invalid-secret-value"})
    assert response.status_code == 400
    assert "invalid-secret-value" not in response.text
    response = client.delete("/workspace/api-key")
    assert response.json()["data"] == {"has_api_key": False}


@pytest.mark.asyncio
async def test_request_clients_close_and_restore_nested_context(monkeypatch):
    from services.ai import client_manager
    import openai
    clients = []

    def factory(**kwargs):
        client = AsyncMock()
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    client_manager.reset_client()
    with pytest.raises(RuntimeError):
        async with client_manager.workspace_openai_client("sk-test-first") as first:
            async with client_manager.workspace_openai_client("sk-test-second"):
                assert client_manager.get_openai_client() is clients[1]
            assert client_manager.get_openai_client() is first
            raise RuntimeError("fixture failure")
    assert client_manager.get_openai_client() is None
    for client in clients:
        client.close.assert_awaited_once()
