"""Privacy regression tests for retained backend diagnostic logging."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

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
