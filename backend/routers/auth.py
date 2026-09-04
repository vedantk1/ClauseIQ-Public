"""
Authentication and user management routes.
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from database.service import get_document_service
from services.auth_service import get_auth_service
from middleware.api_standardization import APIResponse, ErrorResponse, create_error_response
from middleware.versioning import versioned_response
from auth import (
    create_access_token,
    create_refresh_token,
    verify_token,
    verify_refresh_token,
    get_current_user,
    UserCreate,
    UserLogin,
    UserResponse,
    UserProfileUpdate,
    Token,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest
)
from models.auth import (
    RefreshTokenRequest,
    UserPreferencesRequest,
    UserPreferencesResponse,
    AvailableModelsResponse,
    SetApiKeyRequest,
    ApiKeyStatusResponse,
    ChangePasswordRequest,
    EmailVerificationStatusResponse
)

logger = logging.getLogger(__name__)


def _log_route_event(
    level: int,
    *,
    operation: str,
    stage: str,
    status: str,
    error: Exception = None,
) -> None:
    """Log bounded route metadata without request, user, or exception content."""
    fields = [
        f"operation={operation}",
        f"stage={stage}",
        f"status={status}",
    ]
    if error is not None:
        fields.append(f"error_type={error.__class__.__name__}")
    logger.log(level, "Authentication route event (%s)", ", ".join(fields))


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=APIResponse[Token])
async def register(user_data: UserCreate):
    """Register a new user and return authentication tokens."""
    auth_service = get_auth_service()

    success, token_data, error = await auth_service.register_user(
        full_name=user_data.full_name,
        email=user_data.email,
        password=user_data.password
    )

    if not success:
        return create_error_response(
            code="REGISTRATION_FAILED",
            message=error or "Registration failed"
        )

    return APIResponse(
        success=True,
        data=token_data,
        message="User registered successfully"
    )


@router.post("/login", response_model=APIResponse[Token])
async def login(user_data: UserLogin, request: Request):
    """Authenticate user and return tokens."""
    auth_service = get_auth_service()
    client_ip = request.client.host if request.client else "unknown"

    success, token_data, error = await auth_service.authenticate_user(
        email=user_data.email,
        password=user_data.password,
        client_ip=client_ip
    )

    if not success:
        return create_error_response(
            code="INVALID_CREDENTIALS",
            message=error or "Invalid email or password"
        )

    return APIResponse(
        success=True,
        data=token_data,
        message="Login successful"
    )


@router.post("/refresh", response_model=APIResponse[Token])
async def refresh_access_token(request: RefreshTokenRequest):
    """Refresh access token using refresh token."""
    try:
        # Step 1: Verify the provided refresh token (rejects access/reset tokens - FND-001)
        payload = verify_refresh_token(request.refresh_token)
        if not payload:
            # If verification fails, return an error response
            return create_error_response(
                code="INVALID_REFRESH_TOKEN",
                message="Invalid refresh token"
            )

        # Step 2: Extract user ID from the token payload
        user_id = payload.get("sub")
        if not user_id:
            # If user ID is missing, return an error response
            return create_error_response(
                code="INVALID_REFRESH_TOKEN",
                message="Invalid refresh token"
            )

        # Step 3: Create new access and refresh tokens for the user
        access_token = create_access_token(data={"sub": user_id})
        refresh_token = create_refresh_token(data={"sub": user_id})

        # Step 4: Prepare the token data for the response
        token_data = Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

        # Step 5: Return a successful API response with the new tokens
        return APIResponse(
            success=True,
            data=token_data,
            message="Token refreshed successfully"
        )
    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="refresh_token",
            stage="token_rotation",
            status="error",
            error=error,
        )
        return create_error_response(
            code="TOKEN_REFRESH_FAILED",
            message="Token refresh failed"
        )


@router.get("/me", response_model=APIResponse[UserResponse])
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information."""
    user_data = UserResponse(
        id=current_user["id"],
        full_name=current_user["full_name"],
        email=current_user["email"]
    )

    return APIResponse(
        success=True,
        data=user_data,
        message="User information retrieved successfully"
    )


@router.post("/forgot-password", response_model=APIResponse[dict])
async def forgot_password(request: ForgotPasswordRequest):
    """Send password reset email to user."""
    auth_service = get_auth_service()

    success, error = await auth_service.initiate_password_reset(request.email)

    # Always return success for security (don't reveal if email exists)
    return APIResponse(
        success=True,
        data={"message": "If the email exists, a password reset link has been sent"},
        message="Password reset email sent"
    )


@router.post("/reset-password", response_model=APIResponse[dict])
async def reset_password(request: ResetPasswordRequest):
    """Reset user password using reset token."""
    auth_service = get_auth_service()

    success, error = await auth_service.reset_password(request.token, request.new_password)

    if not success:
        return create_error_response(
            code="PASSWORD_RESET_FAILED",
            message=error or "Password reset failed"
        )

    return APIResponse(
        success=True,
        data={"message": "Password reset successfully"},
        message="Password reset successfully"
    )


