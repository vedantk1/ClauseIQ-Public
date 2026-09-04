"""
Admin access control middleware.
Provides dependency for admin-only routes using environment-based email verification.
"""
import os
import logging
from typing import List
from fastapi import Depends, HTTPException, status
from dotenv import load_dotenv

from auth import get_current_user

# Load .env file to ensure ADMIN_EMAILS is available
load_dotenv()

logger = logging.getLogger(__name__)


def get_admin_emails() -> List[str]:
    """Get list of admin emails from environment variable."""
    admin_emails_str = os.getenv("ADMIN_EMAILS", "")
    if not admin_emails_str:
        return []
    # Split by comma and strip whitespace, filter empty strings
    return [email.strip().lower() for email in admin_emails_str.split(",") if email.strip()]


def is_admin_email(email: str) -> bool:
    """Check if an email is in the admin list."""
    admin_emails = get_admin_emails()
    return email.lower() in admin_emails


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that verifies the current user has admin access.

    Admin access is determined by checking if the user's email is in the
    ADMIN_EMAILS environment variable (comma-separated list).

    Returns the current user dict if they are an admin.
    Raises 403 Forbidden if they are not.
    """
    user_email = current_user.get("email", "").lower()

    if not is_admin_email(user_email):
        logger.warning("Non-admin user attempted admin access")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    logger.info("Admin access granted")
    return current_user


async def check_admin_access(current_user: dict = Depends(get_current_user)) -> bool:
    """
    Dependency that checks if current user is admin without raising exception.
    Useful for conditional UI elements.
    """
    user_email = current_user.get("email", "").lower()
    return is_admin_email(user_email)
