"""Public, non-sensitive application configuration endpoints."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from database.service import get_document_service
from middleware.api_standardization import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app-config", tags=["app-config"])


class AppConfigResponse(BaseModel):
    """Non-sensitive UI configuration for the local workspace."""

    toast_notifications_enabled: bool = True


@router.get("", response_model=APIResponse[AppConfigResponse])
async def get_app_config():
    """Return non-sensitive UI settings, falling back to safe defaults."""
    try:
        service = get_document_service()
        ui_settings = await service.get_ui_settings()
        toast_notifications_enabled = ui_settings.get(
            "toast_notifications_enabled",
            True,
        )
    except Exception as exc:
        logger.error("App configuration lookup failed: %s", type(exc).__name__)
        toast_notifications_enabled = True

    return APIResponse(
        success=True,
        data=AppConfigResponse(
            toast_notifications_enabled=toast_notifications_enabled,
        ),
    )
