"""Local credential encryption without manually configured application secrets."""
import base64
import os
import stat
import tempfile
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import dotenv_values

from config.environments import get_environment_config


class EncryptionService:
    """An owner-only key file protects database-only backups, not local OS access.

    Decryption never creates a replacement key: restore missing state or enter
    a new API key. Atomic publication prevents simultaneous saves rotating it.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        if state_dir is None:
            state_dir = Path(get_environment_config().workspace_state_dir)
            if not state_dir.is_absolute():
                state_dir = Path(__file__).resolve().parents[1] / state_dir
        self.key_path = Path(state_dir) / "credential.key"

    def _fernet(self, *, create: bool) -> Fernet:
        directory = self.key_path.parent
        if create and not self.key_path.exists():
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, candidate = tempfile.mkstemp(prefix=".credential-", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(Fernet.generate_key())
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(candidate, self.key_path)
                except FileExistsError:
                    pass
            finally:
                os.unlink(candidate)
        descriptor = os.open(self.key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Credential state is not a regular file")
            if os.name == "posix" and (info.st_mode & 0o077):
                raise ValueError("Credential key file must be accessible only by its owner")
            return Fernet(handle.read())

    def encrypt(self, plaintext: str) -> str:
        try:
            return self._fernet(create=True).encrypt(plaintext.encode()).decode()
        except Exception:
            raise ValueError("Cannot access local credential state") from None

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet(create=False).decrypt(ciphertext.encode()).decode()
        except Exception:
            raise ValueError("Restore local credential state or re-enter the API key in Settings") from None


def decrypt_legacy_api_key(ciphertext: str) -> str:
    """Read old secrets solely for migration, without restoring JWT/auth support."""
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    secret = (os.environ.get("API_KEY_ENCRYPTION_SECRET") or values.get("API_KEY_ENCRYPTION_SECRET")
              or os.environ.get("JWT_SECRET_KEY") or values.get("JWT_SECRET_KEY"))
    if not secret:
        raise ValueError("Legacy credential secret is unavailable; re-enter the key in Settings")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                    salt=b"clauseiq_api_key_salt_v1", iterations=100000)
    try:
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return Fernet(key).decrypt(ciphertext.encode()).decode()
    except Exception:
        raise ValueError("Legacy credential cannot be decrypted; re-enter the key in Settings") from None


_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