@router.get("/preferences", response_model=APIResponse[UserPreferencesResponse])
async def get_user_preferences(current_user: dict = Depends(get_current_user)):
    """Get user's preferences including preferred AI model."""
    try:
        from ai_models.models import AIModelConfig
        service = get_document_service()

        # Get user's preferred model
        preferred_model = await service.get_user_preferred_model(current_user["id"])

        preferences_data = UserPreferencesResponse(
            preferred_model=preferred_model,
            available_models=AIModelConfig.get_model_ids()
        )

        return APIResponse(
            success=True,
            data=preferences_data,
            message="User preferences retrieved successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="get_preferences",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="PREFERENCES_FETCH_FAILED",
            message="Failed to get user preferences"
        )


@router.put("/preferences", response_model=APIResponse[dict])
async def update_user_preferences(
    preferences: UserPreferencesRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update user's preferences including preferred AI model."""
    try:
        from ai_models.models import AIModelConfig

        # Validate the model is available
        if not AIModelConfig.is_valid_model(preferences.preferred_model):
            valid_models = AIModelConfig.get_model_ids()
            return create_error_response(
                code="INVALID_MODEL",
                message=f"Invalid model. Available models: {valid_models}"
            )

        service = get_document_service()
        success = await service.update_user_preferences(
            current_user["id"],
            {"preferred_model": preferences.preferred_model}
        )

        if not success:
            return create_error_response(
                code="PREFERENCES_UPDATE_FAILED",
                message="Failed to update preferences"
            )

        return APIResponse(
            success=True,
            data={"message": "Preferences updated successfully"},
            message="Preferences updated successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="update_preferences",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="PREFERENCES_UPDATE_FAILED",
            message="Failed to update preferences"
        )


@router.put("/profile", response_model=APIResponse[UserResponse])
async def update_user_profile(
    profile_update: UserProfileUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update user's profile information."""
    try:
        service = get_document_service()

        # Update user profile
        success = await service.update_user(
            current_user["id"],
            {"full_name": profile_update.full_name}
        )

        if not success:
            return create_error_response(
                code="PROFILE_UPDATE_FAILED",
                message="Failed to update profile"
            )

        # Get updated user data to return
        updated_user = await service.get_user_by_id(current_user["id"])

        if not updated_user:
            return create_error_response(
                code="USER_NOT_FOUND",
                message="User not found after update"
            )

        return APIResponse(
            success=True,
            data=UserResponse(
                id=updated_user.get("id", ""),
                email=updated_user.get("email", ""),
                full_name=updated_user.get("full_name", ""),
                created_at=updated_user.get("created_at"),
                updated_at=updated_user.get("updated_at"),
                preferred_model=updated_user.get("preferred_model")
            ),
            message="Profile updated successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="update_profile",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="PROFILE_UPDATE_FAILED",
            message="Failed to update profile"
        )


@router.put("/password", response_model=APIResponse[dict])
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Change password for the authenticated user.
    Requires current password for verification.
    """
    auth_service = get_auth_service()

    success, error = await auth_service.change_password(
        user_id=current_user["id"],
        current_password=request.current_password,
        new_password=request.new_password
    )

    if not success:
        return create_error_response(
            code="PASSWORD_CHANGE_FAILED",
            message=error or "Failed to change password"
        )

    return APIResponse(
        success=True,
        data={"message": "Password changed successfully"},
        message="Password changed successfully"
    )


@router.get("/available-models", response_model=APIResponse[AvailableModelsResponse])
@versioned_response("1.0")
async def get_available_models():
    """Get list of available AI models with descriptions, including the currently active system model."""
    try:
        from ai_models.models import AIModelConfig
        from database.service import get_document_service

        # Get the current system model set by admin
        service = get_document_service()
        current_model_id = await service.get_system_ai_model()

        # Get the model details for the current model
        current_model_info = None
        try:
            model = AIModelConfig.get_model_by_id(current_model_id)
            current_model_info = {
                "id": model.id,
                "name": model.name,
                "description": model.description
            }
        except ValueError:
            # Fallback if model not found
            current_model_info = {
                "id": current_model_id,
                "name": current_model_id,
                "description": "System configured model"
            }

        models_data = AvailableModelsResponse(
            models=AIModelConfig.get_models_for_api(),
            default_model=AIModelConfig.get_default_model(),
            current_model=current_model_info
        )

        return APIResponse(
            success=True,
            data=models_data,
            message="Available models retrieved successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="get_available_models",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="MODELS_FETCH_FAILED",
            message="Failed to get available models"
        )


@router.post("/logout", response_model=APIResponse[dict])
async def logout(current_user: dict = Depends(get_current_user)):
    """Logout user and invalidate token."""
    try:
        # For now, we'll just return success since we're using stateless JWT tokens
        # In a production system, you'd want to add the token to a blacklist
        # or use shorter-lived tokens with server-side session management

        _log_route_event(
            logging.INFO,
            operation="logout",
            stage="response",
            status="success",
        )

        return APIResponse(
            success=True,
            data={"message": "Logged out successfully"},
            message="Logout successful"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="logout",
            stage="response",
            status="error",
            error=error,
        )
        return create_error_response(
            code="LOGOUT_FAILED",
            message="Logout failed"
        )


# ================== EMAIL VERIFICATION ==================

@router.post("/verify-email", response_model=APIResponse[dict])
async def verify_email(request: VerifyEmailRequest):
    """Verify user's email address using verification token."""
    auth_service = get_auth_service()

    success, error = await auth_service.verify_email(request.token)

    if not success:
        return create_error_response(
            code="EMAIL_VERIFICATION_FAILED",
            message=error or "Email verification failed"
        )

    return APIResponse(
        success=True,
        data={"message": "Email verified successfully"},
        message="Email verified successfully"
    )


@router.post("/resend-verification", response_model=APIResponse[dict])
async def resend_verification(current_user: dict = Depends(get_current_user)):
    """Resend email verification email to the authenticated user."""
    auth_service = get_auth_service()

    success, error = await auth_service.resend_verification_email(current_user["id"])

    if not success:
        return create_error_response(
            code="RESEND_VERIFICATION_FAILED",
            message=error or "Failed to resend verification email"
        )

    return APIResponse(
        success=True,
        data={"message": "Verification email sent"},
        message="Verification email sent successfully"
    )


@router.get("/verification-status", response_model=APIResponse[EmailVerificationStatusResponse])
async def get_verification_status(current_user: dict = Depends(get_current_user)):
    """Check if the authenticated user's email is verified."""
    status = EmailVerificationStatusResponse(
        email_verified=current_user.get("email_verified", False)
    )

    return APIResponse(
        success=True,
        data=status,
        message="Verification status retrieved successfully"
    )


# ================== API KEY MANAGEMENT ==================

@router.put("/api-key", response_model=APIResponse[dict])
async def set_api_key(
    request: SetApiKeyRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Set or update user's OpenAI API key.
    The key is encrypted before storage.
    Requires email verification.
    """
    try:
        # Check email verification
        if not current_user.get("email_verified", False):
            return create_error_response(
                code="EMAIL_NOT_VERIFIED",
                message="Please verify your email address before adding an API key. Check your inbox for a verification email."
            )

        # Validate API key format
        if not request.api_key.startswith("sk-"):
            return create_error_response(
                code="INVALID_API_KEY",
                message="API key must start with 'sk-'"
            )

        service = get_document_service()
        success = await service.set_user_api_key(current_user["id"], request.api_key)

        if not success:
            return create_error_response(
                code="API_KEY_SET_FAILED",
                message="Failed to save API key"
            )

        _log_route_event(
            logging.INFO,
            operation="set_api_key",
            stage="persistence",
            status="success",
        )

        return APIResponse(
            success=True,
            data={"message": "API key saved successfully"},
            message="API key saved successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="set_api_key",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="API_KEY_SET_FAILED",
            message="Failed to save API key"
        )


@router.delete("/api-key", response_model=APIResponse[dict])
async def delete_api_key(current_user: dict = Depends(get_current_user)):
    """Remove user's OpenAI API key."""
    try:
        service = get_document_service()
        success = await service.delete_user_api_key(current_user["id"])

        if not success:
            return create_error_response(
                code="API_KEY_DELETE_FAILED",
                message="Failed to delete API key"
            )

        _log_route_event(
            logging.INFO,
            operation="delete_api_key",
            stage="persistence",
            status="success",
        )

        return APIResponse(
            success=True,
            data={"message": "API key removed successfully"},
            message="API key removed successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="delete_api_key",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="API_KEY_DELETE_FAILED",
            message="Failed to delete API key"
        )


@router.get("/api-key/status", response_model=APIResponse[ApiKeyStatusResponse])
async def get_api_key_status(current_user: dict = Depends(get_current_user)):
    """
    Check if user has an OpenAI API key set.
    Note: This endpoint never returns the actual key for security.
    """
    try:
        service = get_document_service()
        user = await service.get_user_by_id(current_user["id"])

        has_key = bool(user and user.get("openai_api_key_set"))
        updated_at = user.get("openai_api_key_updated_at") if has_key else None

        status = ApiKeyStatusResponse(
            has_api_key=has_key,
            updated_at=updated_at
        )

        return APIResponse(
            success=True,
            data=status,
            message="API key status retrieved successfully"
        )

    except Exception as error:
        _log_route_event(
            logging.ERROR,
            operation="get_api_key_status",
            stage="persistence",
            status="error",
            error=error,
        )
        return create_error_response(
            code="API_KEY_STATUS_FAILED",
            message="Failed to get API key status"
        )
