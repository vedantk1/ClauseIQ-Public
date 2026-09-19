"""Retiring Analytics changes routes, not stored reviews or legacy read APIs."""

from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from config.logging import FoundationalLogger


@pytest.fixture
def application(monkeypatch):
    # Inspect the real route registration without replacing pytest logging or
    # entering the lifespan that initializes local storage and cleanup.
    monkeypatch.setattr(FoundationalLogger, "configure", lambda **kwargs: None)
    return import_module("main").app


def test_analytics_is_not_registered(application):
    paths = application.openapi()["paths"]

    assert not any(path.startswith("/api/v1/analytics") for path in paths)
    assert "/api/v1/documents/" in paths
    assert "/api/v1/documents/{document_id}/review-workspace" in paths
    assert "/api/v1/analysis/documents/{document_id}/clauses" in paths
    assert "/api/v1/analysis/documents/{document_id}/interactions" in paths
    assert "/api/v1/reports/documents/{document_id}/pdf" in paths
    assert "/api/v1/chat/{document_id}/history" in paths
    assert paths["/api/v1/analysis/analyze/"]["post"]["deprecated"] is True


def test_retired_analytics_returns_not_found_without_starting_services(application):
    # No context manager: TestClient must not run application startup.
    client = TestClient(application, base_url="http://localhost")

    response = client.get(
        "/api/v1/analytics/dashboard", headers={"X-ClauseIQ-Local": "1"},
    )

    assert response.status_code == 404


def test_retirement_keeps_local_access_boundary(application):
    client = TestClient(application, base_url="http://localhost")

    response = client.get("/api/v1/analytics/dashboard")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_ACCESS_REQUIRED"
