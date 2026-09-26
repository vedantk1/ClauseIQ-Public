"""One safe HTTP identity across middleware, errors and diagnostic records."""

import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from config.logging import RequestContextFilter
from middleware.api_standardization import (
    add_api_standardization,
    create_error_response,
    create_success_response,
)
from middleware.logging import logging_middleware, structured_logger
from middleware.request_context import current_request_id, request_context
from utils.ai_debug_helper import AIDebugLogger, DebugLevel


def _app(standardize=True, log_requests=True):
    app = FastAPI()
    if standardize:
        add_api_standardization(app)
    if log_requests:
        app.middleware("http")(logging_middleware)

    @app.get("/success")
    async def success(request: Request):
        return create_success_response({
            "request_id": request.state.request_id,
            "correlation_id": request.state.correlation_id,
            "context_id": current_request_id(),
        })

    @app.get("/handled")
    async def handled():
        raise HTTPException(409, "Synthetic conflict")

    @app.get("/custom")
    async def custom():
        return JSONResponse(status_code=409, content=create_error_response(
            "SYNTHETIC_CONFLICT", "Synthetic conflict",
        ).model_dump())

    @app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")

    @app.get("/validation")
    async def validation(count: int):
        return {"count": count}

    return app


@pytest.mark.parametrize("route,status", [
    ("success", 200), ("handled", 409), ("custom", 409),
    ("unexpected", 500), ("validation?count=invalid", 422),
])
def test_same_server_id_in_headers_response_helpers_and_lifecycle_logs(route, status):
    with patch.object(structured_logger.logger, "info") as info:
        response = TestClient(_app()).get(f"/{route}", headers={
            "X-Request-ID": "caller-controlled-value",
            "X-Correlation-ID": "caller-controlled-value",
        })

    assert response.status_code == status
    identity = response.headers["X-Request-ID"]
    assert str(UUID(identity)) == identity
    assert identity == response.headers["X-Correlation-ID"]
    assert response.json()["correlation_id"] == identity
    assert "PRIVATE_EXCEPTION_SENTINEL" not in response.text
    if route == "success":
        assert set(response.json()["data"].values()) == {identity}
    records = [json.loads(call.args[0]) for call in info.call_args_list]
    assert [record["event"] for record in records] == ["request_start", "request_complete"]
    assert {record["request_id"] for record in records} == {identity}
    assert current_request_id() is None


def test_standardization_and_logging_have_safe_standalone_fallbacks():
    for standardize, log_requests in ((True, False), (False, True)):
        response = TestClient(_app(standardize, log_requests)).get("/unexpected")
        assert response.status_code == 500
        assert response.json()["success"] is False
        assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert response.json()["correlation_id"] == response.headers["X-Request-ID"]
        assert response.headers["X-Correlation-ID"] == response.headers["X-Request-ID"]
        assert "PRIVATE_EXCEPTION_SENTINEL" not in response.text


def test_rate_limit_response_outside_standardization_uses_same_identity(monkeypatch):
    from middleware.rate_limiter import rate_limit_middleware, rate_limiter
    from middleware.security import security_monitor

    app = _app(log_requests=False)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(logging_middleware)
    monkeypatch.setattr(rate_limiter, "is_allowed", lambda *args: (False, {"reset_time": 0}))
    monkeypatch.setattr(security_monitor, "record_suspicious_activity", lambda *args: None)
    response = TestClient(app).get("/success")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["correlation_id"] == response.headers["X-Request-ID"]
    assert response.headers["X-Correlation-ID"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_concurrent_requests_and_worker_threads_keep_distinct_contexts():
    app = _app()

    @app.get("/concurrent")
    async def concurrent():
        before = current_request_id()
        await asyncio.sleep(0)
        return create_success_response({"before": before, "after": current_request_id()})

    @app.get("/sync")
    def synchronous_endpoint():
        return create_success_response({"thread_id": current_request_id()})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*[
            client.get(route) for route in ("/concurrent", "/sync", "/concurrent")
        ])
    identities = set()
    for response in responses:
        identity = response.headers["X-Request-ID"]
        identities.add(identity)
        assert set(response.json()["data"].values()) == {identity}
    assert len(identities) == 3
    assert current_request_id() is None


