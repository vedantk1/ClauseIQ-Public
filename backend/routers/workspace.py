"""Local workspace configuration; no registration, identity or roles."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ai_models.models import AIModelConfig
from middleware.api_standardization import create_success_response
from services.workspace_service import WorkspaceService, get_workspace_service
from services.ai.generation import AIRequestError
from workspace import get_workspace_id

router = APIRouter(prefix="/workspace", tags=["workspace"], dependencies=[Depends(get_workspace_id)])


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str | None = None
    query_gate_model_id: str | None = None
    reasoning_effort: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=36500, strict=True)
    toast_notifications_enabled: bool | None = Field(default=None, strict=True)

    @field_validator("model_id", "query_gate_model_id")
    @classmethod
    def known_model(cls, value):
        if value is not None and not AIModelConfig.is_valid_model(value):
            raise ValueError("Choose an available model")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def known_effort(cls, value):
        if value is not None and value not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Choose an available reasoning effort")
        return value


class APIKeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


@router.get("")
async def settings(service: WorkspaceService = Depends(get_workspace_service)):
    return create_success_response(await service.get_settings())


@router.put("/settings")
async def update_settings(body: SettingsUpdate, service: WorkspaceService = Depends(get_workspace_service)):
    try:
        return create_success_response(await service.update_settings(body.model_dump(exclude_none=True)))
    except AIRequestError as error:
        raise HTTPException(status_code=error.status_code, detail=error.public_message) from None


@router.put("/api-key")
async def save_key(body: APIKeyInput, service: WorkspaceService = Depends(get_workspace_service)):
    try:
        await service.set_api_key(body.api_key.get_secret_value().strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Could not save the API key. Check its format and the local credential directory permissions.") from None
    return create_success_response({"has_api_key": True})


@router.delete("/api-key")
async def remove_key(service: WorkspaceService = Depends(get_workspace_service)):
    await service.delete_api_key()
    return create_success_response({"has_api_key": False})
