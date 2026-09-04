"""
Authentication service for ClauseIQ.

Handles user authentication, registration, password management, and token operations.
This service extracts business logic from auth router for better maintainability and testability.
"""
import hashlib
import hmac
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
    create_email_verification_token,
    verify_email_verification_token,
    validate_password,
    Token
)
from email_service import send_password_reset_email, send_verification_email
from database.service import get_document_service
from config.environments import get_environment_config

logger = logging.getLogger(__name__)


def _log_auth_event(
    level: int,
    *,
    operation: str,
    stage: str,
    status: str,
    error: Optional[Exception] = None,
    duration_ms: Optional[float] = None,
) -> None:
    """Log bounded authentication metadata without user or exception content."""
    fields = [
        f"operation={operation}",
        f"stage={stage}",
        f"status={status}",
    ]
    if error is not None:
        fields.append(f"error_type={error.__class__.__name__}")
    if duration_ms is not None:
        fields.append(f"duration_ms={duration_ms:.2f}")
    logger.log(level, "Authentication event (%s)", ", ".join(fields))


def _account_reference(email: str) -> str:
    """Return a stable keyed reference for per-account security monitoring."""
    secret = get_environment_config().security.jwt_secret_key.encode("utf-8")
    normalized_email = email.strip().lower().encode("utf-8")
    digest = hmac.new(secret, normalized_email, hashlib.sha256).hexdigest()
    return f"account-{digest[:16]}"


