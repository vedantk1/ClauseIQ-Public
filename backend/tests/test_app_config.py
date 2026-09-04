"""Tests for the public, non-sensitive application configuration endpoint."""

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from routers import app_config as app_config_router


class FakeDocumentService:
    def __init__(self, toast_notifications_enabled: bool):
        self.toast_notifications_enabled = toast_notifications_enabled

    async def get_ui_settings(self):
        return {
            "toast_notifications_enabled": self.toast_notifications_enabled,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_app_config_returns_configured_toast_setting(monkeypatch, enabled):
    monkeypatch.setattr(
        app_config_router,
        "get_document_service",
        lambda: FakeDocumentService(enabled),
    )

    response = await app_config_router.get_app_config()

    assert response.success is True
    assert response.data.toast_notifications_enabled is enabled


@pytest.mark.asyncio
async def test_app_config_defaults_to_toasts_enabled_on_service_error(monkeypatch):
    def raise_service_error():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        app_config_router,
        "get_document_service",
        raise_service_error,
    )

    response = await app_config_router.get_app_config()

    assert response.success is True
    assert response.data.toast_notifications_enabled is True
