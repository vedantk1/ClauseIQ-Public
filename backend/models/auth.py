"""
Authentication and user-related models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserPreferencesRequest(BaseModel):
    preferred_model: str = Field(..., description="User's preferred AI model")


class UserPreferencesResponse(BaseModel):
    preferred_model: str
    available_models: List[str]


class AvailableModelsResponse(BaseModel):
    models: List[Dict[str, str]]
    default_model: str
    current_model: Optional[Dict[str, str]] = Field(None, description="Currently active system model")


# API Key Management Models
class SetApiKeyRequest(BaseModel):
    """Request to set user's OpenAI API key."""
    api_key: str = Field(
        ...,
        min_length=20,
        description="OpenAI API key (must start with 'sk-')"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "sk-..."
            }
        }


class ApiKeyStatusResponse(BaseModel):
    """Response containing API key status (never returns the actual key)."""
    has_api_key: bool = Field(..., description="Whether user has an API key set")
    updated_at: Optional[str] = Field(None, description="When the API key was last updated")


class ChangePasswordRequest(BaseModel):
    """Request to change user's password (for authenticated users)."""
    current_password: str = Field(
        ...,
        min_length=1,
        description="User's current password for verification"
    )
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password (must be at least 8 characters with letters and numbers)"
    )


class EmailVerificationStatusResponse(BaseModel):
    """Response containing email verification status."""
    email_verified: bool = Field(..., description="Whether user's email is verified")