def _public_user(user: Dict) -> Dict:
    """Return only the user fields that are safe and useful in auth responses."""
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "created_at": user.get("created_at", ""),
        "email_verified": bool(user.get("email_verified", False)),
    }


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self):
        self.document_service = get_document_service()

    async def register_user(self, full_name: str, email: str, password: str) -> Tuple[bool, Optional[Token], Optional[str]]:
        """
        Register a new user and return authentication tokens.

        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password

        Returns:
            Tuple of (success, token_data, error_message)
        """
        try:
            # Check if user already exists
            existing_user = await self.document_service.get_user_by_email(email)
            if existing_user:
                return False, None, "User with this email already exists"

            settings = get_environment_config()
            verification_required = settings.email.verification_required

            # Email delivery is attempted before persistence so an SMTP failure
            # cannot leave behind an account that cannot complete registration.
            if verification_required:
                verification_token = create_email_verification_token(email)
                try:
                    email_sent = await send_verification_email(
                        email,
                        full_name,
                        verification_token,
                    )
                except Exception as error:
                    _log_auth_event(
                        logging.ERROR,
                        operation="register",
                        stage="verification_email_delivery",
                        status="error",
                        error=error,
                    )
                    email_sent = False

                if not email_sent:
                    return (
                        False,
                        None,
                        "Verification email could not be sent. Please try again later.",
                    )

                _log_auth_event(
                    logging.INFO,
                    operation="register",
                    stage="verification_email_delivery",
                    status="success",
                )

            # Hash password and create the user. Local development/testing
            # accounts are immediately eligible for BYOK when verification is
            # disabled; hosted environments always resolve the setting to True.
            hashed_password = get_password_hash(password)
            user_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            user_dict = {
                "id": user_id,
                "email": email,
                "hashed_password": hashed_password,
                "full_name": full_name,
                "created_at": created_at,
                "updated_at": created_at,
                "email_verified": not verification_required,
            }

            await self.document_service.create_user(user_dict)

            # Create tokens for immediate login after registration.
            access_token = create_access_token(data={"sub": user_id})
            refresh_token = create_refresh_token(data={"sub": user_id})

            token_data = Token(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                user=_public_user(user_dict),
            )

            _log_auth_event(
                logging.INFO,
                operation="register",
                stage="persistence",
                status="success",
            )
            return True, token_data, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="register",
                stage="service",
                status="error",
                error=error,
            )
            return False, None, "Registration failed"

    async def authenticate_user(
        self,
        email: str,
        password: str,
        client_ip: str = "unknown"
    ) -> Tuple[bool, Optional[Token], Optional[str]]:
        """
        Authenticate user and return tokens.

        Args:
            email: User's email address
            password: Plain text password
            client_ip: Client IP address for security monitoring

        Returns:
            Tuple of (success, token_data, error_message)
        """
        from middleware.security import security_monitor
        import time

        start_time = time.time()

        try:
            _log_auth_event(
                logging.INFO,
                operation="login",
                stage="credentials",
                status="attempt",
            )

            # Get user by email
            user = await self.document_service.get_user_by_email(email)
            if not user:
                _log_auth_event(
                    logging.WARNING,
                    operation="login",
                    stage="credentials",
                    status="rejected",
                )
                security_monitor.record_auth_failure(
                    client_ip,
                    _account_reference(email),
                )
                return False, None, "Invalid email or password"

            # Verify password
            if not verify_password(password, user["hashed_password"]):
                _log_auth_event(
                    logging.WARNING,
                    operation="login",
                    stage="credentials",
                    status="rejected",
                )
                security_monitor.record_auth_failure(
                    client_ip,
                    _account_reference(email),
                )
                return False, None, "Invalid email or password"

            # Create tokens
            access_token = create_access_token(data={"sub": user["id"]})
            refresh_token = create_refresh_token(data={"sub": user["id"]})

            # Return an explicit public projection; never serialize encrypted keys
            # or other database-only fields into an auth response.
            user_info = _public_user(user)

            token_data = Token(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                user=user_info
            )

            elapsed = time.time() - start_time
            _log_auth_event(
                logging.INFO,
                operation="login",
                stage="service",
                status="success",
                duration_ms=elapsed * 1000,
            )
            return True, token_data, None

        except Exception as error:
            elapsed = time.time() - start_time
            _log_auth_event(
                logging.ERROR,
                operation="login",
                stage="service",
                status="error",
                error=error,
                duration_ms=elapsed * 1000,
            )
            return False, None, "Login failed"

    async def initiate_password_reset(self, email: str) -> Tuple[bool, Optional[str]]:
        """
        Initiate password reset process by sending reset email.

        Args:
            email: User's email address

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Check if user exists
            user = await self.document_service.get_user_by_email(email)
            if not user:
                # Don't reveal if email exists or not for security
                # Return success even if user doesn't exist
                _log_auth_event(
                    logging.INFO,
                    operation="password_reset_request",
                    stage="request",
                    status="accepted",
                )
                return True, None

            # Create password reset token
            reset_token = create_password_reset_token(email)

            # Get user's full name for the email
            full_name = user.get("full_name", "User")

            # Send password reset email
            await send_password_reset_email(email, full_name, reset_token)

            _log_auth_event(
                logging.INFO,
                operation="password_reset_request",
                stage="request",
                status="accepted",
            )
            return True, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="password_reset_request",
                stage="service",
                status="error",
                error=error,
            )
            return False, "Password reset failed"

    async def reset_password(self, token: str, new_password: str) -> Tuple[bool, Optional[str]]:
        """
        Reset user password using reset token.
        Enforces one-time use via jti tracking (FND-002).

        Args:
            token: Password reset token
            new_password: New password (plain text)

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Verify reset token - now returns {email, jti}
            token_data = verify_password_reset_token(token)
            if not token_data:
                return False, "Invalid or expired reset token"

            email = token_data["email"]
            jti = token_data["jti"]

            # Check if this token jti has already been consumed (one-time use)
            if await self.document_service.is_reset_token_consumed(jti):
                return False, "This reset token has already been used"

            # Validate new password
            if not validate_password(new_password):
                return False, "Password does not meet requirements"

            # Get user by email
            user = await self.document_service.get_user_by_email(email)
            if not user:
                return False, "User not found"

            # Hash new password and update user
            hashed_password = get_password_hash(new_password)
            success = await self.document_service.update_user_password(email, hashed_password)

            if not success:
                return False, "Failed to update password"

            # Mark token jti as consumed so it cannot be replayed
            await self.document_service.consume_reset_token(jti)

            _log_auth_event(
                logging.INFO,
                operation="password_reset",
                stage="persistence",
                status="success",
            )
            return True, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="password_reset",
                stage="service",
                status="error",
                error=error,
            )
            return False, "Password reset failed"

    async def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Change password for an authenticated user.

        Args:
            user_id: The authenticated user's ID
            current_password: User's current password for verification
            new_password: New password (plain text)

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Get user from database
            user = await self.document_service.get_user_by_id(user_id)
            if not user:
                return False, "User not found"

            # Verify current password
            if not verify_password(current_password, user.get("hashed_password", "")):
                _log_auth_event(
                    logging.WARNING,
                    operation="password_change",
                    stage="credentials",
                    status="rejected",
                )
                return False, "Current password is incorrect"

            # Validate new password strength
            if not validate_password(new_password):
                return False, "New password must be at least 8 characters with letters and numbers"

            # Ensure new password is different from current
            if verify_password(new_password, user.get("hashed_password", "")):
                return False, "New password must be different from current password"

            # Hash and update password
            hashed_password = get_password_hash(new_password)
            success = await self.document_service.update_user(
                user_id,
                {"hashed_password": hashed_password}
            )

            if not success:
                return False, "Failed to update password"

            _log_auth_event(
                logging.INFO,
                operation="password_change",
                stage="persistence",
                status="success",
            )
            return True, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="password_change",
                stage="service",
                status="error",
                error=error,
            )
            return False, "Password change failed"

    async def verify_email(self, token: str) -> Tuple[bool, Optional[str]]:
        """
        Verify a user's email using the verification token.

        Args:
            token: Email verification JWT token

        Returns:
            Tuple of (success, error_message)
        """
        try:
            email = verify_email_verification_token(token)
            if not email:
                return False, "Invalid or expired verification token"

            user = await self.document_service.get_user_by_email(email)
            if not user:
                return False, "User not found"

            if user.get("email_verified", False):
                return True, None  # Already verified, treat as success

            success = await self.document_service.update_user(
                user["id"],
                {"email_verified": True}
            )

            if not success:
                return False, "Failed to update verification status"

            _log_auth_event(
                logging.INFO,
                operation="email_verification",
                stage="persistence",
                status="success",
            )
            return True, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="email_verification",
                stage="service",
                status="error",
                error=error,
            )
            return False, "Email verification failed"

    async def resend_verification_email(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Resend verification email for a user.

        Args:
            user_id: The authenticated user's ID

        Returns:
            Tuple of (success, error_message)
        """
        try:
            if not get_environment_config().email.verification_required:
                return False, "Email verification is disabled in this environment"

            user = await self.document_service.get_user_by_id(user_id)
            if not user:
                return False, "User not found"

            if user.get("email_verified", False):
                return False, "Email is already verified"

            email = user["email"]
            full_name = user.get("full_name", "User")

            verification_token = create_email_verification_token(email)
            email_sent = await send_verification_email(
                email,
                full_name,
                verification_token,
            )
            if not email_sent:
                return False, "Verification email could not be sent"

            _log_auth_event(
                logging.INFO,
                operation="resend_verification_email",
                stage="delivery",
                status="success",
            )
            return True, None

        except Exception as error:
            _log_auth_event(
                logging.ERROR,
                operation="resend_verification_email",
                stage="service",
                status="error",
                error=error,
            )
            return False, "Failed to resend verification email"


# Global service instance
_auth_service = None

def get_auth_service() -> AuthService:
    """Get the global auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
