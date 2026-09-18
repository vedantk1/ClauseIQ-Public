"""Local browser security boundary: no passwords, no public spend endpoint."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.environments import get_environment_config
from middleware.local_access import local_access_middleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                       allow_methods=["GET", "PUT"], allow_headers=["X-ClauseIQ-Local", "Content-Type"])
    app.middleware("http")(local_access_middleware(["http://localhost:3000"]))

    @app.api_route("/api/v1/workspace", methods=["GET", "PUT"])
    async def workspace():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return TestClient(app, base_url="http://localhost:8000")


@pytest.mark.parametrize("method", ["get", "put"])
def test_marker_is_required_even_without_origin(client, method):
    assert getattr(client, method)("/api/v1/workspace").status_code == 403


@pytest.mark.parametrize("origin", ["https://untrusted.example", "null", "http://localhost:3001", "http://localhost.evil.example:3000"])
def test_other_origins_cannot_read_or_change_workspace(client, origin):
    response = client.put("/api/v1/workspace", headers={"X-ClauseIQ-Local": "1", "Origin": origin})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", ["untrusted.example", "localhost.evil.example", "localhost@evil.example", "localhost/path", "127.0.0.1:bad"])
def test_host_validation_blocks_dns_rebinding(client, host):
    assert client.get("/api/v1/workspace", headers={"X-ClauseIQ-Local": "1", "Host": host}).status_code == 403


def test_local_ui_request_and_native_request_work(client):
    for headers in ({"X-ClauseIQ-Local": "1"}, {"X-ClauseIQ-Local": "1", "Origin": "http://localhost:3000"}):
        response = client.get("/api/v1/workspace", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def test_preflight_and_basic_health(client):
    response = client.options("/api/v1/workspace", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "x-clauseiq-local,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers={"Origin": "https://untrusted.example"}).status_code == 403


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_hosted_environment_is_not_an_account_bypass(monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(RuntimeError, match="local"):
        get_environment_config()


@pytest.mark.parametrize("origins", ["*", "https://external.example", "http://localhost:3000/path"])
def test_remote_cors_configuration_is_rejected(monkeypatch, origins):
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("CORS_ORIGINS", origins)
    with pytest.raises(ValueError, match="loopback"):
        get_environment_config()
