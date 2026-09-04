"""Tests for request-scoped OpenAI client management."""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from services.ai.client_manager import (
    clear_request_client,
    get_openai_client,
    reset_client,
    safe_openai_call,
    set_request_client,
)


def test_get_openai_client_has_no_server_environment_fallback(monkeypatch):
    reset_client()
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-server-credential")

    assert get_openai_client() is None


def test_request_client_is_available_only_in_current_context():
    reset_client()
    request_client = object()

    set_request_client(request_client)
    assert get_openai_client() is request_client

    clear_request_client()
    assert get_openai_client() is None


@pytest.mark.asyncio
async def test_safe_call_without_request_credentials_returns_none():
    reset_client()

    async def unused_call(_client):
        raise AssertionError("The call must not run without request credentials")

    assert await safe_openai_call(unused_call) is None
