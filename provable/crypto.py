from __future__ import annotations

from cryptography.fernet import Fernet


class CryptoConfigError(RuntimeError):
    pass


def encrypt_refresh_token(refresh_token: str, fernet_key: str) -> str:
    if not fernet_key:
        raise CryptoConfigError("fernet_key_missing")
    return Fernet(fernet_key.encode("utf-8")).encrypt(refresh_token.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(refresh_token_encrypted: str, fernet_key: str) -> str:
    if not fernet_key:
        raise CryptoConfigError("fernet_key_missing")
    return (
        Fernet(fernet_key.encode("utf-8"))
        .decrypt(refresh_token_encrypted.encode("utf-8"))
        .decode("utf-8")
    )
