"""Privacy regressions for request, exception, chat logging."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from config.logging import log_exception
from middleware.logging import SecurityLogger, StructuredLogger
from routers import chat as chat_router


PRIVATE_CONTENT = "PRIVATE_CONTENT_SENTINEL"
PRIVATE_IDENTITY = "PRIVATE_IDENTITY_SENTINEL"
PRIVATE_LOCATION = "PRIVATE_LOCATION_SENTINEL"


def _json_payload(mock_method) -> dict:
    message = mock_method.call_args.args[0]
    assert isinstance(message, str)
    return json.loads(message)


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(
        method="POST",
        headers={"user-agent": PRIVATE_IDENTITY},
        client=SimpleNamespace(host=PRIVATE_LOCATION),
        url=SimpleNamespace(path=f"/documents/{PRIVATE_CONTENT}"),
    )


def test_structured_request_and_error_logs_exclude_request_content():
    structured = StructuredLogger()
    request = _fake_request()

    with patch.object(structured.logger, "info") as mock_info:
        structured.log_request(
            request_id="safe-request-id",
            request=request,
            user_id=PRIVATE_IDENTITY,
        )

    request_payload = _json_payload(mock_info)
    request_serialized = json.dumps(request_payload)
    assert request_payload["event"] == "request_start"
    assert request_payload["method"] == "POST"
    assert "path" not in request_payload
    assert "user_id" not in request_payload
    assert "user_agent" not in request_payload
    assert "client_ip" not in request_payload
    assert PRIVATE_CONTENT not in request_serialized
    assert PRIVATE_IDENTITY not in request_serialized
    assert PRIVATE_LOCATION not in request_serialized

    with patch.object(structured.logger, "error") as mock_error:
        structured.log_error(
            request_id="safe-request-id",
            error=RuntimeError(PRIVATE_CONTENT),
            request=request,
            user_id=PRIVATE_IDENTITY,
        )

    error_payload = _json_payload(mock_error)
    error_serialized = json.dumps(error_payload)
    assert error_payload["error_type"] == "RuntimeError"
    assert "error_message" not in error_payload
    assert "traceback" not in error_payload
    assert PRIVATE_CONTENT not in error_serialized
    assert PRIVATE_IDENTITY not in error_serialized
    assert PRIVATE_LOCATION not in error_serialized


def test_security_logger_reduces_arbitrary_details_to_safe_metadata():
    security = SecurityLogger()

    with patch.object(security.logger, "warning") as mock_warning:
        security.log_suspicious_activity(
            "security_middleware_error",
            {
                "ip": PRIVATE_LOCATION,
                "path": f"/documents/{PRIVATE_CONTENT}",
                "email": PRIVATE_IDENTITY,
                "error": PRIVATE_CONTENT,
                "activity_count": 3,
            },
        )

    payload = _json_payload(mock_warning)
    serialized = json.dumps(payload)
    assert payload["type"] == "security_middleware_error"
    assert payload["metadata"]["activity_count"] == 3
    assert payload["metadata"]["redacted_field_count"] == 4
    assert PRIVATE_CONTENT not in serialized
    assert PRIVATE_IDENTITY not in serialized
    assert PRIVATE_LOCATION not in serialized


def test_foundational_exception_logger_uses_type_not_exception_message():
    logger = MagicMock()
    log_exception(logger, "send_message", RuntimeError(PRIVATE_CONTENT))

    call = logger.error.call_args
    rendered = call.args[0] % call.args[1:]
    assert "operation=send_message" in rendered
    assert "error_type=RuntimeError" in rendered
    assert PRIVATE_CONTENT not in rendered
    assert all(not isinstance(arg, Exception) for arg in call.args)


@pytest.mark.asyncio
async def test_chat_runtime_error_keeps_stable_response_and_safe_log(monkeypatch):
    class FailingChatService:
        async def get_or_create_session(self, document_id, user_id):
            raise RuntimeError(PRIVATE_CONTENT)

    monkeypatch.setattr(
        chat_router,
        "get_chat_service",
        lambda: FailingChatService(),
    )

    with patch.object(chat_router.logger, "error") as mock_error:
        with pytest.raises(HTTPException) as raised:
            await chat_router.get_or_create_session(
                document_id=PRIVATE_CONTENT,
                request=SimpleNamespace(),
                workspace_id="local",
            )

    assert raised.value.status_code == 500
    assert raised.value.detail == "Failed to get or create session"
    assert PRIVATE_CONTENT not in repr(mock_error.call_args)
    assert PRIVATE_IDENTITY not in repr(mock_error.call_args)
    assert "RuntimeError" in repr(mock_error.call_args)


@pytest.mark.asyncio
async def test_chat_preserves_classified_client_error_without_raw_service_text(
    monkeypatch,
):
    class MissingDocumentChatService:
        async def get_or_create_session(self, document_id, user_id):
            return {
                "success": False,
                "error": f"Document not found: {PRIVATE_CONTENT}",
            }

    monkeypatch.setattr(
        chat_router,
        "get_chat_service",
        lambda: MissingDocumentChatService(),
    )

    with pytest.raises(HTTPException) as raised:
        await chat_router.get_or_create_session(
            document_id=PRIVATE_CONTENT,
            request=SimpleNamespace(),
            workspace_id="local",
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "Document not found or access denied"
    assert PRIVATE_CONTENT not in raised.value.detail
