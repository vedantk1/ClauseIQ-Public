"""Source recovery references survive the app's real error standardization."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from middleware.api_standardization import add_api_standardization


@pytest.mark.parametrize("status", [409, 422, 502, 503])
def test_saved_document_reference_survives_standardization(status):
    app = add_api_standardization(FastAPI())

    @app.get("/synthetic-failure")
    async def fail():
        raise HTTPException(status, "The review could not be completed.",
                            headers={"X-Document-ID": "synthetic-document"})

    response = TestClient(app).get("/synthetic-failure")
    assert response.status_code == status
    assert response.headers["X-Document-ID"] == "synthetic-document"
    assert response.json()["error"]["details"] == {"document_id": "synthetic-document"}
    assert response.json()["error"]["message"] == "The review could not be completed."
    assert response.headers["X-Correlation-ID"] == response.json()["correlation_id"]


def test_unrelated_errors_do_not_fabricate_document_references():
    app = add_api_standardization(FastAPI())

    @app.get("/synthetic-failure")
    async def fail():
        raise HTTPException(404, "Document not found")

    response = TestClient(app).get("/synthetic-failure")
    assert "X-Document-ID" not in response.headers
    assert response.json()["error"]["details"] is None
