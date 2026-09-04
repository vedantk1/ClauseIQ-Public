"""Privacy regression tests for backend diagnostic logging and endpoints."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from routers import admin as admin_router
from routers import ai_debug as ai_debug_router
from utils.ai_debug_helper import AIDebugLogger, DebugLevel


def _structured_payload(mock_log_method) -> dict:
    for call in mock_log_method.call_args_list:
        message = call.args[0]
        if isinstance(message, str) and message.startswith("JSON: "):
            return json.loads(message.removeprefix("JSON: "))
    raise AssertionError("Structured diagnostic payload was not logged")


def test_system_event_discards_content_credentials_and_exception_details():
    debug_logger = AIDebugLogger()
    secret_values = (
        "NOT_A_REAL_API_KEY_SENTINEL",
        "confidential contract paragraph",
        "private@example.test",
        "NOT_A_REAL_EXCEPTION_DETAIL_SENTINEL",
    )

    with patch.object(debug_logger.logger, "error") as mock_error:
        debug_logger.log_system_event(
            event_type="RAG_PIPELINE_STEP",
            level=DebugLevel.ERROR,
            message=secret_values[1],
            context={
                "duration_ms": 12.5,
                "api_key": secret_values[0],
                "email": secret_values[2],
                "request_data": {"database_uri": secret_values[3]},
                "details": {
                    "original_query": secret_values[1],
                    "chunks_found": 3,
                },
            },
            error=RuntimeError(secret_values[3]),
            user_id="private-user-id",
            request_id="private-request-id",
        )

    payload = _structured_payload(mock_error)
    serialized = json.dumps(payload)

    assert payload["event_type"] == "RAG_PIPELINE_STEP"
    assert payload["level"] == "ERROR"
    assert payload["context"]["duration_ms"] == 12.5
    assert payload["context"]["details"]["chunks_found"] == 3
    assert payload["error"] == {"type": "RuntimeError"}
    assert "traceback" not in serialized.lower()
    assert "user_id" not in serialized
    assert "request_id" not in serialized
    for secret in secret_values:
        assert secret not in serialized


def test_chat_metrics_keep_counts_without_identifiers():
    debug_logger = AIDebugLogger()

    with patch.object(debug_logger.logger, "info") as mock_info:
        debug_logger.log_chat_message_processed(
            session_id="private-session",
            document_id="private-document",
            user_id="private-user",
            message_length=123,
            response_length=456,
            sources_count=4,
            processing_time_ms=78.9,
        )

    payload = _structured_payload(mock_info)
    serialized = json.dumps(payload)

    assert payload["context"] == {
        "status": "processed",
        "message_length": 123,
        "response_length": 456,
        "sources_count": 4,
        "processing_time_ms": 78.9,
    }
    assert "private-session" not in serialized
    assert "private-document" not in serialized
    assert "private-user" not in serialized


def test_admin_log_parser_returns_metadata_without_raw_message():
    secret_message = (
        "user private-user-id failed login with token "
        "NOT_A_REAL_TOKEN_SENTINEL"
    )
    line = (
        "2026-09-04 12:00:00,001 - auth - ERROR - "
        f"[authenticate:42] - {secret_message}"
    )

    entry = admin_router.parse_log_line(line)
    serialized = json.dumps(entry)

    assert entry == {
        "timestamp": "2026-09-04 12:00:00.001",
        "level": "ERROR",
        "message": "Log entry recorded",
        "source": "auth",
        "action": "login",
    }
    assert secret_message not in serialized
    assert "private-user-id" not in serialized
    assert "NOT_A_REAL_TOKEN_SENTINEL" not in serialized


@pytest.mark.asyncio
async def test_log_endpoints_return_metadata_not_raw_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    secret_prompt = "summarize this confidential acquisition clause"
    secret_exception = "database password was leaked here"
    structured_line = (
        "2026-09-04 12:00:00 - ai_debug - ERROR - JSON: "
        + json.dumps(
            {
                "timestamp": "2026-09-04T12:00:00",
                "event_type": "RAG_PIPELINE_STEP",
                "level": "ERROR",
                "message": secret_prompt,
                "context": {
                    "step_name": "vector_retrieval",
                    "success": False,
                    "duration_ms": 25.0,
                    "details": {"original_query": secret_prompt},
                },
                "error": {
                    "type": "RuntimeError",
                    "message": secret_exception,
                    "traceback": secret_exception,
                },
            }
        )
        + "\n"
    )
    (log_dir / "error.log").write_text(structured_line, encoding="utf-8")
    (log_dir / "app.log").write_text(structured_line, encoding="utf-8")

    errors = await ai_debug_router.get_recent_errors(hours=1, current_user={})
    log_summary = await ai_debug_router.get_log_summary(current_user={})

    fake_rag_module = types.ModuleType("services.rag_service")

    class FakeRAGService:
        pass

    fake_rag_module.RAGService = FakeRAGService
    monkeypatch.setitem(sys.modules, "services.rag_service", fake_rag_module)
    rag_status = await ai_debug_router.get_rag_status(current_user={})

    combined = json.dumps(
        {"errors": errors, "log_summary": log_summary, "rag_status": rag_status}
    )
    assert secret_prompt not in combined
    assert secret_exception not in combined
    assert "traceback" not in combined.lower()
    assert "log_line" not in combined

    recent_error = errors["recent_errors"][0]
    assert recent_error["event_type"] == "RAG_PIPELINE_STEP"
    assert recent_error["context"]["step_name"] == "vector_retrieval"
    assert recent_error["context"]["duration_ms"] == 25.0
    assert recent_error["error_type"] == "RuntimeError"
    assert log_summary["log_summary"]["recent_activity"]
    assert rag_status["recent_rag_activity"]
