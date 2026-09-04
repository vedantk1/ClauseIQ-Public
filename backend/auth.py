from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError as JWTError
from pydantic import BaseModel, EmailStr, Field
import secrets
import re
import uuid
from config.environments import get_environment_config

# Get settings instance
config = get_environment_config()

# Configuration
SECRET_KEY = config.security.jwt_secret_key
ALGORITHM = config.security.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = config.security.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = config.security.refresh_token_expire_days

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme
security = HTTPBearer()

# Pydantic models
class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Optional[Dict[str, Any]] = None

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[datetime] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

class VerifyEmailRequest(BaseModel):
    token: str

class UserProfileUpdate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)

# Password utilities
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)

def validate_password(password: str) -> bool:
    """Validate password strength."""
    if len(password) < 8:
        return False
    if not re.search(r"[A-Za-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True

# JWT utilities
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token with explicit type claim."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: Dict[str, Any]) -> str:
    """Create a JWT refresh token with explicit type claim."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str, expected_type: Optional[str] = "access") -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT token, optionally enforcing token type."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Enforce token type if specified
        if expected_type and payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None

def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a refresh token specifically. Rejects access/reset tokens."""
    return verify_token(token, expected_type="refresh")

def create_password_reset_token(email: str) -> str:
    """Create a password reset token with jti for one-time use."""
    token_jti = str(uuid.uuid4())
    to_encode = {"sub": email, "type": "password_reset", "jti": token_jti}
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.security.password_reset_token_expire_minutes)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_password_reset_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a password reset token and return full payload (email + jti)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            return None
        email = payload.get("sub")
        jti = payload.get("jti")
        if not email or not jti:
            return None
        return {"email": email, "jti": jti}
    except JWTError:
        return None

def create_email_verification_token(email: str) -> str:
    """Create an email verification token (24h expiry)."""
    to_encode = {
        "sub": email,
        "type": "email_verification",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_email_verification_token(token: str) -> Optional[str]:
    """Verify an email verification token. Returns the email if valid, None otherwise."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "email_verification":
            return None
        email = payload.get("sub")
        return email if email else None
    except JWTError:
        return None

# Authentication dependency
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Get current user from JWT token."""
    from database.service import get_document_service

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database using the new async service
    service = get_document_service()
    user = await service.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

# Optional authentication dependency (for endpoints that work with or without auth)
async def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))) -> Optional[str]:
    """Get current user ID from JWT token (optional)."""
    if not credentials:
        return None

    token = credentials.credentials
    payload = verify_token(token)
    if payload is None:
        return None
    return payload.get("sub")