def test_diagnostic_and_formatted_logs_use_context_not_paid_attempt_or_user_ids():
    request = StarletteRequest({"type": "http", "headers": []})
    debug = AIDebugLogger()
    record = logging.makeLogRecord({"msg": "Safe event", "http_request_id": "caller-supplied"})
    with request_context(request) as identity:
        RequestContextFilter().filter(record)
        with patch.object(debug.logger, "info") as info:
            debug.log_system_event(
                "SYNTHETIC_EVENT", DebugLevel.INFO, "PRIVATE_CONTENT_SENTINEL",
                request_id="paid-attempt-not-http-identity", user_id="private-person-id",
                context={"request_id": "private-id", "question": "private question"},
            )
    info.assert_called_once()
    payload = json.loads(info.call_args.args[0].removeprefix("JSON: "))
    assert payload["request_id"] == record.http_request_id == identity
    assert "PRIVATE_CONTENT_SENTINEL" not in str(payload)
    assert "paid-attempt-not-http-identity" not in str(payload)
    assert "private-id" not in str(payload)
    assert "private-person-id" not in str(payload)
    assert "private question" not in str(payload)
    RequestContextFilter().filter(record)
    assert record.http_request_id == "-"


def test_nested_context_restores_previous_identity_even_on_error():
    first = StarletteRequest({"type": "http", "headers": []})
    second = StarletteRequest({"type": "http", "headers": []})
    with request_context(first) as first_id:
        with pytest.raises(RuntimeError):
            with request_context(second) as second_id:
                assert second_id != first_id
                raise RuntimeError("Synthetic failure")
        assert current_request_id() == first_id
        with request_context(first) as repeated:
            assert repeated == first_id
    assert current_request_id() is None
    assert create_error_response("OFFLINE", "No request").correlation_id is None


@pytest.mark.asyncio
async def test_process_monitor_never_inherits_the_first_requests_identity(monkeypatch):
    from middleware.monitoring import PerformanceMetrics

    observed = []
    released = asyncio.Event()

    async def monitor(_self):
        observed.append(current_request_id())
        await released.wait()
        observed.append(current_request_id())

    monkeypatch.setattr(PerformanceMetrics, "_monitor_system_metrics", monitor)
    metrics = PerformanceMetrics()
    request = StarletteRequest({"type": "http", "headers": []})
    with request_context(request) as identity:
        metrics.start_monitoring()
        task = metrics.monitoring_task
        metrics.start_monitoring()
        assert metrics.monitoring_task is task
        await asyncio.sleep(0)
        assert current_request_id() == identity
    released.set()
    await task
    assert observed == [None, None]
    assert current_request_id() is None


def test_logger_lookup_does_not_configure_and_explicit_configuration_is_repeatable(tmp_path):
    # Isolate root-logger configuration from pytest's own capture handlers.
    script = """
import logging
from pathlib import Path
from config.logging import FoundationalLogger, get_foundational_logger
from middleware.request_context import request_context
from starlette.requests import Request

logger = get_foundational_logger('synthetic')
assert not FoundationalLogger._configured
assert not Path('logs').exists()
external = logging.NullHandler()
logging.getLogger().addHandler(external)
FoundationalLogger.configure(log_level='WARNING', log_dir='first')
handlers = tuple(logging.getLogger().handlers)
FoundationalLogger.configure(log_level='WARNING', log_dir='first')
assert tuple(logging.getLogger().handlers) == handlers
request = Request({'type': 'http', 'headers': []})
with request_context(request) as identity:
    logger.warning('Safe diagnostic')
content = Path('first/app.log').read_text()
assert 'request_id=' + identity in content
FoundationalLogger.configure(log_level='ERROR', log_dir='second')
assert external in logging.getLogger().handlers
assert len(logging.getLogger().handlers) == len(handlers)
for handler in handlers:
    if isinstance(handler, logging.FileHandler):
        assert handler.stream is None
assert logging.getLogger().level == logging.ERROR
assert all(h.level >= logging.ERROR for h in logging.getLogger().handlers if h is not external)
"""
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
