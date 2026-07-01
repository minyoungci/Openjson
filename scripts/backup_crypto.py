from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


BACKUP_ENCRYPTION_ALGORITHM = "fernet"
BACKUP_ENCRYPTION_KEY_ENV = "OPENJSON_BACKUP_ENCRYPTION_KEY"


def generate_backup_encryption_key() -> str:
    return Fernet.generate_key().decode("ascii")


def resolve_backup_encryption_key(explicit_key: str | None = None) -> str:
    key = explicit_key or os.environ.get(BACKUP_ENCRYPTION_KEY_ENV)
    if not key:
        raise ValueError(f"{BACKUP_ENCRYPTION_KEY_ENV} is required for encrypted backups.")
    try:
        Fernet(key.encode("ascii"))
    except Exception as exc:
        raise ValueError(f"{BACKUP_ENCRYPTION_KEY_ENV} must be a valid Fernet key.") from exc
    return key


def encrypt_backup_bytes(plaintext: bytes, key: str) -> bytes:
    return Fernet(key.encode("ascii")).encrypt(plaintext)


def decrypt_backup_bytes(ciphertext: bytes, key: str) -> bytes:
    try:
        return Fernet(key.encode("ascii")).decrypt(ciphertext)
    except InvalidToken as exc:
        raise ValueError("Backup decryption failed. Check the encryption key and backup file.") from exc
