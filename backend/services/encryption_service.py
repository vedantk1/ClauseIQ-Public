"""
Encryption service for secure storage of sensitive data like API keys.
Uses Fernet (AES-256) symmetric encryption.
"""
import os
import base64
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class EncryptionService:
    """Service for encrypting and decrypting sensitive data."""

    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._initialized = False

    def _get_encryption_key(self) -> bytes:
        """
        Get or derive the encryption key from environment variable.
        The key should be at least 32 characters for security.
        """
        secret = os.getenv("API_KEY_ENCRYPTION_SECRET")

        if not secret:
            # Fall back to JWT secret if no specific encryption secret is set
            # This ensures the service works in development
            secret = os.getenv("JWT_SECRET_KEY", "")
            if not secret or len(secret) < 32:
                raise ValueError(
                    "API_KEY_ENCRYPTION_SECRET or JWT_SECRET_KEY (min 32 chars) "
                    "must be set for API key encryption"
                )

        # Use PBKDF2 to derive a proper Fernet key from the secret
        # This ensures we always get a valid 32-byte key
        salt = b"clauseiq_api_key_salt_v1"  # Static salt - OK since we derive from a secret
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return key

    def _get_fernet(self) -> Fernet:
        """Get or initialize the Fernet instance."""
        if self._fernet is None:
            key = self._get_encryption_key()
            self._fernet = Fernet(key)
            self._initialized = True
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string and return base64-encoded ciphertext.

        Args:
            plaintext: The string to encrypt (e.g., an API key)

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""

        try:
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(plaintext.encode())
            return encrypted.decode()  # Fernet output is already base64
        except Exception as e:
            logger.error("Encryption failed: %s", type(e).__name__)
            raise ValueError("Failed to encrypt data") from None

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a base64-encoded ciphertext and return plaintext.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        try:
            fernet = self._get_fernet()
            decrypted = fernet.decrypt(ciphertext.encode())
            return decrypted.decode()
        except InvalidToken:
            logger.error("Decryption failed: Invalid token (key may have changed)")
            raise ValueError("Failed to decrypt data - encryption key may have changed")
        except Exception as e:
            logger.error("Decryption failed: %s", type(e).__name__)
            raise ValueError("Failed to decrypt data") from None

    def is_initialized(self) -> bool:
        """Check if the encryption service is properly initialized."""
        try:
            if not self._initialized:
                self._get_fernet()
            return True
        except Exception:
            return False


# Global singleton instance
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Get the encryption service singleton instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
